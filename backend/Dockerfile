FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ARG GODOT_VERSION=4.5.1-stable
ARG GODOT_VER_SHORT=4.5.1.stable
ARG TARGETARCH

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    GODOT_BIN=/opt/godot/godot \
    PATH="/app/backend/.venv/bin:${PATH}"

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip libfontconfig1 libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

RUN uv run playwright install --with-deps chromium

RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) godot_arch="x86_64" ;; \
      arm64) godot_arch="arm64" ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    mkdir -p /opt/godot /root/.local/share/godot/export_templates/${GODOT_VER_SHORT}; \
    curl -L --fail -o /tmp/godot.zip \
      "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/Godot_v${GODOT_VERSION}_linux.${godot_arch}.zip"; \
    unzip -q /tmp/godot.zip -d /tmp/godot; \
    find /tmp/godot -maxdepth 1 -type f -name 'Godot*' -exec mv {} /opt/godot/godot \; ; \
    chmod +x /opt/godot/godot; \
    curl -L --fail -o /tmp/templates.tpz \
      "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/Godot_v${GODOT_VERSION}_export_templates.tpz"; \
    unzip -q /tmp/templates.tpz -d /tmp/godot_templates; \
    cp -R /tmp/godot_templates/templates/* /root/.local/share/godot/export_templates/${GODOT_VER_SHORT}/; \
    rm -rf /tmp/godot /tmp/godot.zip /tmp/templates.tpz /tmp/godot_templates

COPY backend ./

RUN mkdir -p /app/backend/workspaces

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
