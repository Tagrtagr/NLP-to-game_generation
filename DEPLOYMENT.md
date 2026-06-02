# Hosted Deployment

This repo is split into two deployable pieces:

- `frontend/`: Vite React app. Deploy this to Vercel.
- `backend/`: FastAPI + Godot + Playwright generation worker. Deploy this as a Docker service on DigitalOcean or another container host.

Do not deploy the current backend as a Vercel Function. Generation jobs run Godot exports, write workspaces, launch Playwright, and can take 10-15 minutes. Keep that work in a long-running container.

## MVP Architecture

```text
Browser
  -> Vercel static frontend
  -> HTTPS FastAPI backend on DigitalOcean
  -> provider APIs: Anthropic/OpenAI/Gemini/Tripo/PixelLab
  -> backend container local workspaces during generation
  -> optional Postgres metadata + DigitalOcean Spaces durable saved games
```

For local development, generated games are served from the backend at `/workspaces/<session>/web/index.html` and saved metadata is written to `backend/saved_games/index.json`.

For public durable saves, set `DATABASE_URL` and DigitalOcean Spaces/S3 variables. The save endpoint uploads the generated `web/` folder to object storage and stores the playable URL plus metadata in Postgres.

## Backend: DigitalOcean App Platform or Droplet

Build from the backend directory with:

```bash
docker build -t godot-agent-backend ./backend
docker run --env-file backend/.env -e PORT=8000 -p 8000:8000 godot-agent-backend
```

For local Docker Compose:

```bash
docker compose -f docker-compose.backend.yml up --build
```

App Platform expects the backend to bind on `0.0.0.0:$PORT`. The Dockerfile already does that and defaults to `8080`.

Required backend environment variables for the hosted app:

```bash
CORS_ALLOW_ORIGINS=https://your-vercel-project.vercel.app
QA_BASE_URL=https://your-backend.example.com
```

`CORS_ALLOW_ORIGINS` must include the Vercel frontend URL. `QA_BASE_URL` must be the public backend URL so Playwright QA can load generated games over HTTP.

For the core LLM pipeline, use either OpenRouter or direct provider keys.

OpenRouter option:

```bash
OPENROUTER_API_KEY=
OPENROUTER_TEXT_MODEL=anthropic/claude-sonnet-4.5
OPENROUTER_CRITIC_MODEL=google/gemini-2.5-flash
OPENROUTER_VISION_MODEL=google/gemini-2.5-flash
OPENROUTER_APP_URL=https://your-vercel-project.vercel.app
OPENROUTER_APP_NAME=Godot Agent
```

Direct provider option:

```bash
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
```

Asset-provider keys are optional for the MVP, but missing keys mean those providers will fall back or fail per the asset resolver:

```bash
OPENAI_API_KEY=
TRIPO_API_KEY=
PIXELLAB_API_KEY=
ASSET_GENERATION_RETRIES=1
ASSET_TIMEOUT_SPRITE=90
ASSET_TIMEOUT_TILESET=90
ASSET_TIMEOUT_BG=120
ASSET_TIMEOUT_UI=120
ASSET_TIMEOUT_MESH=240
PIXELLAB_CONCURRENCY=1
GPT_IMAGE_CONCURRENCY=2
TRIPO_CONCURRENCY=1
ALLOW_PLACEHOLDER_FALLBACKS=false
```

For public demos, keep `ALLOW_PLACEHOLDER_FALLBACKS=false`. That makes asset
provider timeouts fail the run instead of shipping blocky procedural placeholder
art when the bundled fallback packs are not present in the container.

Durable saved-game storage:

```bash
DATABASE_URL=postgresql://user:password@host:25060/db?sslmode=require
SPACES_BUCKET=your-space
SPACES_REGION=nyc3
SPACES_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com
SPACES_ACCESS_KEY=
SPACES_SECRET_KEY=
SPACES_PUBLIC_BASE_URL=https://your-space.nyc3.cdn.digitaloceanspaces.com
```

`SAVE_DATABASE_URL` can be used instead of `DATABASE_URL` if the app already needs a separate database URL for another feature. `SPACES_PUBLIC_BASE_URL` is optional but recommended when serving games through the Spaces CDN or a custom domain. Without these variables, the backend keeps the local JSON/workspace fallback for development.

## Frontend: Vercel

Set the Vercel project root to `frontend/`.

Build settings:

```text
Framework: Vite
Build command: npm run build
Output directory: dist
```

Required frontend environment variable:

```bash
VITE_API_BASE_URL=https://your-backend.example.com
```

This value is used for:

- `POST /api/generate`
- `POST /api/cancel/:id`
- generated game iframes at `/workspaces/...`

## What You Need To Provide

To actually deploy this, I need:

- Vercel project access or a Vercel token/project link.
- DigitalOcean access or a target container host URL.
- Backend API keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `TRIPO_API_KEY`, `PIXELLAB_API_KEY`.
- The final public frontend URL so backend `CORS_ALLOW_ORIGINS` can be set.
- The final public backend URL so frontend `VITE_API_BASE_URL` and backend `QA_BASE_URL` can be set.

## Next Upgrade

Generated saved-game bundles are durable when Postgres and Spaces are configured. Remaining production hardening:

- store full job metadata and event history in Postgres
- upload QA screenshots and build logs to object storage
- add authentication and per-user saved-game ownership
