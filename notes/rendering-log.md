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

## 2026-10-11: PB_EXEC speed, software vs D3D11: measurements and recommendation

Same build and pad script; hub steady state from the `[GPU] fps` lines:

| run | hub fps | note |
|---|---|---|
| baseline (16 raster threads) | 3.6–6.1, typically ~4.5 | main 85% in `sub_002E7F30` (pushbuffer wait) |
| `RECOMP_NO_COMBINERS=1` | 5.8 | cheap shading; main still 91% waiting |
| `RECOMP_RASTER_THREADS=1` | 0.8–2.2 | |

Reading the numbers:

- **Shading is not the main cost.** Removing the combiner evaluation only
  takes the hub from ~4.5 to 5.8 fps.
- **The structure is the cost.** The executor thread is ~70% inside its own
  `xf_rows`. A draw is spread over the pool only above 2048 px
  (`NV_XFQ_PX_PER_THREAD`), and a hub frame is ~400 draw calls, most of them
  small, so most pixels are shaded serially on the executor thread with the
  other 15 threads idle. Each parallel draw then pays a wake/wait round trip.
- The non-pixel executor work is `pb_walk`, the vertex programs (`nv2a_vsh_run`
  ~6%), setup and stderr. It is about 17% of the thread, i.e. roughly 40 ms
  of a ~230 ms frame.
- Pixel work is about 1.6 M combiner pixels per frame, ~160 ms single-threaded
  at the current per-pixel cost. Spread over 15 threads that is about 11 ms.

What the existing D3D11 code really is: `src/nv2a/nv2a_pgraph_d3d11.c` is a
650-line translator for 2D menus (inline-array quads, a hard-coded font atlas,
several wrong method numbers). It is not a backend. A real one would reuse
`src/d3d`'s microcode→HLSL (`d3d8_vsh.c`), combiners→HLSL
(`d3d8_combiners.c`) and the swizzle/DXT code. It would still need new
pieces:

- render targets that alias guest memory, both directions: Blinx samples its
  own swizzled RTs and downsampled copies every frame;
- vertex and index buffers streamed from guest memory on every draw;
- surface/zeta management;
- CPU readback for flips and the FB window;
- moving the device to the executor thread.

That is weeks of work before it matches today's image.

**Recommendation: keep the software rasteriser and make it frame-parallel.**
Defer rasterisation across draw calls: snapshot per-draw state (combiners,
4 texture stages, blend, depth, alpha, fog, colour mask, surface/zeta) into a
state table, bin set-up triangles, and let all threads own interleaved rows
across the whole batch. Flush on:

- surface/zeta change, clear, flip, or the queue filling;
- a texture stage that names a surface written in the current batch (render
  to texture).

Expected: the executor drops to its non-pixel ~40 ms, so roughly 15–25 fps,
with pixel work overlapped. After that, the next steps are the
vertex-program interpreter (`nv2a_vsh_run`), a per-texture decode cache in
place of the per-tap DXT decode, and integer blending. A D3D11 backend stays
the long-term route to 60 fps, mipmaps and filtering fidelity. Revisit it once
software rendering stops being the blocker for gameplay work.

## 2026-10-11: frame-parallel software rasteriser: hub ~4.5 → ~12 fps

xboxrecomp `0ec5a2f`..`554bea6`. Steps and hub fps (same pad script, 16
raster threads, 32-thread host):

| step | hub fps | commit |
|---|---|---|
| per-draw rasterisation (start) | ~4.5 | |
| NOP/WAIT_FOR_IDLE/BREAK_VB_CACHE no longer ranked | – | `0ec5a2f` |
| no `fflush(stderr)` per pushbuffer kick (was 7% of the executor) | – | `ee9cc4f` |
| deferred batches + PixState snapshots, shared stats | 6.4–7.5 | (part of `c40d37a`) |
| + prepared combiners, per-size swizzle tables | 7.6–8.6 | `554bea6` |
| + per-thread pixel stats (contended `s_gpu.pixels` per pixel) | **~12** (title ~60) | `c40d37a` |

Findings along the way:

- **The executor now waits on the workers** (`rq_wait` ~56%), so per-pixel
  cost and worker scaling decide the frame rate. The single-thread pixel
  profile (`RECOMP_RASTER_THREADS=1`, before the combiner change):
  - `nv2a_rc_eval` ~30% self (`read_rgb` 20%, `unpack_cached` 6%);
  - `sample_tex` 12%;
  - blending ~7%.
- **Draining at GET** (`nv2a_pb_exec_drain`, before the NV2A thread publishes
  GET = PUT) costs nothing measurable. Without it the waits move to flips
  and clears, at the same fps. It stays on because it keeps "GET passed"
  meaning "pixels done".
- **Stipple on the hub floor's lower left:** fine dots where the grated
  stairs reflect. It appears identically with per-draw sync
  (`RECOMP_RASTER_BATCH=0`), so it is not a deferral race. Probably the
  grate texture itself (nearest/bilinear, no mipmaps). Open, low priority.
- The r1 run stalled once at 1070 flips (title spinning on critical
  sections, PUT = GET). It did not reproduce in eight later runs. Watch for
  it.

Next for speed:

- **False sharing on swizzled render targets:** vertically adjacent pixels
  share cache lines, and rows are dealt out y mod n. Deal swizzled targets
  out in 2x2/4x4 tiles instead.
- **Integer blending** in `put_pixel`.
- **Mip selection:** it would also cut texel-cache misses on minified
  textures.
- **The vertex-program interpreter** (`nv2a_vsh_run`, ~14% of the executor)
  once the workers stop being the limit.

Screens:

- `checkpoint_png/hub_gameplay_reflection.png`: gameplay, reflection visible.
- `checkpoint_png/hub_deferred_raster_12fps.png`: the hub at ~12 fps.

## 2026-10-11 (later): double-click window; why the hub stays at ~12 fps

**Window fix** (blinx2-recomp `e496400`, xboxrecomp `5a02ba6`):
- the exe is playable on double-click: PB_EXEC, FB window, USB pad and
  keyboard default on;
- `RECOMP_HEADLESS=1` opts out;
- closing the window ends the process;
- the working directory is the exe's folder;
- `blinx2_recomp.log` when there is no console;
- a crash MessageBox.

Verified with a clean environment launched through explorer.exe:
`checkpoint_png/double_click_window.png`.

**Perf, after the frame-parallel rasteriser** (xboxrecomp `ce8e979`..`251c5b3`):

- **Workers claim 4-row bands** from a counter; the executor helps instead
  of sleeping. This is correct but fps-neutral (~12–12.7), because the
  pipeline is not throughput-bound.
- **Raster drains with work pending, by call site:** ~75% are the drain
  before GET is published, then clears, then visibility reports.
- **Main thread** (`RECOMP_SAMPLE_MS`, hub):
  - ~60% in `sub_002E7F30`, D3D's **pushbuffer kick**. It sets 0x10000 in
    NV2A 0x100410 (PFB flush) and spins until the "GPU" clears it, then
    writes PUT.
  - 15% in the fence wait `sub_002E8110`.
  - The executor meanwhile yield-spins (`Sleep(0)`) about 30% of the time.
  - So the kick handshake serialises the title and the executor: the bit is
    cleared only by the executor's loop, between segments.
- **Acking 0x100410 from a separate thread does not work.** Moving all the
  busy/interrupt/idle acks there, or only the flush bit, made the intro
  never flip (0 fps from boot, PUT = GET). The flush bit evidently has to
  stay ordered with execution. Reverted.
- The `[KERNEL] summary` `fflush(stderr)` on the game thread is gone
  (`1733753`). It was 15% of main's samples in WriteFile, mostly at boot.
- Hang hunt: `RECOMP_WATCHDOG_STALL=<n>` (`ddb6f8c`) dumps when flips stop.
  The hang has not recurred in three runs without the GPU sampler.

Next for speed: make the executor loop return to the flush ack faster. The
GET drain is where it blocks; a drain that waits only for batches older
than the current kick, or GET published per batch, would let the next kick
through while the workers finish. After that, the vertex-program
interpreter.

**Async GET** (xboxrecomp, after `251c5b3`): the NV2A thread now hands the
queue to the workers at GET-publish time instead of draining it. A/B within
one run (a flag file toggled every 40 s, same paused gameplay view): **~14.7
fps vs ~12.8 waiting**, three alternations each. Cross-run fps comparisons
are unreliable, because the pad script is time-based and faster runs reach
different, cheaper or costlier scenes. A/B inside one run.

**Hang:** the sync-mode control run rZ0 hung after ~3 min without any
sampler (fps → 0, PUT = GET). So it is a real, intermittent hang, not
caused by the GPU sampler: 3 of ~25 runs. Runs with
`RECOMP_WATCHDOG_STALL=15` have not hit it yet.

## 2026-10-11: the intermittent no-flip hang is in XPP's USB stack

Caught twice by `RECOMP_WATCHDOG_STALL=15` (rV1, rG1); it happens in ~1 run
in 8, always with `RECOMP_USB=1`. Note that USB is now on by default for
double-click.

- **Where:** the guest main thread loops forever in `sub_0036E7A5`, called
  from XInput (`sub_0036827F`, from game code 0x0021C4D4). Return addresses:
  0036E7E6 0036E897 0036E91C 0036D037 0036B107 0036840F.
- **What the loop does:** `sub_0036E7A5` pops nodes from the host
  controller's pending list `[hcd+0x41C]` (`next = [node+0x24]`) while a
  16-bit bandwidth budget at 0xF2E0E2 allows (`sub_0036E35D`), and completes
  each through `sub_0036E407`. An endless walk means the list has a cycle.
  The ICALL trace shows RtlEnter/LeaveCriticalSection (kernel slots 30/29)
  each round.
- **Suspected cause:** concurrent insertion and removal between the
  game-thread XInput path and the OHCI controller thread's ISR/DPC (the ISR
  runs on the controller thread; DPCs run inline from
  `kernel_run_dpc`/`kernel_timer_thread`).
- **Tried, not enough:** an interrupt gate in `kernel_hal.c`. Raised threads
  hold an SRW lock shared and ISR/DPC delivery holds it exclusive, closing
  the check-then-act in `xbox_IrqlBlocksInterrupts`. It still hung (rG1),
  so it was reverted. The game-side path evidently does not raise IRQL
  around the list, or the racing writer is elsewhere: the timer DPC thread,
  or the 84 `cli`/`sti`/`pushfd` sites the recompiler emits as RECOMP_UNIMPL
  no-ops.
- **Next:**
  - find what serialises `[hcd+0x41C]` on the console: disassemble the
    inserting side, or watch-point the list head and log the thread on each
    write;
  - check whether XPP brackets it with `cli`/`sti` (a no-op today), which
    would call for a real interrupt-disable in the runtime.
