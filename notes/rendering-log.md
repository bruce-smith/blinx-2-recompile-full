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

### USB hang, continued (2026-10-11 evening)

- The xboxrecomp `ohci.c` interrupt-status race is fixed (atomic set/clear),
  but **the hang remains**: 1 of 4 ten-minute runs, and that one froze at
  t ≈ 34 s during the title Start presses.
- **Full stack at the hang**, oldest first: game 0x0021C4D4 → XInput
  `sub_0036827F` → … → `sub_0036E7A5` (pending-list drain) →
  `sub_0036E407` (complete a transfer) → **game main-loop code**
  (0x000633AB in `sub_00062FB0`, 0x00064969 in `sub_00064850`), which spins
  in Enter/LeaveCriticalSection + NtYieldExecution.
- A USB completion has no business calling the main loop. Most likely the
  completion called through a stale/corrupted callback pointer in a reused
  XInput request object (use-after-free or double submit), and re-entered
  the frame loop, which then waits forever on itself.
- Next: break on `sub_0036E407`'s indirect call and log the request object
  and callback target. Compare XInputGetState's request reuse with the
  model's completion timing.
- **Ownership:** this now belongs to the input/timing worker (`src/usb` is
  theirs).

## 2026-10-11 (night): culling fix, visibility tests, invisible characters

- **Magenta attract stage: fixed** (xboxrecomp `de4de43`). Blinx renders
  stage geometry into two 256x256 targets through a y-up viewport
  (c[58].y > 0). Culling judged winding on screen only, so those passes kept
  their hidden faces, and the main pass sampled the wrong image. The winding
  is now taken relative to the viewport's y direction. The game also
  switches CULL_FACE FRONT/BACK per object.
- **Visibility tests** (GET_REPORT) gate drawing. `RECOMP_ZPASS_FORCE=1`
  (diagnostic) restores the attract **sky** and cliff shading. Counting
  itself works: tests in open sky count pixels, ones behind cliffs fail on
  depth, and the surfaces have no AA. Which test hides the sky is still
  open. A diff of the frame trace is confounded by the demo camera
  differing between runs, so this needs one run that toggles mid-flight.
- **Invisible characters: the title never submits them.** In the attract
  demo no batch of character size reaches the executor, and that is not
  because something is lost:
  - none of the 196 unresolved stubs runs (new `[STUB]` logging, `d1f4a6a`);
  - there are no fixed-function batches;
  - no positions are NaN;
  - every main-ring JUMP goes to the ring start, so no precompiled
    pushbuffers are skipped;
  - no draw method is unhandled;
  - no P8 (fmt 0x0B) texture is sampled at all;
  - forcing visibility does not bring them back.

  So the game decides not to draw them. Next: find the character render
  call in the guest (e.g. from the MDLPL model loader / draw list) and
  trace why it is skipped (a failed load, a flag, a time check).
- Hub fps with the audio worker's APU-on default: ~10.6 (was ~13–15
  without audio).

## 2026-10-11 (late): invisible actors were a memory-layout regression (fixed)

The orchestrator found a 09:50 UTC frame with Blinx rendered, so this was a
bisect. An env toggle on the current build found it:
- `RECOMP_CONTIG_LEGACY=1` restored Blinx;
- `RECOMP_PHYS_RAM_TAG=0`, `RECOMP_TITLE_KEVENTS=0` and `RECOMP_AUDIO=0`
  did not.

Cause: since c1136b0 the contiguous arena started above the 48 MB image,
leaving ~16 MB below 64 MB. Blinx needs ~26 MB, and its actor data landed
past 64 MB, a physical range no console has. The game then skips every
actor model (player and enemies), and the attract sky too. A 64 MB-first
allocator above the image was not enough. The console avoids the collision
by mapping sections virtually (the title XeLoad/UnloadSections at run time).

Fix (xboxrecomp `2009a1c`): the arena numbers from 0x1000 again, 64 MB
first. `MmGetPhysicalAddress` tags all non-window VAs (`XBOX_PHYS_RAM_TAG`),
so untagged numbers always mean arena memory, and the NV2A executor, APU
and OHCI strip the tag. OHCI prefers the arena for untagged numbers when
tagging is on.

Regression run, all OK:
- pad enumerates, Start leaves the title, right-stick pitch moves the
  camera;
- audio plays (59 audible voice reports from tagged RAM);
- no arena exhaustion and no spill;
- the attract demo shows Blinx, enemies and the sky, and hub gameplay shows
  Blinx and his reflection.

Screens: `checkpoint_png/attract_blinx_visible_fixed.png` and
`hub_blinx_visible_fixed.png`.

## 2026-10-12: vertex programs four at a time

With the characters back, the vertex-program interpreter was ~35% of the
executor, and the executor's pace (it acks D3D's kick) is the frame rate.

- A post-transform cache got 0 hits (Blinx draws strips).
- Fetching only the inputs a program reads saved nothing (fetch is 1.6%).
- `nv2a_vsh_run4` (xboxrecomp `c898127`): SSE, four vertices in lockstep,
  bit-identical to the scalar interpreter (2,000 random programs, 0
  differences). Vertex share ~35% → ~13%. A hub run reached 17.3 fps, but
  its end scene differed from the baseline's, so the figure is only
  indicative.
- Render-to-texture drains now count only sampled stages (`5c103b5`):
  -20% drains.

## 2026-10-12: method survey indexed

The executor walker's per-word `note()` (the method inventory) searched
every (subchannel, method) pair seen so far, linearly. It runs for inline
vertex data too, and it was ~15% of the NV2A thread (`pb_walk` self). A
direct slot table fixed it (xboxrecomp `a945b67`): the hub went from 10.7
to 12.1 fps on the same pad script. The NV2A thread is now ~27% idle
(`Sleep(0)` polling for PUT). Of the busy time, the top costs are the
combiners (`nv2a_rc_eval_prep` ~12%), texture sampling and the vertex
programs.

## 2026-10-12: D3D fences executed (12.1 -> 17.0 fps)

A main-thread profile with the executor on: 65% in `sub_002E7F30` (the
kick: it spins on the flush bit until the executor's loop acks it) and 21%
in `sub_002E8110`, D3D's fence wait. The NV2A thread was 27% idle at the
same time. The fence wait was the GPU-idle shim's `Sleep(1)` poll: a
spinning shim alone gave 17.2 fps.

D3D's fences are semaphore releases in the pushbuffer: `0x1D6C` = offset 0
(set once), then `0x1D70` with the fence time, ~9 a frame. The executor now
writes them to `[[0x2F1FB8]+0x30]` and mirrors bits 2–6 into `0x400B10`
(xboxrecomp `704daa8`, blinx2-recomp `9eb4f27`; the shim no longer runs
under PB_EXEC). Measured on the same pad script, in the hub:

| fence released when | fps |
|---|---|
| shim, 1 ms poll (before) | 12.1 |
| executor drains the raster queue, then releases | 11.6 |
| raster batch done (`RECOMP_FENCE_STRICT=1`, no executor stall) | 12.4 |
| executor reaches it (default) | 17.0 |

The default treats "commands read" as done. That is enough for
pushbuffer-space fences, and is already more than the shim claimed. Flips,
clears, visibility reports and render to texture still drain the queue.
The hub renders correctly (Blinx, the reflection, the overlay text).

## 2026-10-12 (later): raster pipeline, pixel path, and what did not help

Committed (xboxrecomp):
- `c59c2cf`: the executor walks the ring GET → PUT through the wrap JUMP. The
  old version guessed the ring's end from the highest PUT seen, and could skip
  commands (fences included).
- `e073a9d`: raster batches pipelined per band (a 4-batch ring), and raster
  threads up to cores − 4. A raster worker's idle time went from 44% to 32%.
  In-run A/B, 28 vs 16 workers: 18.7 vs 16.5 fps.
- `9b59a7a`: a DXT block is decoded in one pass (bit-identical, 0 / 4.8 M
  texels differ).
- `63b1296`: combiner results no register keeps are skipped (bit-identical,
  0 / 400 k pixels differ). One program is 67% of hub pixels. Combiner share
  of a worker: 16% → 11%.

The hub often sits at exactly 20.0 fps = 60/3. The title is vblank-locked,
so a frame has to get under 33.3 ms to reach 30, and smaller gains don't
show.

Tried and not committed:
- **Early kick ack** (acking 0x100410 mid-walk, to overlap the title with
  the executor). It deadlocks. At the stall all fences are complete
  (gpu = cpu − 2) and the flush bit is clear, but D3D's write pointer is past
  PUT, and the main thread waits in `sub_002E0D00` (called from frame pacing,
  `0x00060412`) on a fence that was never kicked. D3D's lazy kickoff seems to
  depend on GET/ack timing. A fix would need its kick heuristics
  reverse-engineered.
- **Render-to-texture barrier batches** instead of draining the queue: correct
  (the reflection renders), but no measurable gain.
- **Pause-spin instead of `Sleep(0)`** in the NV2A loop: no measurable gain.
- **Skipping the visibility-report drains**: no gain.

Measurement caveat: with the other workers' instances running, the hub swings
15–28 fps even with no input. In-run A/Bs under ~15% are noise unless the
machine is quiet.

## 2026-10-12: Blinx 2's D3D kickoff / fence-wait model (for the early ack)

Device pointer at `[0x2F1FB8]`. `dev+0` is the pushbuffer write pointer,
`+4` its end, `+0x2C` the CPU's next fence time, `[+0x30]` the address the
GPU's last fence time is written to, `+0x40` the wrap epoch, and `+0x934`
the NV2A register base.

- **Kick, `sub_002E7F30`.** Sets PFB `0x100410` bit 16 and spins until it
  clears (on hardware: write-combine flush, near-instant). Then it writes
  PUT. With `[0x2F1B10]` set, it also loops on `sub_002E1C50`.
- **InsertFence, `sub_002E8050`.** Writes 8 dwords at the write pointer:
  1. `0x0004A310`, `((wptr << 3 | fence & 0x1F) << 2) | (epoch & 3)`:
     subch 5 method 0x310, latched by PGRAPH into **0x400B10**;
  2. `0x00041D70`, `fence`: the semaphore release that writes `[+0x30]`;
  3. `0x00041D90`, 0, `0x00041D90`, 0: padding, patched later (see below).

  The record (fence, address) is stored in a 64-entry table at `dev+0x64`.
- **GPU position, `sub_002E7E00` / `sub_002E7E80`.** D3D reads the GPU's
  progress from `0x400B10`, not from DMA GET:
  `addr = ((reg >> 5) & 0x7FFFFFC) | 0x80000000`, with low bits giving the
  epoch. `sub_002E7E80` also spins until `0x400B10` bits 2–6 equal
  `[+0x30] << 2`. **Until today the executor never ran method 0x310**, so the
  register held only the fence bits, and D3D always saw the GPU at address 0.
- **Fence wait, `sub_002E8110(fence, flags)`.**
  1. If the fence has passed, return.
  2. Otherwise measure the pushbuffer distance from the GPU position to the
     fence record (`sub_002E7B90`).
  3. **Near (< 0x2000):** spin until `[+0x30]` passes.
  4. **Far:** patch the record's padding to `WAIT_FOR_IDLE` (0x40110) +
     `NO_OPERATION` param 5 (0x40100). Kick (`sub_002E7F00`), then wait on the
     KEVENT at `dev+0x1DCC`. That event is set from the interrupt path below.
- **Interrupt path.**
  - D3D's ISR `sub_002EA2E0` (vector 3) checks `[dev..+0xA0]` and PMC
    `INTR_EN` (`+0x140`), then queues a DPC.
  - The DPC's PGRAPH handler `sub_002EAA50` reads:
    - `0x400100`: INTR, where bit 0 is NOTIFY;
    - `0x400108`: NSOURCE, which must be non-zero and must not include 0x40;
    - `0x400704`: the trapped method, masked with `0x1FFC` (== 0x100);
    - `0x400708`: the trapped data.

    It then calls `sub_002EA7E0(data)`. Case 5 of that function is the
    fence-wait wakeup.
  - The handler brackets its work with `0x400720 = 0` … `= 1`.

**Why the early ack deadlocked:** with it, the title gets far enough ahead
of the executor to take the "far" branch of the fence wait. That branch waits
for a NOP-notify interrupt the executor never raised. Without the early ack the
title is always near the executor and spins instead.

**Plan:**
1. Execute subch 5 method 0x310 (done: `0x400B10` now holds the real
   position).
2. On `NO_OPERATION` with a non-zero parameter, raise the PGRAPH NOTIFY
   interrupt the way the vblank is raised. Set INTR/NSOURCE/TRAPPED_ADDR/DATA
   and PMC bit 12, have the timer thread call the ISR, and let the executor
   wait for `0x400720` to return to 1 (the GPU stalls at a notify on hardware
   too).
3. Soak with `RECOMP_EARLY_ACK=1` before it becomes the default.
