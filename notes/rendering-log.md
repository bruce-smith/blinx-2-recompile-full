# Blinx 2 rendering log (NV2A pushbuffer executor, path (a))

Running log of the `RECOMP_PB_EXEC` work. The plan is in
`rendering-options.md`, and earlier boot history is in `audio-spin-fix.md`.
Newest entries go at the bottom.

## How to run a rendering session

`blinx2-recomp\build\Release\run_p4.ps1 -Secs <n> -Tag <name> [-Gpu]` (untracked,
in the build dir) sets:

- `RECOMP_PB_EXEC=1`
- `RECOMP_FB_DUMP=fb_`
- `RECOMP_USB=1`
- `RECOMP_PAD_SCRIPT=@pad_script.txt`
- `RECOMP_PAD_LIVE=pad_live.txt`
- `RECOMP_FB_DUMP_FLIPS=dumpflips.flag`
- `RECOMP_FRAME_TRACE=ftrace.flag`
- `RECOMP_SAMPLE_MS=5`, plus `RECOMP_SAMPLE_GPU=1` with `-Gpu`

Logs go to `<tag>.err` / `<tag>.out`. Controls while the game runs:

- `touch dumpflips.flag` for a few seconds dumps every flip.
- `touch ftrace.flag` traces one whole frame (`[FTRACE]`): every batch with
  its surface, textures, combiner stages, blend, depth state and pixel count.
- Append `start:500` or `a:600` to `pad_live.txt` to press buttons.

With a save present the title flow goes straight to the hub `mgtu_ts` (about
1 min). The CHALLENGE "GAME PAUSED" screen needs **Start**, not A.

## 2026-10-11: the textured-batch counter was wrong

`[GPU] batches: 0 textured` over frames full of textures. `raster_batch()`
sends vertex-program batches to `raster_batch_program()` and returns before
the accounting, and in a 3D scene that is nearly every batch. These batches
are now counted separately (xboxrecomp `41a8c2d`):
`[GPU] vertex-program batches: 430857 with a texture on some stage, 0 with none`.

## 2026-10-11: back-face culling

`0x0308` CULL_FACE_ENABLE and `0x039C` CULL_FACE topped the unhandled ranking
at about 300k each, and `0x03A0` FRONT_FACE was unhandled too. They are now
implemented on the screen-space signed area: y down, so CW means area > 0,
and FRONT_FACE `0x900` is CW. Odd triangles in a strip are re-ordered so the
whole strip shares one winding (xboxrecomp `cda813f`). Hub: 745k of about 5M
triangles culled, and the image is unchanged. `RECOMP_NO_CULL=1` turns it
off for A/B tests. Frame rate did not change measurably (fill-bound, see
below).

## 2026-10-11: hub floor artifact = swizzled render targets

`checkpoint_png/hub_floor_artifact.png` shows the floor as stair-stepped teal
bands. A frame trace of the hub shows:

```
color offset -> 04630000 ; clear surf 04630000 512x512   (mirrored scene drawn here)
color offset -> 04430000 ; clear surf 04430000 512x512
PRG surf 03144000 640x480 | rc prog 00021 | t0 84630000 512x512 fmt 06 | t1 84430000 512x512 fmt 06
```

The floor samples two 512x512 A8R8G8B8 **swizzled** textures (fmt 0x06),
each with the PROJECT2D stage program, which are the game's own render
targets. `SET_SURFACE_FORMAT` type 2 (swizzled, log2 size in bits 16-31) was
ignored, so the executor wrote them linearly with pitch 2048, and the sampler
then read them as swizzled. `put_pixel` and `clear_surface` now go through
per-format swizzle offset tables, using the same masks as the sampler
(xboxrecomp `54869bf`). The floor now mirrors the walls:
`checkpoint_png/hub_floor_reflection_fixed.png` and
`hub_tutorial_swizzled_rt.png`.

## 2026-10-11: where PB_EXEC time goes (hub, 640x480, 32-thread host)

The hub runs at **3.5–4.7 fps** with PB_EXEC (title and attract: about 30
fps).

Main thread (`RECOMP_SAMPLE_MS=5`, hub): **92% self in `sub_002E7F30`**,
D3D's wait for pushbuffer space. The game's own frame work is a few percent.
The executor thread is the whole frame rate.

NV2A worker thread (`RECOMP_SAMPLE_GPU=1`, ~15.7k samples, before the
stall-free window ended):

| inclusive | |
|---|---|
| 86% | `pb_walk` → `nv2a_pb_exec_method` |
| 78% | `raster_batch_program` → `xfq_flush` |
| 70% | `xf_rows` (pixel loop, executor's own share of the rows) |
| 21% | `nv2a_rc_eval` (register combiners, float) |
| 21% | `draw_inline_array` |
| 15% + 10% | `put_pixel` (float blend: `blend_factor` 6%) |
| 9% / 6% / 3% | `sample_tex` / `read_rgb` / `d3d8_dxt_decode_texel` (texel decoded per tap, 4 taps bilinear) |
| 6% | `nv2a_vsh_run` (vertex programs) |
| 13% | idle (sleep + waiting for raster workers) |
| 5% | `ZwWriteFile` (stderr logging) |

Frame-trace totals: about **1.6 M pixels per frame** through the
combiners. That is 5.2x overdraw of 640x480. It includes two 512x512
reflection passes, a 320x240 downsample, and three full-screen
post-processing passes of 120–280k pixels each. There are about 400 draw
calls per frame.
