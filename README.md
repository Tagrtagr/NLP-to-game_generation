# Godot Agent

Turn a single natural-language prompt into a playable Godot 4.5.1 game, streamed live into your browser. Left column: chat with per-phase progress. Right column: iframe running the freshly-built game.

Target: **2–3 min common-case, up to ~5 min worst-case with repairs**. SSE streams every phase — design tokens, asset thumbnails, code file writes, build stdout, QA screenshots — so slow feels *progressing*, not stuck.

> **Reviewer notes:** [`WRITEUP.md`](WRITEUP.md) / [`WRITEUP.pdf`](WRITEUP.pdf) — single-document summary of pipeline, decisions, bugs encountered during build, and next steps.

## Research lineage

This agent is a direct implementation of a recognizable research pattern. Credited explicitly because the architecture choices come from these papers, not from scratch:

- **LayoutVLM** (Sun et al., CVPR 2025) — separating semantic planning from code synthesis, with structured output in a DSL consumed by a deterministic engine. Maps to our `design → synthesize` split: Claude produces a strict `GameDesign` DSL (pydantic-validated); a deterministic applier turns it into Godot scenes/scripts.
- **Voyager** (Wang et al., NVIDIA) — execution-feedback loops that repair code against the real runtime. Maps to our build + visual-QA repair loops, governed by a global budget so worst-case latency stays bounded.
- **Holodeck** (Yang et al., CVPR 2024) — LLM-driven scene composition combining asset retrieval with classical rendering beats pure generative approaches. Maps to our template-guided synthesis + bundled-fallback asset tier: generated-first, retrieved-when-generation-fails, always-plays-via-Godot.

Prior art we learned from and explicitly compete against: [htdt/godogen](https://github.com/htdt/godogen) — same idea, CLI-only, hours per run. We target minutes-not-hours via (a) template-guided synthesis over from-scratch, (b) parallel asset generation with circuit-broken fallbacks, (c) bounded self-repair, (d) best-of-N taste floor on design.

Templates are **forked from community starters** (Godot's Your First 2D/3D Game, GDQuest open-source kits, Kenney Starter Kits) and polished on top. Credited in each template's `README.md`.

## Stack

- **Backend:** Python 3.11, FastAPI, `uv`, `sse-starlette`, Playwright (chromium headless for QA).
- **Frontend:** Vite + React + TypeScript + Tailwind. Two columns; five phase cards; asset thumbnail grid; amber-outlined fallback indicator.
- **Engine:** Godot 4.5.1 headless, single-threaded web export (`variant/thread_support=false`) — no SharedArrayBuffer, no COOP/COEP, loads in every browser iframe.
- **LLMs:** Anthropic Claude Opus 4.7 (design + code synthesis), Google Gemini 3 Flash (design critic + visual QA).
- **Assets:** PixelLab (2D pixel) · `gpt-image-1` (2D backgrounds/UI) · Tripo v2.5 (3D meshes, fast mode). Every generation call is wrapped in a circuit-broken fallback resolver keyed against bundled Kenney CC0 packs.
- **SFX:** deterministic lookup from `sfx/sfx_manifest.json` — no generated audio path. Kenney CC0 clips only.

## Run locally

```bash
./scripts/bootstrap.sh                           # Godot + templates + node + uv + Playwright
cp backend/.env.example backend/.env             # fill in API keys (all four)
cd backend && uv run uvicorn app:app --reload    # localhost:8000
cd frontend && npm run dev                       # localhost:5173
```

Required env vars in `backend/.env`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (for `gpt-image-1`), `GEMINI_API_KEY`, `TRIPO_API_KEY`, `PIXELLAB_API_KEY`. Pipeline will surface a clear error per missing key rather than failing silently.

### Canonical test prompts

Three prompts that exercise the full matrix:

- **Specific 2D** → *"a cozy 2D platformer where a cat collects yarn balls"* — routes to `platformer_2d`, exercises PixelLab sprites, tileset, shader.
- **Specific 3D** → *"third-person explorer on a floating island"* — routes to `walker_3d`, exercises Tripo meshes, sky-gradient shader, camera rig.
- **Vague** → *"make something fun"* — exercises the design-phase rescue path: schema forces the model to commit to one verb, one style, one template.

### Replaying past runs

Every session persists under `backend/workspaces/<sid>/` (gitignored) and is static-served. Open `http://localhost:8000/workspaces/<sid>/web/index.html` to replay any prior generation without regenerating. `GET /api/stream/<sid>` also replays the full SSE event history (new subscribers get history before live events).

### Approximate cost per run

- **2D (platformer_2d / topdown_2d):** ~$0.30–0.60. Dominated by Opus design + Sonnet synthesize; PixelLab sprites are cheap; 3–5 `gpt-image-1` calls at ~$0.04 each.
- **3D (walker_3d):** ~$0.60–1.20. Tripo v2.5 fast mode dominates ($0.10–0.30 per mesh × 5 meshes); Sonnet repair loops can add another Opus/Sonnet call or two.
- **Vague prompt rescue:** +1 re-sample if design validation fails; ~$0.05 delta.

## Architecture

```
POST /api/generate  ──SSE──▶  5 phases, shared RepairBudget(cap=3)

 1. Design      Claude × 3   →  Gemini critic  →  GameDesign DSL         ~25–40s
 2. Assets      asyncio.gather{ PixelLab | gpt-image-1 | Tripo } ┐
                              ↓ garbage / scale checks          │
                              ↓ per-service circuit breaker     │       ~30–90s
                              ↓ bundled Kenney fallback         ┘
 3. Synthesize  Claude edit-plan JSON → path-safe applier →
                structural sanity loop (repairs spend budget)           ~30–60s
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
- Any generated asset can fail (timeout, garbage output, scale-mismatch for 3D). Every `Asset` in `GameDesign` has a required `fallback_role` validated at design-time against `fallback_assets/manifest.json`. On generation failure, a synchronous file copy can't itself fail — the game always ships.
- 3D is treated as flakier than 2D: aggressive fallback posture + walker_3d template embeds a Kenney humanoid so a total Tripo outage still produces a stylistically-coherent 3D scene, not a 2D game when the user asked for 3D.

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
    design.py                     best-of-3 + Gemini critic
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

## Differentiation levers (why output beats generic code agents)

1. **PixelLab for pixel art** — game-native characters + animations, consistent across assets.
2. **Always-on shader** — every ship ships with ≥1 from `shader_snippets.md` (CRT, outline, water, dither, palette_lock, sky gradient, chromatic aberration, grain). Massive aesthetic lift for free.
3. **Locked palette + style sentence** applied to every asset prompt → visually cohesive even under fallback.
4. **Template-guided synthesis** — the template already runs; Claude customizes. Avoids "from-scratch → hours → lifeless".
5. **Visual QA on the real web build** — catches WebGL quirks, font fallbacks, canvas sizing that editor-mode QA misses.
6. **Single-threaded web export** — zero deployment friction; game just runs in the iframe.
7. **Per-asset streaming** in chat → user watches the game assemble in real time.

## Honest limitations

Written to be useful to the reviewer, not to sell.

**Works reliably**
- All three tier-1 templates end-to-end (platformer_2d, walker_3d, topdown_2d).
- Fallback asset tier catches external API outages — a full Tripo outage still produces a 3D game (embedded Kenney humanoid), not a silent downgrade to 2D.
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

## Non-goals (v1)

Generated music, multi-turn editing UI, auth / multi-tenant, persistence beyond local disk, mobile controls.
