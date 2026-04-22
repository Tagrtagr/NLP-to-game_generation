# Godot Game Generation Agent — Writeup

## Problem statement

Turn a single natural-language prompt into a playable Godot 4.5.1 game, rendered live in a browser iframe. Two-column UI: prompt + streamed progress on the left, the running game on the right.

## Prioritization

Four evaluation axes: prompt alignment, playability, aesthetic, and the user not feeling stuck. Ranking under a fixed time budget:

1. **Never feel stuck.** A minute of silence is fatal; a minute of visible per-step progress is fine. This forced SSE streaming as a hard requirement and set the design of the phase-card UI.
2. **Always ship *something* playable.** Never show a broken or empty iframe. This drove the fallback-first asset pipeline and the "budget-exhausted but shippable" synthesize exit.
3. **Aesthetic by default.** At least one shader, locked palette, style-sentence prefix on every asset prompt, juice list required.
4. **Alignment last** — the template picker and the GameDesign schema carry most of this, so it gets handled upstream.

## Pipeline

Five phases, each emitting SSE events the frontend renders as live phase cards.

**1. Design (~40–90 s).** Opus 4.7 returns a `GameDesign` (Pydantic: dimension, template, controls, mechanics, camera, signals, palette, juice, assets, shaders, sfx_map). A Gemini Flash critic picks the winner from N candidates under an anti-blandness bias; fallbacks and sfx are validated against the bundled manifests so the model cannot hallucinate filenames. Current `TEMPERATURES = (0.7,)` — single candidate — because Anthropic's 4K output-tokens-per-minute org cap is hit easily by best-of-3.

**2. Assets (~30–90 s).** `asyncio.gather` across every asset. Each task runs inside a generate-or-fallback wrapper. Timeouts: PixelLab 20 s (sprites), `gpt-image-1` 25 s (bg/UI), Tripo 60 s (meshes). Garbage detectors per service (near-uniform PNG, tiny GLB, bbox-diagonal-off-by-10×). A per-session circuit breaker short-circuits a service to fallback after 2 consecutive failures. If both the API and the bundled Kenney asset are unavailable, a palette-themed PIL placeholder (vertical gradient for `bg`, solid mid-tone otherwise) is written; the game always ships.

**3. Synthesize (~30–90 s).** Template copied to the session workspace. Sonnet 4.6 receives the full file tree + `GameDesign` + resolved asset manifest + SFX manifest + API/shader snippets + per-template notes. Returns a strict JSON edit plan (`{files: [{path, content}]}`). Sanity pass checks: balanced braces, `extends` on scripts, `res://` refs resolve to real files (including `project.godot`), input actions declared, banned inline `load()`/`preload()` in `.tscn`/`.tres` (runtime parse error). Failures feed back into a repair loop.

**4. Build (~15–30 s).** `godot --headless --export-release "Web"`. `threads=false` in the preset → single-threaded WASM, no COOP/COEP headers needed, runs in every browser.

**5. QA (~15–25 s).** Playwright Chromium polls `window.__GODOT_READY__` (set by the per-template `ready_signal` autoload), captures 3 screenshots at ready+0/3/6s, Gemini Flash reviews for blank-screen / missing-texture / broken-scale. Runs after the iframe is already visible; only triggers a repair on critical issues.

**Global repair budget = 3** iterations total across synthesize + build + QA combined. Hard cap on worst-case latency and cost. `SessionManager` owns the pipeline as a detached `asyncio.Task`; SSE disconnect no longer cancels the job. A `/api/cancel/{sid}` endpoint gives the user explicit termination.

## Load-bearing contracts

- **SSE event schema.** Every phase emits `{phase, step, status, detail, payload}`. This is the single contract the frontend, QA repair trigger, and history replay all key off — the phase cards, the detached pipeline, and `GET /api/stream/{sid}` resuming from a reconnect all fall out of one shape.
- **Workspaces as replayable history.** Every session persists `_log/design_candidates.json`, `_log/synthesize.json`, and `qa/*.png`. The full event stream can be re-served on reconnect (history replay before live events), and any past run is a static URL away. Makes debugging and the future gallery UI free.
- **Ready-signal autoload.** Every template ships an autoload that sets `window.__GODOT_READY__ = true` via JavaScriptBridge once the main scene loads. QA polls this instead of racing a timer — removes an entire class of flaky screenshot timing bugs.
- **Anti-blandness critic.** The Gemini Flash critic prompt is not a neutral rubric grader; it explicitly rejects hedging, generic verbs, empty juice, unpicked art direction. An opinionated taste filter is what keeps "make something fun" from collapsing into a generic asset dump.
- **Hot-reloadable prompts.** `prompts/*.md` are loaded per-call. Design and synthesize prompts can be tuned without a server restart, tightening the iteration loop.

## How to run

```bash
./scripts/bootstrap.sh                          # Godot + export templates + Playwright + uv sync
cd backend && uv run uvicorn app:app --reload   # :8000
cd frontend && npm run dev                      # :5173
```

Open `http://localhost:5173`, type a prompt, click Generate. Typical wall-clock: 2–3 min for 2D, 3–4 min for 3D. All sessions persist at `backend/workspaces/<sid>/web/index.html` and are static-served — bookmark to replay. Previously-promoted games can live in `backend/gallery/` (tracked in git, stripped of the 37 MB wasm).

## Key decisions

- **Template-guided synthesis over from-scratch.** Forking polished community starters (Godot 2D/3D getting-started, GDQuest, Kenney kits) brings per-template craft from ~10 hrs to ~3. The template already runs; the LLM only customizes.
- **Strict schema + manifest-validated references.** `GameDesign` is a Pydantic model; every `fallback_role` must key into `fallback_assets/manifest.json` and every `sfx_map` value must key into `sfx_manifest.json`. The LLM cannot hallucinate a filename or a role that doesn't exist — validation failures are re-prompted with the violation.
- **Sanity check as primary quality gate.** Balanced braces, `extends` declarations, `res://` refs resolving to real files (including `project.godot`'s `main_scene`), banned `load()`/`preload()` in `.tscn`/`.tres`. This catches "exports cleanly, runs blank" bugs that Godot's own exporter will not.
- **Locked art_style + palette applied to every asset prompt.** Single style sentence and 4–6 hex codes are injected into every image/mesh prompt. Cheap to implement, single largest aesthetic-cohesion lever.
- **Shader snippets library.** Every game ships with ≥1 shader from a hand-tuned set (CRT, water, outline, dither, sky-gradient, palette-lock). Large aesthetic upgrade at near-zero per-game cost.
- **Generated-first, bundled-fallback assets.** The resolver always returns something; the pipeline cannot fail the asset phase. Combined with the repair budget, this produces a "best-effort but guaranteed-shippable" system.
- **Global repair budget (cap = 3).** Per-phase caps of 2 each stack to 6 worst-case; a single shared counter caps total wall-clock and API cost deterministically.
- **File-level generation + headless export**, not MCP / live editor. Faster, simpler, one-shot appropriate.
- **Single-threaded web export.** Eliminates SharedArrayBuffer + iframe CORS pain.
- **QA reads what the user sees.** Playwright on the web build, not Godot editor-mode — catches WebGL, font, and canvas-sizing bugs Godot itself doesn't.
- **Opus 4.7 for design, Sonnet 4.6 for synthesize, Gemini Flash for critic + QA.** Design needs taste + schema adherence; synthesize needs speed + 16k output tokens; QA needs cheap multimodal.
- **Streaming UX as a first-class feature.** Phase cards, per-asset thumbnails, live step details. The point isn't speed — it's that slow-but-progressing never feels stuck.

## Bugs encountered during build

- **Renderer mismatch.** Templates shipped with `forward_plus` (requires WebGPU, broken on Chromium-web). Flipped all three tier-1 templates to `gl_compatibility`.
- **Blank canvas despite successful export.** `project.godot` referenced a `main_scene` whose file was never created. Sanity check extended to scan `project.godot` for `res://` refs.
- **Second blank canvas.** Scenes contained inline `load("res://sfx/foo.wav")` — valid in scripts, invalid in `.tscn`/`.tres` (runtime parse error). Sanity now bans `load()`/`preload()` inside scene/resource files.
- **Magenta placeholder assets.** When both API and bundled fallback fail, a PIL placeholder was drawn. Originally magenta + text label. Rewritten to a palette-themed gradient (bg) or mid-tone solid so fallback assets blend with the design's palette.
- **Cancel button broken.** After detaching the pipeline into a background task, SSE disconnect no longer terminated it. Added `POST /api/cancel/{sid}` + `CancelledError` handling in `SessionManager`.
- **Frontend phase cards stayed idle forever.** sse-starlette emits `\r\n\r\n` between events; the frontend was splitting on `\n\n`. Zero events were ever parsed. Split now uses `/\r?\n\r?\n/`. This was the single most misleading bug — backend was fully working; only the UI looked stuck.
- **PixelLab 422.** Designs specifying 24×24 pickups were rejected (API requires ≥32×32 area). Client now clamps width/height to ≥32.
- **Anthropic 429.** The synthesize repair loop fires up to 3 Sonnet calls back-to-back, tripping the 4K output-tokens-per-minute org cap and aborting the run. `claude_json` now retries up to 4× honoring `retry-after`, with exponential backoff.

## Shortcomings + next steps

- **Single design candidate.** Best-of-3 is in the code but disabled to stay under the token-rate cap. With a higher cap or streamed token accounting, re-enabling it would measurably raise taste-floor on vague prompts.
- **3D is flakier than 2D.** Walker_3d has more scene surface (camera rig + physics + third-person controller), so Claude takes more repair rounds. Shrinking the template's wired surface or splitting synthesize into two smaller calls (scene vs. scripts) would help.
- **No token-stream in the Design card.** Users see "fanout start" then silence for ~60 s. Streaming Claude chunks to the UI would remove the only remaining perceived-stuck window.
- **Gallery / session history is CLI-only.** A `GET /api/sessions` + sidebar list is ~30 min of work and would let users reopen past games without URL bookmarks.
- **Fallback asset packs ship empty.** Kenney manual download required per `bootstrap.sh`; only palette placeholders currently render. Non-blocking (pipeline ships regardless) but a polish hit.
- **No generated music.** Bundled loops only.
- **Pre-template coverage.** `shooter_2d`, `puzzle_2d`, `adventure_3d` exist in plan but aren't polished. Rhythm / card-game templates are absent; prompts in those genres will map to the closest tier-1 template and feel off.
