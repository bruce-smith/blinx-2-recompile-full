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
py -3 -m tools.disasm       E:\Blinx2project\game_files\default.xbe --text-only --extra-sections DSOUND,D3D,D3DX,XGRPH,XPP,SRCADV,SRCED,SRCAC --seed-functions tools/recomp/output/seed_functions.json   # ~50 s
py -3 -m tools.func_id      E:\Blinx2project\game_files\default.xbe -v                    # ~30 s
py -3 -m tools.abi_analysis E:\Blinx2project\game_files\default.xbe -v                    # ~1 min
py -3 -m tools.recomp       E:\Blinx2project\game_files\default.xbe --all --split 250 --gen-dir E:\Blinx2project\blinx2-recomp\src\recomp\gen   # ~15 min
```

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
  - **PSFD_*** sections are data too.
  - **The MDL*/M*/G* blobs stay out** (they are data; scanning them created
    14,549 false functions).
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
  `recomp_stubs_unresolved.c` + `recomp_types.h` (10,525 functions, ~3.0 M
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

- `build\Release\blinx_2_recomp.exe`, launched **from `build\Release`** —
  `xbox_kernel.log` is opened with a relative path and lands in the current
  directory.
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
- **Current count:** 10,525 identified functions (2026-10-10, full
  extra-section list), with 204 unresolved stubs left, ~3.0 M lines in 43
  files. The earlier "23,753" figure did not match the disasm summary, which
  had reported 8,688 for the DSOUND-only run. The 2026-10 data-ptr fix removed
  14,549 false functions. `--text-only` is correct for this title: the
  model-blob sections (MDL*/M*/G*) are data.
- **Boot status (2026-10-10):** full write-up in
  `notes/audio-spin-fix.md`. Boot now gets past audio init, DirectSound init,
  the texture loader and the old SetLastError crash, and **starts rendering**
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
  - **Current blocker:** D3D waits for the GPU. Main is in the frame code →
    D3D `sub_002E1060` → `sub_002E8420` → `sub_002E8110` (pushbuffer/fence
    wait via `[device+0x30]`), retrying `KeWaitForSingleObject` (ordinal 159,
    364 M calls). The dump shows `PFIFO PUT=0 GET=0 REF=0`. Suspect the
    emulated NV2A never advances the progress value D3D polls, or never
    signals its event.
  - Diagnostics: `RECOMP_WATCHDOG_SECS`, `[CS]` contention backtraces, kernel
    ordinal counts, `RECOMP_YIELD_TRACE=1` (the `[YIELD]` sampler, now
    env-gated), `RECOMP_SAMPLE_MS=<n>` (main-thread host-RIP sampler in
    `main.c`). The game now links with `/DEBUG`, so `[CRASH]` dumps print a
    named native stack plus host thread id and `g_fs_base`.
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
