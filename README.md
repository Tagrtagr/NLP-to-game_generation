# Godot Agent

Turn a single natural-language prompt into a playable Godot 4.5.1 game, streamed live into your browser. Left column: chat with per-phase progress. Right column: iframe running the freshly-built game.

The goal is to compress the first playable prototype loop for small games: idea -> design -> assets -> Godot implementation -> browser-playable build -> saved replay URL.

Target: **2–3 min common-case, up to ~5 min worst-case with repairs**. SSE streams every phase — design tokens, asset thumbnails, code file writes, build stdout, QA screenshots — so slow feels *progressing*, not stuck.

## Research lineage

This agent is a direct implementation of a recognizable research pattern. Credited explicitly because the architecture choices come from these papers, not from scratch:

- **LayoutVLM** (Sun et al., CVPR 2025) — separating semantic planning from code synthesis, with structured output in a DSL consumed by a deterministic engine. Maps to our `design → synthesize` split: Claude produces a strict `GameDesign` DSL (pydantic-validated); a deterministic applier turns it into Godot scenes/scripts.
- **Voyager** (Wang et al., NVIDIA) — execution-feedback loops that repair code against the real runtime. Maps to our build + visual-QA repair loops, governed by a global budget so worst-case latency stays bounded.
- **Holodeck** (Yang et al., CVPR 2024) — LLM-driven scene composition combining asset retrieval with classical rendering beats pure generative approaches. Maps to our template-guided synthesis + bundled-fallback asset tier: generated-first, retrieved-when-generation-fails, always-plays-via-Godot.

Prior art we learned from and explicitly compete against: [htdt/godogen](https://github.com/htdt/godogen) — same idea, CLI-only, hours per run. We target minutes-not-hours via (a) template-guided synthesis over from-scratch, (b) bounded parallel asset generation with circuit-broken fallbacks, (c) bounded self-repair, (d) schema-validated design with an optional critic pass.

Templates are **forked from and inspired by community starters** (Godot's Your First 2D/3D Game, GDQuest open-source kits, Kenney Starter Kits) and polished on top. Key sources are credited below.

## AI usage and attribution

AI tools were used heavily and intentionally:

- **ChatGPT/Codex** helped implement, debug, review, and document the codebase, including backend endpoints, frontend state handling, tests, deployment notes, and repository hygiene.
- **Anthropic Claude** is used by the app at runtime for structured game design and Godot code synthesis.
- **Google Gemini** is used by the app at runtime for design critique and visual QA on generated web builds.
- **OpenAI `gpt-image-1`, PixelLab, and Tripo** are used by the app at runtime for image and 3D asset generation when keys are configured.

The project architecture, source code, prompts, templates, tests, and deployment wiring were assembled and iterated by the student with AI assistance. External inspiration and borrowed/forked starting points are credited in this README and in template READMEs. Generated game outputs are examples of the system's behavior, not hand-authored demo levels.

## Source and asset credits

- Godot engine and web export behavior are based on Godot 4.5.1 and Godot's official beginner game patterns, especially the official [Your first 2D game](https://docs.godotengine.org/en/4.0/getting_started/first_2d_game/index.html) tutorial.
- Template structure and Godot idioms were informed by GDQuest's open-source Godot learning material and demos, including the [gdquest-demos GitHub organization](https://github.com/gdquest-demos) and GDQuest's [Godot 4 getting-started demos](https://github.com/gdquest-demos/getting-started-with-godot-4).
- Optional fallback art/audio roles map to Kenney assets. Kenney states that game assets on its asset pages are public-domain/CC0 licensed; this repo does not vendor the full asset bundle by default. Installers and manifests expect assets from Kenney's [asset library](https://www.kenney.nl/assets) or [Game Assets All-in-1](https://kenney.itch.io/kenney-game-assets).
- Runtime provider outputs come from the API keys configured by the user: Anthropic/OpenRouter, Google Gemini, OpenAI image generation, PixelLab, and Tripo.

## Stack

- **Backend:** Python 3.11, FastAPI, `uv`, `sse-starlette`, Playwright (chromium headless for QA).
- **Frontend:** Vite + React + TypeScript + Tailwind. Two columns; five phase cards; asset thumbnail grid; amber-outlined fallback indicator.
- **Engine:** Godot 4.5.1 headless, single-threaded web export (`variant/thread_support=false`) — no SharedArrayBuffer, no COOP/COEP, loads in every browser iframe.
- **LLMs:** Anthropic Claude Opus 4.7 (design + code synthesis), Google Gemini 3 Flash (design critic + visual QA).
- **Assets:** PixelLab (2D pixel) · `gpt-image-1` (2D backgrounds/UI) · Tripo v2.5 (3D meshes, fast mode). Every generation call is wrapped in a circuit-broken fallback resolver keyed against Kenney CC0 roles; if the optional Kenney files are not installed, the resolver writes palette-matched placeholders.
- **SFX:** deterministic lookup from `sfx/sfx_manifest.json` — no generated audio path. Optional Kenney CC0 clips; missing files degrade to short silent WAVs so references still load.

## Run locally

```bash
./scripts/bootstrap.sh                           # Godot + templates + node + uv + Playwright
cp backend/.env.example backend/.env             # fill in API keys (all four)
cd backend && uv run uvicorn app:app --reload    # localhost:8000
cd frontend && npm run dev                       # localhost:5173
```

Required env vars in `backend/.env`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (for `gpt-image-1`), `GEMINI_API_KEY`, `TRIPO_API_KEY`, `PIXELLAB_API_KEY`. Pipeline will surface a clear error per missing key rather than failing silently.

For production frontend builds, set `VITE_API_BASE_URL` to the public backend URL. In local Vite development, `/api` and `/workspaces` are proxied to `localhost:8000`; alternatively run `VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev`.

### Canonical test prompts

Three prompts that exercise the full matrix:

- **Specific 2D** → *"a cozy 2D platformer where a cat collects yarn balls"* — routes to `platformer_2d`, exercises PixelLab sprites, tileset, shader.
- **Specific 3D** → *"third-person explorer on a floating island"* — routes to `walker_3d`, exercises Tripo meshes, sky-gradient shader, camera rig.
- **Vague** → *"make something fun"* — exercises the design-phase rescue path: schema forces the model to commit to one verb, one style, one template.

### Replaying past runs

Every session persists under `backend/workspaces/<sid>/` (gitignored) and is static-served. Open `http://localhost:8000/workspaces/<sid>/web/index.html` to replay any prior generation without regenerating. `GET /api/stream/<sid>` also replays the full SSE event history (new subscribers get history before live events).

Saved games are exposed through `GET/POST/DELETE /api/saves`. In local development, saved-game metadata is stored in `backend/saved_games/index.json` and playable builds point at local `/workspaces/...` URLs. In production, setting Postgres and DigitalOcean Spaces/S3-compatible environment variables stores metadata durably and uploads each generated `web/` folder to object storage so saved games survive container redeploys.

### Approximate cost per run

- **2D (platformer_2d / topdown_2d):** ~$0.30–0.60. Dominated by Opus design + Sonnet synthesize; PixelLab sprites are cheap; 3–5 `gpt-image-1` calls at ~$0.04 each.
- **3D (walker_3d):** ~$0.60–1.20. Tripo v2.5 fast mode dominates ($0.10–0.30 per mesh × 5 meshes); Sonnet repair loops can add another Opus/Sonnet call or two.
- **Vague prompt rescue:** +1 re-sample if design validation fails; ~$0.05 delta.

## Architecture

```
POST /api/generate  ──SSE──▶  5 phases, shared RepairBudget(cap=3)

 1. Design      Claude × N   →  optional Gemini critic → GameDesign DSL   ~25–40s
 2. Assets      bounded gather{ PixelLab | gpt-image-1 | Tripo } ┐
                              ↓ garbage / scale checks          │
                              ↓ per-service circuit breaker     │       ~30–90s
                              ↓ installed Kenney or placeholder fallback ┘
 3. Synthesize  Claude edit-plan JSON → path-safe applier →
                structural + Godot stderr sanity loop (repairs spend budget) ~30–60s
 4. Build       godot --headless --export-release "Web"
                single-threaded → no COOP/COEP                          ~15–30s
                stderr → Claude repair (spends budget)
 5. QA          Playwright polls window.__GODOT_READY__ →
                3 screenshots → Gemini Flash critic                     ~15–25s
                critical issue → repair (spends budget) → rebuild → re-QA
```

Every phase yields `Event(phase, step, status, detail, payload?)` onto the SSE stream; the frontend renders a status dot + per-step log per card. Asset thumbnails stream in as they resolve. Terminal `qa:ready` event carries `web_rel` + `qa_ok` + `qa_screenshots` + `budget_used` + `budget_trace`, at which point the iframe swaps in.

### Why a global repair budget

Per-phase caps of 2 can stack to 6 (synthesize fixes × 2 + build fixes × 2 + QA fixes × 2), pushing worst-case latency past 5 minutes and cost past $5/run. We cap at **3 total repairs** across the three phases. When exhausted, the pipeline ships what it has with `budget_trace` showing exactly where the budget went (e.g. `synthesize_repair:1, build_repair:1, qa_repair:1`).

### Why template-guided + fallback-guarded

- Polished Godot templates from zero are 8–15 hours of craft each. Forking community starters brings per-template cost to 3–5h.
- Any generated asset can fail (timeout, garbage output, scale-mismatch for 3D). Every `Asset` in `GameDesign` has a required `fallback_role` validated at design-time against `fallback_assets/manifest.json`. On generation failure, the resolver either copies an installed Kenney file or writes a valid placeholder — the game always has a loadable resource.
- 3D is treated as flakier than 2D: aggressive fallback posture + walker_3d template's stable primitive controller means a total Tripo outage still produces a 3D scene, not a silent downgrade to 2D.

### Ready-signal protocol

Every template ships `autoload/ready_signal.gd` that sets `window.__GODOT_READY__ = true` one frame after main-scene load via JavaScriptBridge. Phase 5 polls this — no racing splash screens, no guessing timings. Invariant enforced in per-template docs + synthesize prompt hard rules.

### Shared `ScreenShake` autoload

Tier-1 templates register `ScreenShake` as a second autoload: one API (`ScreenShake.kick(amount, duration)`), finds the active camera via the viewport, decays quadratically, 2D/3D flavors. Synthesize wires it into impact / pickup / win moments so `GameDesign.juice` produces real screen shake instead of guidance prose.

## Repo layout

```
backend/
  app.py                          FastAPI: POST /api/generate (SSE), /workspaces static
  agent/
    pipeline.py                   5-phase orchestrator, owns the RepairBudget
    design.py                     schema-validated design + Gemini critic
    assets.py                     resolve_all: gather + circuit-broken fallback
    clients/                      pixellab.py, gpt_image.py, tripo.py
    garbage.py                    per-service output validation
    breaker.py                    per-session per-service CircuitBreaker
    budget.py                     shared RepairBudget(cap=3)
    synthesize.py                 edit-plan applier + sanity loop + repair helpers
    build.py                      godot headless export + repair hook
    qa.py                         Playwright + Gemini Flash vision
    schema.py                     GameDesign (pydantic) + manifest cross-validators
    sfx.py                        deterministic SFX lookup
    saved_games.py                local/Postgres save metadata + Spaces/S3 upload
  godot_templates/
    platformer_2d/  walker_3d/  topdown_2d/       (tier 1, polished)
  godot_context/                  api_cheatsheet, shader_snippets, per_template_notes
  fallback_assets/                Kenney packs + manifest.json
  sfx/                            Kenney SFX + sfx_manifest.json
  prompts/                        design.md, design_critic.md, synthesize.md, qa.md
  workspaces/                     per-session generated projects (gitignored)
frontend/
  src/
    App.tsx  Chat.tsx  PhaseCard.tsx  GameFrame.tsx   two-column UI
    sse.ts                        fetch-based SSE parser (EventSource only does GET)
    useGenerate.ts                single hook; per-phase state + thumbnails + budget
scripts/
  bootstrap.sh                    Godot + templates + node + uv + Playwright chromium
```

## Evaluation evidence

Evidence collected:

- **Automated regression tests:** `cd backend && uv run pytest tests/test_regressions.py` passed with 24 tests, covering build-error detection, asset fallback/resize behavior, synthesize sanity checks, local saved games, and object-storage save wiring.
- **Frontend build:** `cd frontend && npm run build` passed, confirming the TypeScript/Vite production bundle compiles.
- **Lint check:** `cd backend && uv run ruff check app.py agent/saved_games.py tests/test_regressions.py` passed for the recently added backend save path.
- **Local smoke test:** backend and frontend were started locally; a fake exported web build was saved through `POST /api/saves`, appeared in the Saved Games list, loaded in the iframe, and was then deleted.
- **Qualitative prompt matrix:** canonical prompts cover 2D platformer, top-down 2D, 3D walker, and vague-prompt rescue. Results are judged on playability, prompt alignment, visual coherence, repair count, and whether progress remains visible during slow phases.

## Differentiation levers (why output beats generic code agents)

1. **PixelLab for pixel art** — game-native characters + animations, consistent across assets.
2. **Always-on shader** — every ship ships with ≥1 web-safe node material shader from `shader_snippets.md` (outline, water, dither, sky gradient). Massive aesthetic lift for free.
3. **Locked palette + style sentence** applied to every asset prompt → visually cohesive even under fallback.
4. **Template-guided synthesis** — the template already runs; Claude customizes. Avoids "from-scratch → hours → lifeless".
5. **Visual QA on the real web build** — catches WebGL quirks, font fallbacks, canvas sizing that editor-mode QA misses.
6. **Single-threaded web export** — zero deployment friction; game just runs in the iframe.
7. **Per-asset streaming** in chat → user watches the game assemble in real time.

## Honest limitations

Written to be useful to the reviewer, not to sell.

**Works reliably**
- All three tier-1 templates end-to-end (platformer_2d, walker_3d, topdown_2d).
- Fallback asset tier catches external API outages — a full Tripo outage still produces a 3D game with loadable placeholder or installed Kenney assets, not a silent downgrade to 2D.
- Single-threaded export loads in every major browser with no headers.
- SSE progress is continuous; the UI never shows a phantom "stuck" state — the elapsed timer + current-phase label stay live.

**Flaky**
- Tripo quality on abstract prompts (e.g. "a floating castle of language") is uneven; the Kenney fallback often looks better than the generated mesh.
- Shader customizations occasionally desaturate the palette when Claude re-keys uniforms from the `art_style` sentence rather than the `palette` array; visual QA catches most but not all.
- PixelLab skeleton animation loop seams are visible on some sprites.
- Gemini Flash QA occasionally false-positives on intentionally-dark scenes (reading them as "blank"); the budget cap limits the damage to one wasted repair per run.

**Known failure modes**
- Prompts requiring genre fusion outside the template library (e.g. "a rhythm game") — agent picks the closest template and the result will feel off. Not mitigated; the template set is the ceiling.
- Very long prompts (>500 words) can exceed the design-phase context budget and truncate.
- Headless Playwright on CI/CD without GPU may fail to initialize WebGL — QA surfaces a `playwright error` event and we ship without the QA step, which is the right failure mode (the game still loads).
- Repair budget is global to a session, not per-user-turn — if the first build round uses all 3 repairs, a subsequent iterative edit in the same session has nothing left. Iterative editing is a v1 non-goal.

## What I'd fix with more time

- Generated music (Suno/ElevenLabs) for title + gameplay loops.
- Rhythm and card-game templates — the obvious gaps.
- Multi-turn edit mode with localized rebuilds (architecture supports it; UI is single-shot).
- A richer `GameDesign.juice` compiler that emits concrete screen-shake / particle nodes rather than relying on synthesize to translate guidance text.
- A telemetry pass on per-phase latency + repair rates across the three canonical prompts to tune the budget split.
- User accounts and per-user saved-game ownership.

## Non-goals (v1)

Generated music, multi-turn editing UI, auth / multi-tenant, mobile controls.
