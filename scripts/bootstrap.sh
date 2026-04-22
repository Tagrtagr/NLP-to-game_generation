#!/usr/bin/env bash
# Bootstrap script: installs Godot 4.5.1 headless + web export templates,
# frontend node deps + Playwright chromium, backend uv deps.
#
# Idempotent — safe to run multiple times.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$ROOT_DIR/bin"
mkdir -p "$BIN_DIR"

GODOT_VERSION="4.5.1-stable"
GODOT_VER_SHORT="4.5.1.stable"

os="$(uname -s)"
arch="$(uname -m)"

case "$os" in
  Darwin)
    GODOT_ZIP="Godot_v${GODOT_VERSION}_macos.universal.zip"
    TEMPLATES_DIR="$HOME/Library/Application Support/Godot/export_templates/${GODOT_VER_SHORT}"
    ;;
  Linux)
    if [ "$arch" = "x86_64" ]; then
      GODOT_ZIP="Godot_v${GODOT_VERSION}_linux.x86_64.zip"
    else
      GODOT_ZIP="Godot_v${GODOT_VERSION}_linux.arm64.zip"
    fi
    TEMPLATES_DIR="$HOME/.local/share/godot/export_templates/${GODOT_VER_SHORT}"
    ;;
  *)
    echo "Unsupported OS: $os" >&2
    exit 1
    ;;
esac

GODOT_URL="https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/${GODOT_ZIP}"
TPL_ZIP="Godot_v${GODOT_VERSION}_export_templates.tpz"
TPL_URL="https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/${TPL_ZIP}"

# --- Godot binary ---
if [ ! -x "$BIN_DIR/godot" ]; then
  echo "[bootstrap] Downloading Godot ${GODOT_VERSION}..."
  tmp="$(mktemp -d)"
  curl -L --fail -o "$tmp/$GODOT_ZIP" "$GODOT_URL"
  (cd "$tmp" && unzip -q "$GODOT_ZIP")
  if [ "$os" = "Darwin" ]; then
    # Mac universal ships as an .app bundle
    app_path="$(find "$tmp" -maxdepth 2 -name 'Godot*.app' | head -n1)"
    ln -sf "$app_path/Contents/MacOS/Godot" "$BIN_DIR/godot"
  else
    bin_path="$(find "$tmp" -maxdepth 2 -type f -name 'Godot*' | head -n1)"
    mv "$bin_path" "$BIN_DIR/godot"
    chmod +x "$BIN_DIR/godot"
  fi
  echo "[bootstrap] Godot installed at $BIN_DIR/godot"
else
  echo "[bootstrap] Godot already present."
fi

# --- Export templates ---
if [ ! -d "$TEMPLATES_DIR" ] || [ -z "$(ls -A "$TEMPLATES_DIR" 2>/dev/null || true)" ]; then
  echo "[bootstrap] Downloading export templates..."
  mkdir -p "$TEMPLATES_DIR"
  tmp="$(mktemp -d)"
  curl -L --fail -o "$tmp/$TPL_ZIP" "$TPL_URL"
  (cd "$tmp" && unzip -q "$TPL_ZIP")
  # Archive extracts to a 'templates/' folder
  cp -R "$tmp/templates/"* "$TEMPLATES_DIR/"
  echo "[bootstrap] Export templates installed at $TEMPLATES_DIR"
else
  echo "[bootstrap] Export templates already present."
fi

# --- Frontend deps + Playwright chromium ---
if [ -d "$ROOT_DIR/frontend" ]; then
  echo "[bootstrap] Installing frontend deps..."
  (cd "$ROOT_DIR/frontend" && npm install)
fi

# --- Backend deps ---
if command -v uv >/dev/null 2>&1; then
  echo "[bootstrap] Installing backend deps via uv..."
  (cd "$ROOT_DIR/backend" && uv sync)
  echo "[bootstrap] Installing Playwright chromium..."
  (cd "$ROOT_DIR/backend" && uv run playwright install chromium)
else
  echo "[bootstrap] WARNING: uv not found. Install from https://docs.astral.sh/uv/ then re-run." >&2
fi

echo "[bootstrap] Verifying Godot..."
"$BIN_DIR/godot" --version || true

echo "[bootstrap] Done."
