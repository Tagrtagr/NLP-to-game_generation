# Fallback assets

CC0 asset packs from [Kenney](https://kenney.nl/), fetched at bootstrap time. The binary content is **gitignored**; only `manifest.json` is committed.

Why a fallback tier exists: every external asset service (PixelLab, `gpt-image-1`, Tripo) can be slow, rate-limited, or produce garbage. The asset phase wraps every generation in a fallback-guarded resolver — on timeout / API error / garbage detection, it falls back to a deterministic file from here. This is what lets the agent guarantee a playable game even under external-service failure.

## How it's used

1. **Design phase** reads `manifest.json` and injects it verbatim into the system prompt. The LLM picks a `fallback_role` for every `Asset` in `GameDesign` — a Pydantic validator rejects any role that isn't a key in this file.
2. **Asset phase** calls the real generation API; on failure, `load_fallback(role)` resolves the role → file path → copies into the workspace as the asset's final location. Caller code never knows whether a given asset was generated or fallback (the SSE event does, so the frontend can tag it).
3. **Synthesize phase** sees the resolved asset manifest with real filenames on disk — no conditional logic needed in the generated Godot scripts.

## Directory layout (populated by bootstrap)

```
fallback_assets/
  manifest.json           # committed, source of truth
  sprites_2d/
    kenney_topdown/...    # Kenney's Top-Down Tanks / RPG Characters
    kenney_platformer/... # Kenney's Platformer Art Deluxe / Jumper Pack
  tiles_2d/
    kenney_platformer/... # same packs, tileset subset
  ui_2d/
    kenney_ui/...         # Kenney's UI Pack
    kenney_backgrounds/...
  meshes_3d/
    kenney_mini_chars/... # Kenney's Mini Characters 1
    kenney_nature/...     # Kenney's Nature Kit
    kenney_proto/...      # Kenney's Prototype Textures / Platformer Kit
```

## Adding / replacing assets

If a Kenney pack's filenames don't match `manifest.json`, either:
- rename the files after download (preferred), or
- edit `manifest.json` to point at the real filenames.

The `_doc` field and per-role `desc` fields are read by the LLM as context — keep them honest and descriptive.

## Licensing

All bundled content is CC0 (public domain) from Kenney.nl. Credit in the final app's README is optional but courteous.
