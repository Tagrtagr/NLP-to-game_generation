# SFX

CC0 sound effects from Kenney's [Interface Sounds](https://kenney.nl/assets/interface-sounds), [Impact Sounds](https://kenney.nl/assets/impact-sounds), and [RPG Audio](https://kenney.nl/assets/rpg-audio) packs. Fetched by `scripts/bootstrap.sh` — WAV binaries are gitignored; only `sfx_manifest.json` is committed.

The manifest is injected verbatim into both the **design** system prompt (so `GameDesign.sfx_map` entries map to real semantic keys) and the **synthesize** system prompt (so generated `.gd` scripts reference real filenames). No LLM filename guessing anywhere in the pipeline.

Keys are the stable interface. If a downloaded WAV has a different filename than the manifest expects, rename it rather than editing the manifest (keeps the prompt template stable across machines).
