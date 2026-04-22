# Battle-tested GDShader snippets (Godot 4.5.1)

Each snippet is a drop-in starting point. Tune uniforms from the `GameDesign.palette`.

## How to wire a shader (read this first)

Skipping these steps is the single most common synthesize failure.

- **canvas_item post-process (crt / dither / palette_lock / chromatic / grain)**: add a
  full-screen `ColorRect` as a child of a `CanvasLayer` (so it renders above the
  game), `anchor_right=1.0 anchor_bottom=1.0`, set `material` to a new
  `ShaderMaterial` pointing at a `.gdshader` resource. Post-process shaders read
  `SCREEN_TEXTURE` — requires a CanvasLayer `layer=1` or greater.
- **canvas_item sprite material (outline / water)**: assign the `ShaderMaterial`
  directly to the `Sprite2D.material` (or `TileMap.material` for a whole layer).
  Sprite shaders read `TEXTURE`, not `SCREEN_TEXTURE`.
- **sky (3D)**: assign the `ShaderMaterial` to `WorldEnvironment.environment.sky.sky_material`.
  Do NOT put `shader_type sky` on anything else.
- Writing a `ShaderMaterial` resource inline in a `.tscn` works — `shader =
  SubResource("ShaderRes")` where the SubResource is `type="Shader"` with
  `code = "..."`. Keep the shader body in an unquoted triple-quoted string
  inside the tscn's SubResource.
- Palette uniforms: pass `GameDesign.palette` hex values as `Color` directly from
  GDScript at `_ready` (`$PostFX.material.set_shader_parameter("palette", [...])`)
  — cleaner than baking colors into the shader source.

## crt (canvas_item, post-process)

```gdshader
shader_type canvas_item;
uniform float curvature : hint_range(0.0, 0.1) = 0.04;
uniform float scanline_strength : hint_range(0.0, 1.0) = 0.25;
uniform float vignette : hint_range(0.0, 1.0) = 0.35;

void fragment() {
    vec2 uv = SCREEN_UV * 2.0 - 1.0;
    uv += uv * (uv.yx * uv.yx) * curvature;
    uv = uv * 0.5 + 0.5;
    vec4 col = texture(SCREEN_TEXTURE, uv);
    float scan = sin(uv.y * 800.0) * 0.5 + 0.5;
    col.rgb *= mix(1.0, scan, scanline_strength);
    float v = 1.0 - length(SCREEN_UV * 2.0 - 1.0) * vignette;
    COLOR = vec4(col.rgb * v, 1.0);
}
```

## outline (canvas_item, sprite material)

```gdshader
shader_type canvas_item;
uniform vec4 outline_color : source_color = vec4(0,0,0,1);
uniform float width : hint_range(0.0, 4.0) = 1.0;

void fragment() {
    vec4 c = texture(TEXTURE, UV);
    vec2 px = TEXTURE_PIXEL_SIZE * width;
    float a = 0.0;
    a = max(a, texture(TEXTURE, UV + vec2( px.x, 0)).a);
    a = max(a, texture(TEXTURE, UV + vec2(-px.x, 0)).a);
    a = max(a, texture(TEXTURE, UV + vec2(0,  px.y)).a);
    a = max(a, texture(TEXTURE, UV + vec2(0, -px.y)).a);
    COLOR = mix(vec4(outline_color.rgb, a * outline_color.a), c, c.a);
}
```

## water (canvas_item)

```gdshader
shader_type canvas_item;
uniform float time_scale : hint_range(0.0, 2.0) = 0.5;
uniform float amp : hint_range(0.0, 0.05) = 0.01;

void fragment() {
    vec2 uv = UV;
    uv.x += sin(uv.y * 20.0 + TIME * time_scale) * amp;
    COLOR = texture(TEXTURE, uv);
}
```

## dither (canvas_item, post-process — limited palette snap)

```gdshader
shader_type canvas_item;
uniform vec3 palette[4] : source_color;
uniform float threshold : hint_range(0.0, 1.0) = 0.08;

const mat4 bayer = mat4(
    vec4( 0, 8, 2,10),
    vec4(12, 4,14, 6),
    vec4( 3,11, 1, 9),
    vec4(15, 7,13, 5)) / 16.0;

vec3 snap(vec3 c) {
    float best = 1e9;
    vec3 out_c = palette[0];
    for (int i = 0; i < 4; i++) {
        float d = distance(c, palette[i]);
        if (d < best) { best = d; out_c = palette[i]; }
    }
    return out_c;
}

void fragment() {
    vec4 c = texture(SCREEN_TEXTURE, SCREEN_UV);
    ivec2 p = ivec2(mod(FRAGCOORD.xy, 4.0));
    float b = bayer[p.y][p.x];
    c.rgb = snap(c.rgb + (b - 0.5) * threshold);
    COLOR = c;
}
```

## sky gradient (spatial, 3D)

```gdshader
shader_type sky;
uniform vec3 top_color : source_color = vec3(0.35, 0.55, 0.85);
uniform vec3 bottom_color : source_color = vec3(0.85, 0.75, 0.65);
uniform float softness : hint_range(0.0, 1.0) = 0.5;

void sky() {
    float t = smoothstep(-softness, softness, EYEDIR.y);
    COLOR = mix(bottom_color, top_color, t);
}
```

## chromatic aberration (canvas_item post-process — split RGB at screen edges)

Cheap cinematic juice, especially good under CRT or on hit/damage flashes.
Drive `amount` via Tween from a signal handler for impact moments.

```gdshader
shader_type canvas_item;
uniform float amount : hint_range(0.0, 0.02) = 0.003;

void fragment() {
    vec2 dir = SCREEN_UV - vec2(0.5);
    float r = texture(SCREEN_TEXTURE, SCREEN_UV - dir * amount).r;
    float g = texture(SCREEN_TEXTURE, SCREEN_UV).g;
    float b = texture(SCREEN_TEXTURE, SCREEN_UV + dir * amount).b;
    COLOR = vec4(r, g, b, 1.0);
}
```

## film grain (canvas_item post-process — TIME-animated noise overlay)

Warms up flat palettes without touching art.

```gdshader
shader_type canvas_item;
uniform float strength : hint_range(0.0, 0.5) = 0.08;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void fragment() {
    vec3 c = texture(SCREEN_TEXTURE, SCREEN_UV).rgb;
    float n = hash(FRAGCOORD.xy + vec2(TIME * 13.37));
    c += (n - 0.5) * strength;
    COLOR = vec4(c, 1.0);
}
```

## palette_lock (canvas_item post-process — hard color snap, no dither)

```gdshader
shader_type canvas_item;
uniform vec3 palette[6] : source_color;
uniform int palette_size : hint_range(1, 6) = 6;

void fragment() {
    vec3 c = texture(SCREEN_TEXTURE, SCREEN_UV).rgb;
    float best = 1e9;
    vec3 pick = palette[0];
    for (int i = 0; i < palette_size; i++) {
        float d = distance(c, palette[i]);
        if (d < best) { best = d; pick = palette[i]; }
    }
    COLOR = vec4(pick, 1.0);
}
```
