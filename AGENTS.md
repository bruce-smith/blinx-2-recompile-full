# AGENTS.md

Workspace for statically recompiling **Blinx 2** (original Xbox) with the
xboxrecomp toolkit. Windows + MSVC (VS 2022) + PowerShell only. Python is the
Windows launcher `py -3` (Python 3.12 at `C:\Python312`).

## Layout

- `xboxrecomp/` — clone of github.com/sp00nznet/xboxrecomp (v0.13.1): the
  Python recomp pipeline + the C runtime libraries. It is a git repo and may
  carry local uncommitted edits — run `git -C xboxrecomp status` / `diff`
  before assuming it is pristine, and never revert it blindly.
- `blinx2-recomp/` — the game project that produces the `.exe`. Copied from
  `xboxrecomp/templates/new-game/`; `project(blinx_2_recomp)` → the exe is
  named `blinx_2_recomp.exe`. It is now its **own git repo** (initial commit
  holds `.gitignore`, `CMakeLists.txt`, `src/main.c`, `src/recomp_manual.c`);
  the existing `.gitignore` excludes `build/` and the fully generated
  `src/recomp/gen/`, so those never appear in `git status` — regenerate rather
  than version them.
- The workspace root `E:\Blinx2project` is itself a git repo (origin
  github.com/bruce-smith/blinx-2-recompile-full). `xboxrecomp/` and
  `blinx2-recomp/` are **submodules** (`.gitmodules`). `xboxrecomp` tracks
  the fork github.com/bruce-smith/xboxrecomp, branch `blinx2-fixes`. Inside
  it, `origin` is upstream sp00nznet with push `DISABLED`, and `fork` is where
  to push. Never push upstream. `blinx2-recomp` tracks
  github.com/bruce-smith/Blinx2-Recompiled `main`. After pushing new submodule
  commits, bump the pointers here (`git add xboxrecomp blinx2-recomp`) and
  push the superproject. The root `.gitignore` excludes `Blinx_2.xiso`, `game_files/`,
  `ghidra_12.1.4_PUBLIC/` and the bulky `assets/` subdirectories.
- `game_files/` — disc contents extracted from `Blinx 2.xiso` (root) with
  `xdvdfs.exe` (root; `xdvdfs.exe --help` for `unpack`/`ls`/`pack`):
  `default.xbe` (38 MB) + `.ipk`/`.iph` data.
- `notes/step 2..7.txt` — verbatim record of every pipeline command actually
  run **with its full output**. This is the ground truth for flags used; read
  the relevant step before re-running anything.
- `notes/first-opencode-session.md` — full record of the 2026-10-08/09 OpenCode
  bring-up session (the DSOUND fix + audio-spin diagnosis).
- `ghidra_12.1.4_PUBLIC/` — Ghidra install, used only by the optional
  symbol-naming step.
- `assets/` — the `.ipk`/`.iph` archives extracted with blipks. `CATALOG.md`
  covers formats, the per-archive and per-type inventory, and open
  questions; `README.md` says how to reproduce. `extracted/` (~1.7 GB of
  game data), `tools/` and `logs/` are gitignored. The `.ipk`s hold
  textures, text-as-texture bundles, SE banks and camera/event data only.
  Models, motions and stage geometry live in the XBE `MDL*`/`M*`/`G*`/`MOT*`
  sections, not in the archives.

Upstream docs are authoritative and good: `xboxrecomp/README.md` (Quick Start),
`xboxrecomp/docs/GETTING_STARTED.md`, `xboxrecomp/tools/README.md`.

## Build

```powershell
# toolkit runtime libs only
cmake --build E:\Blinx2project\xboxrecomp\build --config Release

# the game — CMakeLists add_subdirectory's ../xboxrecomp, so this rebuilds the
# runtime libs as well; building the game alone is usually enough
cmake --build E:\Blinx2project\blinx2-recomp\build --config Release
```

- Both build trees already exist (VS generators); don't re-run
  `cmake -S . -B build` unless the cache is missing.
- Output: `blinx2-recomp\build\Release\blinx_2_recomp.exe` (~125 MB). A full
  build of the generated C is ~16 min; rebuilds are fast when only
  game/runtime sources changed.
- The log is wall-to-wall warnings — grep for `error C` / `LNK` before
  concluding anything from a failed build. A failure inside `xboxrecomp/src`
  is usually a local edit there: check `git -C xboxrecomp diff` before looking
  at generated code.

## Regenerating the recompiled C

Run every `py -3 -m tools.*` with cwd = `E:\Blinx2project\xboxrecomp`. The
tools' default input/output paths (`tools/disasm/output`,
`tools/func_id/output`, `tools/abi_analysis/output`) are **relative to the
current directory**, and `tools.recomp` reads the earlier steps' output from
there — running from anywhere else scatters or misses files.

Order and exact commands (see `notes/step N.txt` for expected output):

```powershell
cd E:\Blinx2project\xboxrecomp
py -3 -m tools.xbe_parser   E:\Blinx2project\game_files\default.xbe --json E:\Blinx2project\game_files\mygame_analysis.json
py -3 -m tools.disasm       E:\Blinx2project\game_files\default.xbe --text-only --extra-sections DSOUND,D3D,D3DX,XGRPH,XPP,SRCADV,SRCED,SRCAC,PSFD_I,PSFD_B,PSFD_P,PSFD00 --seed-functions E:\Blinx2project\blinx2-recomp\seeds\seed_functions.json   # ~50 s
py -3 -m tools.func_id      E:\Blinx2project\game_files\default.xbe -v                    # ~30 s
py -3 -m tools.abi_analysis E:\Blinx2project\game_files\default.xbe -v                    # ~1 min
py -3 -m tools.recomp       E:\Blinx2project\game_files\default.xbe --all --split 250 --gen-dir E:\Blinx2project\blinx2-recomp\src\recomp\gen --exclude-manual E:\Blinx2project\blinx2-recomp\src\recomp_manual.c --coalesce-functions E:\Blinx2project\blinx2-recomp\seeds\coalesce.json   # ~15 min
```

- **`--coalesce-functions …\seeds\coalesce.json` is required.** It
  merges false splits whose loops would otherwise become host-stack
  recursion (`sub_00044900` overflowed the host stack ~11 min in). Needs
  xboxrecomp `ce832a6`+ (the `internal_alias_starts` key).
- **`--exclude-manual` is required.** `recomp_manual.c` wraps
  `sub_002F89C3` (the D3DX JPEG guard). The recomp must emit the generated
  body as `sub_002F89C3_gen`, or the link fails / the guard is lost.
  Since blinx2-recomp `7b65d06` it also wraps `sub_002EAA50`, D3D's
  PGRAPH interrupt handler. The wrapper emulates the write-1-to-clear ack.
  A gen made before that commit fails to link (duplicate `sub_002EAA50`):
  rerun the recomp step.
- Skipping `abi_analysis` still builds, but every generated signature falls
  back to a guess (cdecl / 0 params).
- **`--extra-sections` is load-bearing, not optional.** `--text-only` skips
  every section but `.text`, and Blinx 2's real x86 also lives in the
  D3D/D3DX/XGRPH/DSOUND/XPP/SRCADV/SRCED/SRCAC sections. Code reached only by
  jumps in an unswept section is never found, so it compiles to a
  `g_esp += 4` stub in `recomp_stubs_unresolved.c`. That gives guest stack
  corruption and deterministic crashes or garbage. Two cases so far:
  - 2026-10-09, sub_002AA810: DSOUND not swept. Adding DSOUND gave 320 real
    functions.
  - 2026-10-10, texture loader: the gen had been produced with only DSOUND
    swept. D3DX `sub_002F4EBC` was lifted as 36 bytes, and its two
    continuations were stubs. It returned with its 0x434 frame on the stack,
    which zeroed the caller's name pointer and caused the
    `media\dds\.dds` probe flood.

  With the full list the disasm finds 10,525 functions (was 8,688): D3DX
  3→459, XGRPH 10→735, D3D 94→295, XPP 11→230, SRCADV 66→261. Unresolved
  stubs dropped 389→204, and 157 of the remaining ones are in `.text`.
  `tail_jump_alias` is 1,301. Check `recomp_stubs_unresolved.c`'s count after
  every regen.
  - **DOLBY is deliberately excluded:** it is the Dolby encoder's DSP56300
    microcode for the APU, not x86.
  - **PSFD_I/B/P/00 are x86** (the CRI Sofdec movie decoder, reached only
    through function pointers). They were wrongly thought to be data and are
    swept since 2026-10-10: 10,549 functions; PSFD00 20, PSFD_B 4.
  - **The MDL*/M*/G* blobs stay out** (they are data; scanning them created
    14,549 false functions).
- **Seeds are tracked in `blinx2-recomp/seeds/seed_functions.json`.** Pass
  that file to `--seed-functions`. `tools/recomp/output/` is an untracked
  output dir, and `seed_from_log` writes there, so copy the result back
  into `seeds/` and commit it after adding seeds.
- **Seed workflow** (runtime-observed entry points `--text-only` cannot find
  statically): after a run, `py -3 -m tools.seed_from_log <log>` writes
  `tools/recomp/output/seed_functions.json`, then re-run the whole pipeline
  with `--seed-functions tools/recomp/output/seed_functions.json` on the
  `disasm` line. Without it the worker `0x002D702E` is missed and boot dies on
  an unresolved ICALL. Docs: `tools/recomp/icall_feedback.py`.
- The `float` data-pointer pass (`_pass_data_ptr_targets`) scans **only**
  conventional data sections (`.rdata`/`.data`/`.data1`/…). With `--text-only`
  every other section counts as data, and the `MDL*`/`M*`/`G*` model blobs are
  not pointer tables: scanning them produced 14,549 coincidental "function
  addresses" (the `tail_jump_alias` fragments), fixed 2026-10. Do not widen it
  back to "all non-text sections". Regression test:
  `tools/disasm/test_data_ptr_sections.py`.
- The analysis JSON is named `mygame_analysis.json`, **not**
  `default_analysis.json`. Tools look for `<xbe stem>_analysis.json` and accept
  any `*_analysis.json` only while `game_files/` holds exactly one `.xbe` —
  drop a second XBE in there and the lookup silently breaks (or pass
  `--analysis-json`).
- Output is 43 `recomp_*.c` + `recomp_funcs.h` + `recomp_dispatch.c` +
  `recomp_stubs_unresolved.c` + `recomp_types.h` (10,549 functions, ~3.0 M
  lines with the full extra-section list, 2026-10-10). `recomp_types.h` is written by the recompiler,
  not the template: "Cannot open include file: recomp_types.h" means the
  recomp run never finished.
- `blinx2-recomp/src/recomp/gen/` is gitignored and fully regenerated — never
  hand-edit it. Hand-written code goes in `blinx2-recomp/src/recomp_manual.c`
  (`recomp_lookup_manual`, `recomp_unimpl`, `sub_X` overrides).
- The game `CMakeLists.txt` globs `gen/*.c` with `CONFIGURE_DEPENDS`, so
  added/removed chunks are picked up on the next build; unresolved externals
  like `recomp_0087.c` mean the glob is stale — re-run configure.
- Regeneration rewrites every gen file, so the following build is a full
  ~16 min rebuild, not an incremental one.
- Optional Ghidra naming (`tools/ghidra_naming/run_ghidra.sh`) is a dead end
  here: it needs `GHIDRA_HOME=E:\Blinx2project\ghidra_12.1.4_PUBLIC` plus the
  Jython Ghidra extension, takes ~16 min, and exported **0 names**
  (`notes/step 6.txt`). Skip it unless that changes.

## Running the game

- **Double-click `build\Release\blinx_2_recomp.exe`** to play. Since
  2026-10-11 (blinx2-recomp `e496400`) it starts with these defaults:
  - `RECOMP_PB_EXEC`, `RECOMP_FB_WINDOW`, `RECOMP_USB` and
    `RECOMP_KEYBOARD` are on when unset;
  - the window is titled "Blinx 2 (recomp)" and opens in front;
  - closing the window ends the process;
  - the previous runs' `blinx2_recomp.log` and `xbox_kernel.log` are kept as
    `<name>.prev-<last write time>.log`, the newest five each (blinx2-recomp
    `23a5d78`). A crash log survives the next launch.

  **Agents: do not run tests in `blinx2-recomp\build\Release`.** That folder
  is the human's: their logs and their save are there. Test from your own
  build tree (or another folder), with `RECOMP_HEADLESS=1`, and pass
  `RECOMP_SAVE_DIR=<your dir>` if the run must not touch the shared
  saves/cache. The human's save slots live in `game_files\UDATA` (XAPI's
  E:\UDATA on partition 1), not under `%LOCALAPPDATA%\xboxrecomp`. Since
  xboxrecomp `67c7518`, an explicit `RECOMP_SAVE_DIR` takes `UDATA`/`TDATA`
  as well (`<dir>\UDATA`). Older builds still read and write the shared
  slots. To test with the human's progress, copy `%LOCALAPPDATA%\xboxrecomp`
  plus `game_files\UDATA` into your dir. Never write to theirs.

  Keyboard: arrows = d-pad, Enter = Start, Z/X/A/S = A/B/X/Y,
  Q/E = White/Black, 1/3 = LT/RT, Shift/Ctrl = L3/R3 (thumb clicks),
  Backspace = Back, I/J/K/L = right stick, numpad 8/4/2/6 = left stick.
  A host XInput pad also works (host LB/RB = White/Black, triggers analog);
  the mapping is printed to the log at the first poll (xboxrecomp
  `006bf0e`). First-person pitch needs a gen made with xboxrecomp `aa5e481`+
  (`movsx` from bp/sp sign-extends; 9 `SX16(LO16(ebp))` lines in
  recomp_0005/0013/0016).
  A key already held when the window gets focus is not a press until it is
  released (xboxrecomp `0d4086b`). Windows sends the newly focused window that
  key's auto-repeats, so Enter still down from launching the exe read as
  Start/A and skipped the intro movies. The first 24 raw host-pad changes
  are logged as `[HOSTPAD]` (`4a64408`).
  Window: opens at 2x, resizable with aspect kept; Alt+Enter or F11 =
  fullscreen, F9 = nearest/linear (`RECOMP_FB_SCALE`, `RECOMP_FB_FILTER`).
- The right-stick pitch fix (`aa5e481`, lifter `movsx` from bp/sp) needs a
  regen + full rebuild before it is in the exe.
- The exe makes its own folder the working directory, so `xbox_kernel.log`
  lands next to it. Without a console, stderr goes to `blinx2_recomp.log`
  there. An unhandled crash shows a MessageBox.
- **Characters render again** (2026-10-11 regression, fixed by the memory
  layout above). If actors ever vanish, try `RECOMP_CONTIG_LEGACY=1` first.
- **Culling** judges winding against the viewport's y direction (xboxrecomp,
  2026-10-11). Blinx 2 renders stage geometry into 256x256 targets through a
  y-up viewport, and screen-only winding tinted the attract stage magenta.
- **USB/XInput freeze: fixed (2026-10-12, P5).**
  - Cause: XPP pops its TD free list (`sub_0036E33D`, `[0xF2E0CC]`) without
    a lock. It does so from both the USB DPC and the game thread's
    XInputSetState, which raises to DISPATCH. Here DPCs ran regardless, so
    the same TD was handed out twice. That left the pad's IN endpoint dead
    and a rumble request pending forever: the game spins in `sub_0005E060`.
    It was not a list cycle.
  - Fixes:
    - xboxrecomp `dd55908`: OHCI retires TDs in hardware order, and keeps
      an always-on endpoint history that dumps on a "BAD HeadP".
    - xboxrecomp `c9dd72f`: DISPATCH_LEVEL is a process-wide lock for guest
      raises and host DPCs (not ISRs), with a 2 s bounded wait.
      `RECOMP_DISPATCH_LOCK=0` opts out; `RECOMP_DPC_RACE_TRACE=1` is the
      diagnostic; the test is `tests/kernel_dispatch_lock`.
  - 10-min runs with the lock on: 0 freezes in 8 (2 in 4 without it).
  - The OHCI Frame Number Overflow is raised since `d3fd7f8`.
  - `RECOMP_WATCHDOG_STALL=15` still catches any stall in scripted runs.
- **Never kill `blinx_2_recomp.exe` by image name**: the human may be
  playing. Kill only the PID you started. If their instance blocks a
  relink, build the `xbox_kernel` target alone to check that it compiles.
- **Agents / scripted runs: set `RECOMP_HEADLESS=1`.** That means no window,
  no dialog, and none of the four defaults. Set
  `RECOMP_PB_EXEC`/`RECOMP_USB`/… explicitly, and redirect stderr. The
  untracked `build\Release\run_p4.ps1` does this.
- `blinx2-recomp/src/main.c` hardcodes `BLINX_2_XBE_PATH` /
  `BLINX_2_DIR` as absolute `E:\Blinx2project\game_files` paths and the
  entry point `0x0029A1DA`. Move game_files and you must edit main.c.
- Crash diagnostics come from the VEH handler in `main.c`: guest registers,
  guest-stack return addresses, and the last 16 ICALL targets. Function names
  (`sub_XXXXXXXX`) come from dbghelp + the PDB, but the default Release build
  emits **no `.pdb`** — use a Debug/RelWithDebInfo build (or add `/DEBUG`) if
  you want named frames in the crash output.
- Runtime env switches (read via `getenv`, no rebuild needed):
  `RECOMP_AC97_READY=1` routes the APU aperture and starts the emulated APU
  (main.c gates `mcpx_apu_init_standalone` on it),
  `RECOMP_WATCHDOG_SECS=<n>` hang watchdog (dumps guest esp, 6 regs, ICALL
  trace, NV2A pointers, and 400 dwords of guest stack, then `_exit(3)`),
  `RECOMP_UNIMPL_TRAP=1` stop at the first unimplemented instruction.
  `RECOMP_TITLE_KEVENTS` defaults to 1 (`=0` opts out; blinx2-recomp
  `13018e3`). D3D's BlockUntilVerticalBlank (`sub_002E0DB0`) waits on a
  title-built KEVENT at device+0x1DBC. Without it that wait failed at once,
  so CRI ADXM's vsync thread spun ~80k/s instead of 60. Sofdec times
  video-only movies by it, so the title-screen crystal loops
  (`title_movie_1a/2a.sfd`, 6 s) ran ~17x fast and burned a core.
  Diagnostics: `RECOMP_TIMING_TRACE=1`; `RECOMP_XINPUT_TRACE=1` also logs
  stick floats (`048bd54`).
- **Sound is on by default** in the playable exe (blinx2-recomp `c7715e3`,
  xboxrecomp `de4de43..0760b18`). The APU's VP is emulated and output through
  XAudio2. GP DSP effects/reverb are still stubbed, and the DSP doorbell
  watcher in `main.c` is still needed. `RECOMP_AUDIO=0` opts out; headless
  runs stay silent unless `RECOMP_AUDIO=1`. `RECOMP_APU_WAV=<file>` dumps the
  device output, and `RECOMP_APU_STATS=1` logs voices. Speaker mixbins
  are folded down to stereo, and reverb/FX sends are not added dry
  (`a329ee8`). `RECOMP_APU_MIXDOWN_ALL=1` gives the old sum of all bins, `=0`
  bins 0/1 only. Blinx uses only bins 0/1 and sends nothing to the
  reverb/FX bins in any observed scene, so the missing GP reverb is
  inaudible. Sofdec A/V sync is within one frame (median video +19 ms) with
  no drift. Root causes fixed:
  - the APU monitor zeroed the VP mix;
  - heap "physical" addresses aliased the contiguous arena (now
    `XBOX_PHYS_RAM_TAG`; `RECOMP_PHYS_RAM_TAG=0` opts out);
  - pitch was ignored (linear resampler now);
  - a DSOUND ISR crash in `sub_00335C18` (trapped-FE PIO FIFO);
  - static, "reverb" and a silent opening movie (`c85c259`). The APU read
    DSOUND's contiguous voice/SGE/notifier structs from the game image and
    wrote notifications into it. APU address resolution must check the
    contiguous arena before the image range when RAM tagging is on. **Any new
    device model that follows guest physical pointers needs the same order
    as OHCI `bus_resolve` and `mcpx_apu_phys`.**

  Details: `E:\blinx2_wt\audio\notes-audio.md`.

## Tests

- Python suite: `py -3 -m pytest tools/` from `xboxrecomp` — clean run (pytest
  9.1.1 installed 2026-10) is **574 passed / 38 skipped / 57 subtests passed**;
  the skips need a C compiler on PATH, so check the skip count, not just the
  pass count. `tools/fusion/test_lifter_diff.py` needs the optional `pefile`
  module — `--ignore=tools/fusion` if it is absent. `capstone` 5.0.7.
- `py -3 -m tools.conformance` — differential lifted-C-vs-real-CPU suite.
- C runtime tests: each `xboxrecomp/tests/<name>/` is a **standalone** CMake
  project (configure/build/ctest per its README). The top-level build does not
  add them, so `ctest` in the main build dirs has nothing to run.

## Game-specific facts

- Retail NA XBE, title ID `0x4D530065`, LTCG build (`c:\B\Final - LTCG\...`),
  base `0x00010000`, 73 sections, 121 kernel imports.
- **Current count (2026-10-12, blinx2-recomp `c129123` seeds):** 10,565
  functions through abi_analysis, 196 unresolved stubs, 45 gen `.c` files.
  `0x000EF540`, the stage 01-01 load-completion callback, is seeded; without
  it the mission summary never appears. On 2026-10-10 the count was 10,549
  functions and 204 stubs. The earlier "23,753" figure did not match the disasm summary, which
  had reported 8,688 for the DSOUND-only run. The 2026-10 data-ptr fix removed
  14,549 false functions. `--text-only` is correct for this title: the
  model-blob sections (MDL*/M*/G*) are data.
- **Boot status (2026-10-10):** full write-up in
  `notes/audio-spin-fix.md`. Boot now gets past audio init, DirectSound init,
  the texture loader and the old SetLastError crash, and plays the intro movies
  (NV2A pushbuffer `PUT = GET = 0x2BB0`). It reaches this point in ~1–2 min
  and ran 900 s with no crash.
  - **Audio-queue spin: fixed.** Root cause was in the runtime, not AC97:
    `bridge_PsCreateSystemThreadEx` ignored `CreateSuspended`. Audio init
    (`sub_002A1BE0`) creates `sub_002A1B20`/`sub_002A1BA0`/`sub_002A17B0`
    suspended, stores their handles, then resumes them. Started early,
    `sub_002A17B0` self-suspended on a handle slot (`0xF4A140`) that was still
    0, failed (NtSuspendThread + RtlNtStatusToDosError ×675k), and spun with
    the others on lock `0x00F4A160`. The bridge now creates the host thread
    `CREATE_SUSPENDED` (log shows `(suspended)`).
  - **DirectSound DSP doorbell: worked around.** `sub_003341BE`, holding
    the DSOUND lock `0x00339ADC`, writes 3 to the GP scratch+0x810 and spins
    until the (stub) GP DSP clears it. The address moves with contiguous
    allocations (0x803D0810, then 0x80A20810), so `src/main.c` resolves it at
    run time from `[[[[[[g_pDS@0xEC4C0C]+0x4]+0x14]+0x8]+0x10]]+0x810` and
    clears it (`[DSP] …` log lines).
  - **SetLastError AV (`sub_00299449`): fixed.** The runtime's fixed layout
    (fake TLS/KTHREAD blocks at `0x0070xxxx`, main stack
    `0x00780000–0x00F80000`, bump heap from `0x00F80000`) sat on top of
    Blinx 2's image, which ends at `0x0303AC20` (`.data` BSS alone runs to
    `0x0103DB40`). Stack, CRT heap and game globals overwrote each other.
    `xbox_memory_layout.[ch]` now moves that region above the image
    (`0x03040000`, stack 1 MB, heap `0x031C0000–0x04000000`, 14 MB) when the
    image reaches `0x00700000`. Smaller images keep the old layout.
  - **Texture-name flood: fixed** by regenerating with the full
    `--extra-sections` list (an unresolved D3DX stub leaked guest stack).
    **XBE section cap: fixed** (all 73 sections load). **stderr: buffered**
    (it was the boot's main cost).
  - **D3D fences: executed (2026-10-12).** D3D's fences are semaphore
    releases in the pushbuffer (`0x1D6C` offset, `0x1D70` value), written to
    `[[0x2F1FB8]+0x30]`; the low bits are mirrored into NV2A reg `0x400B10`.
    With `RECOMP_PB_EXEC` (the default) the executor writes them as it reaches
    them (xboxrecomp `704daa8`, registered in `main.c` via
    `xbox_Nv2aSemaphoreAt`). Here "done" means the commands have been read.
    `RECOMP_FENCE_STRICT=1` also waits for the queued pixels (slower: 12.4 vs
    17 fps in the hub). Without the executor (`RECOMP_HEADLESS`), or with
    `RECOMP_GPU_IDLE_SHIM=1`, the old "GPU always idle" shim reports every
    fence complete instead (`[[dev+0x30]] = [dev+0x2C] - 2`, 1 ms poll).
    `RECOMP_GPU_IDLE_SHIM=0` disables both.
    Since xboxrecomp `5a733df` the executor also handles two more of D3D's
    signals:
    - **GPU position.** D3D reads it from PGRAPH `0x400B10`, loaded by
      subch 5 method `0x310` before each fence, not from DMA GET.
    - **PGRAPH NOTIFY.** It is raised for `NO_OPERATION` with a parameter;
      D3D's fence wait sleeps on one when the GPU is far behind.

    `RECOMP_EARLY_ACK=1` (default off) acks D3D's kick mid-walk. It no
    longer deadlocks, but gives no fps gain yet. The model is in
    `notes/rendering-log.md`.
  - **Executor parallelism (2026-10-12).** Geometry (vertex programs, clip,
    set-up) runs on the raster pool per batch (xboxrecomp `3e4d724`;
    `RECOMP_SERIAL_XF=1` keeps it on the executor). Register-combiner draws
    shade four pixels at once (`a622dca`; `RECOMP_SCALAR_PIXELS=1` is the
    scalar reference). `RECOMP_PIXEL_CHECK=1` draws every span both ways and
    reports differences: slow, for testing only. In-play hub camera:
    ~19 → ~27 fps, most frames at the title's 2-vblank (30 fps) cadence.
    On an otherwise idle machine the in-play hub holds 30–31 frames/s. The
    heaviest view so far is the hub's high overview camera behind the first
    CHALLENGE prompt, with the reflective floor filling the frame.
  - **Rendering glitches, resolved.** The human's random yellow/black
    one-frame glitches were methods lost at pushbuffer wraps (`c59c2cf`).
    Later "reflection + HUD gone for 1–3 frames" sightings were a capture
    artifact: mid-frame report dumps overwrote flip dumps (`9ef0a2e`).
    `RECOMP_FRAME_SUMMARY=1|2` separates "the title submitted different work"
    from "the same work rendered differently".
    The black streaks in the first mission and the floor band in the opening
    tutorial were float edge functions. Near-plane clipping leaves vertices
    ~1e7 px off screen, so pixels on a shared edge fell inside neither
    triangle. Edges are now set up in double, rebased to the triangle's first
    pixel, and the neighbour's edge is the exact negation (`df9a07d`, P8;
    both span loops evaluate them in the same order).
  - **Logging from the NV2A thread is expensive.** stderr is one locked
    stream shared with every guest thread. The per-kick and per-flip lines
    cost ~14% of the executor until they were gated on
    `RECOMP_NV2A_TRACE` (`c0a6afa`, `62d8aa6`). A 4-min hub log went from
    ~100–170k lines to ~8k. Keep anything per-kick, per-draw or per-pixel
    behind an env switch.
  - **`RECOMP_ASYNC_SYNC=1` (opt-in, xboxrecomp `4c40733`).** The flip
    becomes the only raster drain:
    - render-to-texture hazards become barrier batches;
    - colour and depth clears become ordered band jobs;
    - visibility reports are written when their batches finish (z-pass is
      counted per report epoch).

    It is aimed at the intermittent ~22 fps state around the hub's first
    CHALLENGE prompt, where the executor sat in drains. It is not yet
    measured there; where frames are already at 30 it changes nothing.
    `47a38a2` (P8) times the drains by call site.
  - **Heap exhaustion: fixed** with `xbox_SetMapSize(128 MB)` in `main.c`
    (78 MB heap; the title still sees 64 MB of RAM).
  - **Seeds added (2026-10-10):** `0x001B8BF0` (IPK loader thread), and
    `0x00366CBC`/`0x003674FA` (XPP indirect-call targets that failed to
    resolve).
  - **Intro movies: fixed.** The main loop paces frames on a vblank counter
    (`0xAE7388`) bumped by the title's vblank callback `0x000604A0`, which
    D3D's NV2A ISR calls. `main.c` now defaults `RECOMP_VBLANK=1` (the runtime
    raises the interrupt only when it is set), and `recomp_manual.c` supplies
    the callback, which the disassembler never found. Sofdec's PSFD_I/PSFD_P
    entries (`0x0033A340`/`0x0033B040`), `0x002D0450` and `0x000604A0` are
    now seeded (seed file not in git; recorded in the note). Result: 10,553
    functions, 200 stubs, no unresolved ICALLs.
  - **Title textures: fixed.** D3DX's format dispatcher tried libjpeg
    (`sub_002F89C3`) on a non-JPEG texture; libjpeg's setjmp/longjmp error path
    cannot resume in lifted code (esp came back +0x90, ebx/esi/edi = -1, then
    an endless surface-chain walk). `recomp_manual.c` now returns E_FAIL unless
    the data starts with the JPEG SOI `FF D8` (needs `--exclude-manual`).
  - **Reached the title screen (2026-10-10):** intro movies →
    `title_tex_us` / `uniform_tex` → title background movie
    `title_movie_1a.sfd` + title music `adx\song_TITLE.adx` → `tsinfo_tex_us`,
    `media\plcom_tex`. Nothing is drawn (GPU-idle shim; `RECOMP_PB_EXEC` off).
  - **Host stack overflow at `plcom_tex`: fixed.** `sub_00044900` was
    split at five false interior starts; a loop across them became tail-call
    recursion (exit `0xC00000FD` ~11 min in). It is coalesced via
    `seeds/coalesce.json`. `main.c` now reports stack overflow, other fatal
    exceptions, `abort()` and CRT exit, so no death is silent.
  - **Cache renames: fixed** (xboxrecomp `f1efce4`). `NtSetInformationFile`
    class 10 (FileRenameInformation) is implemented. XAPI passes drive-letter
    names (`z:\lng_us\x.ipk`) relative to RootDirectory `0xFFFFFFFD`
    (ObDosDevicesDirectory). Cached packs now become `.ipk`
    (`%LOCALAPPDATA%\xboxrecomp\Cache`).
  - **Thread-exit poll: fixed** (xboxrecomp `5430cca`).
    `ObReferenceObjectByHandle` returned a NULL object, so XAPI
    `GetExitCodeThread` (`sub_00298004`) read SignalState/ExitStatus from page 0
    and polled finished loader threads forever. Thread handles now get a
    per-handle guest KTHREAD stub that tracks the host thread.
  - **Current state (2026-10-11): input works; the game reaches the hub.**
    Intro movies → title → (Start) `gamestart_adx.adx` → `R0_opening.sfd`
    (or `title_movie_2a.sfd` once a save exists) → hub level `mgtu_ts` with
    its first "CHALLENGE" prompt. No unresolved ICALLs, no crash.
    - **Speed:** about 30 fps in the hub, vblank-bound (83% of main-thread
      samples in the frame-pacing wait at `0x00060475`); it was about 4.5 fps.
      Two fixes did it. First, the runtime's vblank now really reaches the
      title at 60 Hz: the cadence is on QPC, and the NV2A ack thread no
      longer wipes the pending bits; `XBOX_NV2A_VBLANK_MARK` emulates the
      write-1-to-clear ack. Second, `main.c` calls `timeBeginPeriod(1)`, so
      the GPU-idle shim's `Sleep(1)` no longer stalls D3D's fence wait for
      15.6 ms.
    - **Rendering:** without `RECOMP_PB_EXEC` nothing is drawn (GPU-idle
      shim). With it, the title, the attract stage and the hub render
      textured in the FB window and dumps. With the executor the hub runs
      at ~17 fps (2026-10-12, executed fences); the target is 30. See
      `notes/rendering-options.md`
      and the running log `notes/rendering-log.md`. The hub floor's
      stair-step bands are fixed: the floor reflection renders into
      *swizzled* surfaces, which the executor now writes swizzled
      (xboxrecomp `54869bf`). It also culls back faces now (`cda813f`).
      With PB_EXEC the hub runs at about 12 fps and the title at about 60.
      Rasterisation is deferred across draw calls onto a 16-thread pool
      (`c40d37a`, `554bea6`). Before that it was about 4.5 fps, with main 92%
      in D3D's pushbuffer-space wait (`sub_002E7F30`). The raster workers set
      the frame rate now. Numbers are in `notes/rendering-log.md`.
      Under PB_EXEC, Start (not A) leaves the CHALLENGE "GAME PAUSED"
      screen. Use `RECOMP_PAD_LIVE=<file>` and append `start:500` /
      `a:600`, because 200 ms presses can fall between 4 fps polls.
    - **Pipeline:** `--extra-sections` as listed above. Seeds
      (`blinx2-recomp/seeds/seed_functions.json`, 43 entries) cover the XPP
      USB callbacks, the opening-movie, attract and hub ICALL targets, and
      `0x000EF540` (the stage 01-01 mission-load completion callback). Any
      new `[ICALL] Failed to resolve` that is a gap-start gets seeded, and
      the pipeline is rerun.
    - A save (`game_files/UDATA/4d530065/13C91777168C/`) is created once the
      hub is reached; it changes the post-title flow.
  - **Dirty-disc error after the title: fixed (2026-10-11).** It was not I/O.
    The contiguous arena (64 MB bump allocator) ran out right after the
    `stg0101` cache copy (`[CONTIG] arena exhausted`, 66,973,696 bytes used),
    deterministically and with or without `RECOMP_PB_EXEC`. `main.c` now
    defaults `RECOMP_HEAP_RECLAIM=1`. The stage cache copies then finish
    (`.tmp` → `.ipk` renames OK) and the attract demo
    (`demoplay\r01s01demo.dat`) plays.
  - **Rendering with `RECOMP_PB_EXEC=1 RECOMP_FB_WINDOW=1`:** the Sofdec logo,
    the textured title screen and the textured 3D stage 01-01 all appear in the
    FB window/BMP dumps (`RECOMP_FB_DUMP=fb_`).
  - **Input works (2026-10-11).** Run with `RECOMP_USB=1` (plus
    `RECOMP_PAD_PRESS=0x10` or `RECOMP_PAD_SCRIPT` when there's no host pad).
    Start skips the logo movies and leaves the title (`gamestart_adx.adx` →
    `R0_opening.sfd` → hub level `mgtu_ts`). It took three fixes:
    - `main.c` calls `xbox_OhciInit()` and routes the OHCI apertures through
      the VEH.
    - **Memory layout (2026-10-11, xboxrecomp `2009a1c`).**
      - The contiguous window is 128 MB.
      - The arena numbers from physical 0x1000 and fills below 64 MB first.
        Above 64 MB is overflow only, logged as `[CONTIG] below-64 MB arena
        full`.
      - `MmGetPhysicalAddress` tags every non-window VA with
        `XBOX_PHYS_RAM_TAG` (0x40000000), so an untagged number is always
        arena memory.
      - The NV2A executor, APU and OHCI strip the tag.
      - Opt-out: `RECOMP_CONTIG_LEGACY=1` (64 MB, no tag).

      History: an arena *above* the image (top `0x0303AC20`) left ~16 MB below
      64 MB. The title needs ~26 MB, and data past 64 MB made it skip every
      actor model (player, enemies) and the attract sky. The original
      overlapping arena (no tag) made OHCI read its control ED out of the
      image.
    - `xbox_ContiguousOwnsPhys` includes physical page 0. XAPI's USB stack
      carves its pool from that page (`0x80001000` minus what is left), so
      XInput handles and report buffers sit at `0x80000xxx`. Without this the
      reports went to low RAM and the buttons stayed 0.

    The seeded XPP callbacks (`0x0036BA63`, `0x0036AFFE`, …) complete
    enumeration. `RECOMP_XINPUT_TRACE=1` logs XInputGetState
    (`sub_00368457`) and XGetDeviceChanges (`sub_00367F0E`). It logs only on
    change or every 32nd call, and the game polls once per frame at about
    5.5 fps. `MmAllocateContiguousMemoryEx` from XPP asks for highest
    `0x00FFFFFF` and gets `0x03DA0000`: logged as `[CONTIG] ... above the
    caller's highest`, harmless so far.
  - Diagnostics: `RECOMP_WATCHDOG_SECS`, `[CS]` contention backtraces, kernel
    ordinal counts, `RECOMP_YIELD_TRACE=1` (the `[YIELD]` sampler, now
    env-gated), `RECOMP_SAMPLE_MS=<n>` (main-thread host-RIP sampler in
    `main.c`). The game now links with `/DEBUG`, so `[CRASH]` dumps print a
    named native stack plus host thread id and `g_fs_base`.
- **Collision octree pools are fixed and unchecked in the game.** The
  builder (`sub_001642A0`) uses 8000 triangles at `0xC21EA8`, 2000 nodes at
  `0xCAE8A8` and 60000 links at `0xBACB98`, back to back with no bounds
  check (node 2000 *is* the node counter `0xCC9E30`). Stage 01-01 already
  uses 58% of the nodes and 77% of the links with valid input. An overflow
  corrupts the counter, and `sub_001645A0` then recurses into garbage
  (one-off crash, 2026-10-12). `recomp_manual.c` now guards the split
  (blinx2-recomp `0e5cff1`, P5): a node whose children or links would not
  fit stays a leaf, logged once as `[OCTREE] pool full`. This needs
  `--exclude-manual` (emits `sub_001645A0_gen`). `RECOMP_OCTREE_WATCH=1`
  prints each build's peaks. The real Xbox presumably fits the same data;
  the SAT test's float precision follows D3D's PC=24 as on hardware.
- **Stage 01-01 freeze (fps 0, sound repeating, around the time
  controls): fixed** (xboxrecomp `9d895c0`, audio worker). The DPC that
  DSOUND's APU ISR queues used to run on the timer thread's next tick, up to
  10 ms later. If the game restarted a voice in that gap, the ISR put it on
  the retire list (`ctx+0x4A0`) twice, linked to itself. The DPC
  `0x334BDF` / `sub_003346BE` then looped forever. `apu_deliver_irq` now
  runs that DPC right after the ISR. `RECOMP_APU_DPC_INLINE=0` restores the
  old behaviour. Diagnostics: `RECOMP_APU_TRAP_TRACE`, `[DPCSPIN]`, the
  `[DPC]` host stack on a dispatch-lock timeout, `[DSAPU]`/`[DSTIMER]` dumps.
- The `blinx2_0NN.rec` scan (000–359, each opened twice) is **not** a
  blocker, but it is slow: the sampler shows the main thread ~100% in
  `ZwWriteFile` under stderr `fprintf`, so its 4–15 min length tracks how fast
  stderr is drained, not guest compute. Per `assets/CATALOG.md` the Z: cache
  slots are all zero, and `media\dds\.dds` is an empty texture name (no
  missing asset). The XBE also references `media\Textures\Waterfog.xpr`,
  which exists in no archive and not on the disc.
- `SRCADV`/`SRCED`/`SRCAC` are x86 code paired with `DATADV`/`DATED` data.
  There is **no** VM bytecode in the `.ipk` archives (`assets/CATALOG.md`).
  8 remaining unresolved stubs are in SRCADV.
- `blinx2-recomp/CMakeLists.txt` also carries a local `RECOMP_ABI_CHECK`
  diagnostic (checks every direct call; its log stops after ~32 entries).

## Agent orchestration notes

- The root repo is registered as AO project `blinx2project`. AO worktrees of
  it get **empty submodule dirs**, and both submodules carry uncommitted local
  fixes, so a worktree can neither build nor see the current code. Until those
  fixes are committed and pushed in the submodules, agents must work in
  `E:\Blinx2project` directly (and coordinate edits to shared files such as
  this one).
- OpenCode session habit: it pauses for approval (esp. first file access).
  For overnight runs, prefer a harness/daemon with auto-approve, or Claude
  Code subagents (which do not prompt for permission to read project files).
