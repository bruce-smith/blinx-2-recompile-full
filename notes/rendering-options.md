# Blinx 2 rendering: options assessment (2026-10-11)

## Where we are

The game boots to its title screen and attract loop: `title_movie_1a.sfd`
loops and `song_TITLE.adx` plays, then the attract stage loads and a normal
frame loop runs. **Nothing is drawn.** D3D submits NV2A pushbuffer commands
(USER `PUT = GET`), and the `main.c` "GPU always idle" shim reports every
fence complete so the game never waits on a GPU. `RECOMP_PB_EXEC` (the
runtime's pushbuffer executor) is off.

## What xboxrecomp offers today

| Piece | Where | State |
|---|---|---|
| Pushbuffer executor | `src/kernel/nv2a_pb_exec.c` (~3.5 k LOC), `RECOMP_PB_EXEC` | Walks the command stream. It handles surface selection and clears, and rasterises **screen-space, flat-shaded** batches (UI/HUD/2D) into the guest framebuffer. Batches needing a vertex program, texturing or depth are counted and skipped, and `nv2a_pb_exec_report()` ranks what is unhandled. Also: `RECOMP_RASTER_TEST`, `RECOMP_FB_DUMP=<prefix>` (BMP per frame), `RECOMP_TEX_DUMP`. |
| Vertex-shader interpreter, combiners | `src/kernel/nv2a_vsh_interp.c`, `nv2a_combiner.c` | Pieces toward real 3D in the executor path. |
| PGRAPH → D3D11 translator | `src/nv2a/nv2a_pgraph_d3d11.c` (~650 LOC) | The executor's own docs name it as the upgrade path for textured/vertex-program geometry. Partial. |
| xemu-derived NV2A core + MMIO hook | `src/nv2a/nv2a_core.c`, `nv2a_mmio_hook.c` | Register-level emulation (PFIFO/PGRAPH/PCRTC…). Not wired into this build. The aperture is plain RAM here. |
| Framebuffer window | `src/video/fb_present.c`, `RECOMP_FB_WINDOW` | GDI window that shows the guest framebuffer (from `AvSetDisplayMode`). It copies once per flip, so no tearing. `RECOMP_FB_VA` pins an address. |
| D3D8 → D3D11 HLE layer | `src/d3d/` (`xbox_d3d8`, ~9 k LOC incl. GL, VSH, combiners, swizzle) | A full IDirect3DDevice8 replacement. It only helps if the game's D3D calls can be redirected to it. |
| Host FMV | `RECOMP_FMV_HOST`, `src/video/` | Plays an `.sfd` the game opens on the host instead of via Sofdec. |

## The two paths

### (a) Execute the NV2A pushbuffer (LLE-ish), presented via the FB window

The game's lifted D3D (295 D3D + 459 D3DX + 735 XGRPH functions, plus code
inlined into the game by LTCG) already produces a complete NV2A command
stream. Executing it catches every draw however it was issued.

- **First pixels are cheap:** clears and 2D/screen-space batches already work
  in the executor. The title screen's logo and menu text are likely 2D.
- **Real 3D is the long tail:** vertex programs (the interpreter exists),
  texture formats and swizzle, register combiners and depth all need
  finishing, ideally through `nv2a_pgraph_d3d11.c`.
- **Risks:** surface/DMA addressing. The executor itself warns that
  `SET_SURFACE_COLOR_OFFSET` is a DMA offset, and the Dashboard overwrote its
  own image this way. Blinx 2's framebuffers come from the contiguous window,
  which is the safe case. CPU cost of software rasterisation is the other risk.
  And the GPU-idle shim must become real completion (fences/semaphores
  advanced by the executor) or the two will disagree.
- **Effort:** first image (title background or menu, possibly untextured)
  takes hours to a few days. Textured 3D gameplay at reasonable fidelity
  takes weeks. xemu-level accuracy takes months.

### (b) HLE: override the lifted D3D entry points with `xbox_d3d8`

Redirect `Present`, `DrawVertices`/`DrawIndexedVertices`, `SetTexture`,
`SetRenderState` and friends (via `recomp_manual.c` wrappers) to the existing
D3D8 → D3D11 layer.

- **Blocker:** the XDK's D3D is not a clean call boundary. Many hot paths
  (render states, vertex-shader constants, `Begin`/`End`, push-buffer
  reservation) are header-inlined code that writes NV2A methods straight into
  the pushbuffer, and LTCG inlines more. Those never reach an entry point, so
  HLE sees a partial and inconsistent state.
- **No symbols:** every entry point has to be identified by hand among about
  1,500 lifted D3D/D3DX/XGRPH functions, plus their argument conventions
  (thiscall, register args).
- **Mixed state:** objects the game created through lifted code (textures,
  vertex buffers with swizzled data in contiguous memory) have to be
  translated into `xbox_d3d8` objects.
- **Effort:** weeks before anything coherent appears, and fragile per title.
  It pays off only for titles whose D3D usage is not inlined.

## Recommendation

**Go with (a).** Its first step needs no new code:

1. Boot with `RECOMP_PB_EXEC=1 RECOMP_FB_WINDOW=1 RECOMP_FB_DUMP=fb_`
   (keep the GPU-idle shim for now) and capture:
   - whether the title screen produces any non-black frame (BMP dumps);
   - `nv2a_pb_exec_report()`'s ranked list of unhandled methods and skipped
     batches.

   That turns "how far is rendering" into a measured list.
2. If the surface or present path is wrong, fix that first: framebuffer
   address from `AvSetDisplayMode` / `SET_SURFACE_COLOR_OFFSET`, flip
   detection.
3. Then work down the report: textured screen-space quads first (the title
   background and logo), then the vertex-program path via
   `nv2a_pgraph_d3d11.c`.
4. Replace the GPU-idle shim with executor-driven completion once the executor
   consumes the stream: semaphore release → `[[dev+0x30]]`, and REF.

**Parallel cheap win:** `RECOMP_FMV_HOST=1` should make the intro and title
movies visible through the host player, independent of the GPU work.

**Input is separate and also missing:** nothing calls `xbox_OhciInit()`, so
`RECOMP_USB`/`RECOMP_PAD_PRESS` are inert. Wiring it (where the template or
the kernel init expects it) is needed before menus can be driven.
