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

# --- Kenney fallback assets (manual step) ---
# Kenney's CDN paths are not stable across site redeploys, so we don't script
# the download here. Instead, we create the directory skeleton and print the
# list of packs to fetch manually. The step-6 fallback loader tolerates
# missing files — it probes by kind (*.png / *.glb / *.wav) and falls back
# to engine primitives (ColorRect, BoxMesh, silent AudioStream) if nothing
# matches. So the pipeline runs even without this step; it just looks plainer.
ASSETS_DIR="$ROOT_DIR/backend/fallback_assets"
SFX_WAV_DIR="$ROOT_DIR/backend/sfx/wav"
mkdir -p "$ASSETS_DIR/sprites_2d/kenney_platformer" \
         "$ASSETS_DIR/sprites_2d/kenney_topdown" \
         "$ASSETS_DIR/tiles_2d/kenney_platformer" \
         "$ASSETS_DIR/ui_2d/kenney_ui" \
         "$ASSETS_DIR/ui_2d/kenney_backgrounds" \
         "$ASSETS_DIR/meshes_3d/kenney_mini_chars" \
         "$ASSETS_DIR/meshes_3d/kenney_nature" \
         "$ASSETS_DIR/meshes_3d/kenney_proto" \
         "$SFX_WAV_DIR"

if [ ! -f "$ASSETS_DIR/.populated" ]; then
  cat <<'EOF'

[bootstrap] Fallback asset packs: manual download required.
  Download these CC0 packs from https://kenney.nl/assets, unzip, and drop the
  raw files (no nested folders) into the matching directory below:

    backend/fallback_assets/sprites_2d/kenney_platformer/   (Platformer Art Deluxe)
    backend/fallback_assets/sprites_2d/kenney_topdown/      (Topdown Tanks / Topdown Shooter)
    backend/fallback_assets/ui_2d/kenney_ui/                (UI Pack)
    backend/fallback_assets/ui_2d/kenney_backgrounds/       (Background Elements)
    backend/fallback_assets/meshes_3d/kenney_mini_chars/    (Mini Characters 1)
    backend/fallback_assets/meshes_3d/kenney_nature/        (Nature Kit)
    backend/fallback_assets/meshes_3d/kenney_proto/         (Prototype Textures / Platformer Kit)
    backend/sfx/wav/                                        (Interface Sounds + Impact Sounds + RPG Audio)

  After dropping files in: touch backend/fallback_assets/.populated
  (The pipeline still runs without this — fallback loader degrades to engine
  primitives. But the output looks much better with real Kenney assets.)

EOF
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
