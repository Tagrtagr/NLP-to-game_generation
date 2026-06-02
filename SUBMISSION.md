# CS 153 Final Submission Notes

## Project

**Title:** Godot Agent

**Track:** Application / Product and Automation / Agent Systems

**One-line description:** A browser app that turns a natural-language prompt into a playable Godot web game, showing live generation progress and saving playable builds.

## Rubric Map

### Problem & Insight

Game prototyping has a high activation cost: a designer has to choose an engine, create assets, write scripts, export a build, and debug browser/runtime issues before an idea becomes playable. This project tests whether one person using AI tools can compress that loop into minutes while preserving enough structure that the result is actually playable.

### Execution & Technical Work

- FastAPI backend with a five-stage agent pipeline: design, assets, synthesize, build, QA.
- React/Vite frontend with streamed SSE progress, phase cards, thumbnails, cancel, saved games, and iframe preview.
- Godot 4.5.1 template-guided synthesis and single-threaded web export.
- Runtime integrations with LLMs and asset providers.
- Local saved-game fallback plus Postgres metadata and Spaces/S3 object-storage support for durable public saves.
- Regression tests for build detection, asset handling, synthesize sanity checks, and saved-game storage.

### Evaluation & Evidence

- Backend regression tests: `cd backend && uv run pytest tests/test_regressions.py`
- Backend lint for changed paths: `cd backend && uv run ruff check app.py agent/saved_games.py tests/test_regressions.py`
- Frontend production build: `cd frontend && npm run build`
- Local smoke test: save/list/load/delete a fake generated web build through the UI.
- Qualitative demo prompts:
  - "a cozy 2D platformer where a cat collects yarn balls in a moonlit bakery"
  - "a top-down 2D arcade game where a gardener dodges slimes and gathers seeds"
  - "a 3D third-person explorer where a robot crosses floating islands to reach a beacon"
  - "make something fun"

### Communication & Presentation

The README explains the problem, stack, local setup, architecture, repair budget, evaluation evidence, limitations, and AI usage. `DEPLOYMENT.md` explains Vercel frontend deployment, DigitalOcean backend deployment, and durable saved-game environment variables.

### Process, Integrity & Disclosure

AI usage is disclosed in `README.md`. External inspiration and asset/template sources are credited. Known limitations are listed explicitly, including provider flakiness, limited template coverage, fallback asset quality, and lack of user accounts.

## Demo Video Outline

Keep under 3 minutes.

1. **Why I built it (0:00-0:25):** The bottleneck is getting from a game idea to a playable prototype.
2. **How it works (0:25-1:25):** Prompt enters the React app, backend creates a structured design, resolves assets, synthesizes Godot files, exports a web build, and runs visual QA.
3. **Live product demo (1:25-2:15):** Show the UI, saved-game list, a generated game in the iframe, and the save/reopen flow.
4. **Use cases and impact (2:15-2:40):** Rapid prototyping, game jams, education, and creative tooling for non-engineers.
5. **What I would add next (2:40-3:00):** More templates, multi-turn edits, user accounts, richer telemetry, and better 3D assets.

## Deployment Checklist

- Frontend Vercel project root: `frontend/`
- Frontend env: `VITE_API_BASE_URL=https://your-backend-url`
- Backend host: DigitalOcean App Platform/Droplet or another long-running container host
- Backend env:
  - `CORS_ALLOW_ORIGINS=https://your-vercel-url`
  - `QA_BASE_URL=https://your-backend-url`
  - provider API keys
  - optional durable saves: `DATABASE_URL`, `SPACES_BUCKET`, `SPACES_REGION`, `SPACES_ENDPOINT_URL`, `SPACES_ACCESS_KEY`, `SPACES_SECRET_KEY`, `SPACES_PUBLIC_BASE_URL`

## Final Submission Links

Fill these in before submitting:

- GitHub repo:
- Vercel frontend:
- Backend health URL:
- Demo video:
