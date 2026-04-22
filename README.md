# Godot Agent

Turn a single natural-language prompt into a playable Godot 4.5.1 game, streamed live into your browser. Left column: chat with per-phase progress. Right column: iframe running the freshly-built game.

> Status: scaffold only. Pipeline phases land over the next commits.

## Research lineage

This agent is a direct implementation of a recognizable research pattern. Credited explicitly because the architecture choices come from these papers, not from scratch:

- **LayoutVLM** (Sun et al., CVPR 2025) — separating semantic planning from code synthesis, with structured output in a DSL consumed by a deterministic engine. Maps to our `design → synthesize` split: Claude produces a strict `GameDesign` DSL; a deterministic applier turns it into Godot scenes/scripts.
- **Voyager** (Wang et al., NVIDIA) — execution-feedback loops that repair code against the real runtime. Maps to our build + visual-QA repair loops, governed by a global budget.
- **Holodeck** (Yang et al., CVPR 2024) — LLM-driven scene composition combining asset retrieval with classical rendering beats pure generative approaches. Maps to our template-guided synthesis + bundled-fallback asset tier: generated-first, retrieved-when-generation-fails, always-plays-via-Godot.

Prior art we learned from and explicitly compete against: [htdt/godogen](https://github.com/htdt/godogen) — same idea, CLI-only, hours per run. We target 2–3 min common-case, up to 5 min worst-case, streaming the whole way.

## Stack

- **Backend:** Python 3.11, FastAPI, `uv`, SSE streaming, Playwright (chromium).
- **Frontend:** Vite + React + TypeScript + Tailwind.
- **Engine:** Godot 4.5.1 headless, single-threaded web export (no SharedArrayBuffer / COOP+COEP needed).
- **LLMs:** Anthropic Claude Opus 4.7 (design + code), Google Gemini 3 Flash (critic + visual QA).
- **Assets:** PixelLab (2D pixel) · `gpt-image-1` (2D backgrounds/UI) · Tripo v2.5 (3D meshes). All with bundled Kenney CC0 fallbacks.

## Run locally

```bash
./scripts/bootstrap.sh                       # Godot + templates + node + uv + Playwright
cp backend/.env.example backend/.env         # fill in API keys
cd backend && uv run uvicorn app:app --reload   # localhost:8000
cd frontend && npm run dev                   # localhost:5173
```

## Architecture

Five phases, each emitting SSE events consumed by the frontend:

1. **Design** (~25–40s) — best-of-3 Opus 4.7 samples + Gemini critic; produces `GameDesign` (pydantic).
2. **Assets** (~30–90s) — parallel PixelLab/gpt-image-1/Tripo with per-service circuit breakers and bundled fallbacks.
3. **Synthesize** (~30–60s) — Opus 4.7 emits a strict JSON edit plan over a forked template; deterministic applier writes files.
4. **Build** (~15–30s) — `godot --headless --export-release "Web"` with single-threaded preset.
5. **Visual QA** (~15–25s) — Playwright polls `window.__GODOT_READY__`; Gemini Flash reviews screenshots; repairs governed by global budget (cap = 3).

## Honest limitations

To be filled in once the pipeline is real. Target shape: what works reliably, what's flaky (Tripo on abstract prompts, shader desaturation, sprite animation seams), what fails (genre gaps outside the template library, very long prompts, headless WebGL on GPU-less CI).
