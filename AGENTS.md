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
- The workspace root itself is **not** a git repo; only the two project
  subdirectories are.
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
py -3 -m tools.disasm       E:\Blinx2project\game_files\default.xbe --text-only --extra-sections DSOUND,D3D,D3DX,XGRPH,XPP,DOLBY,SRCADV --seed-functions tools/recomp/output/seed_functions.json   # ~50 s
py -3 -m tools.func_id      E:\Blinx2project\game_files\default.xbe -v                    # ~30 s
py -3 -m tools.abi_analysis E:\Blinx2project\game_files\default.xbe -v                    # ~1 min
py -3 -m tools.recomp       E:\Blinx2project\game_files\default.xbe --all --split 250 --gen-dir E:\Blinx2project\blinx2-recomp\src\recomp\gen   # ~15 min
```

- Skipping `abi_analysis` still builds, but every generated signature falls
  back to a guess (cdecl / 0 params).
- **`--extra-sections` is load-bearing, not optional.** `--text-only` skips
  every section but `.text`, and Blinx 2's real code also lives in the
  D3D/D3DX/XGRPH/DSOUND/XPP/DOLBY/SRCADV sections. Without them those calls
  compile to `g_esp += 4` stubs → guest stack corruption → deterministic
  crashes (2026-10-09: the boot crash at sub_002AA810 was exactly this).
  Adding DSOUND alone produced 320 real functions and fixed the crash; keep
  the full real-code list when regenerating. The MDL*/M*/G* blobs stay out
  (they are data; scanning them created 14,549 false functions).
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
- Output is ~35 `recomp_*.c` + `recomp_funcs.h` + `recomp_dispatch.c` +
  `recomp_types.h` (~23,753 functions, ~2.6 M lines after the 2026-10 data-ptr
  fix + DSOUND extra-section). `recomp_types.h` is written by the recompiler,
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
- **Current count:** 23,753 identified functions (2026-10-09, after the
  DSOUND `--extra-sections` fix). The 2026-10 data-ptr fix removed 14,549
  false functions; adding DSOUND brought back 320 real ones. ~2.6 M lines in
  ~35 files. `--text-only` is correct for this title: the model-blob sections
  (MDL*/M*/G*) are data.
- **Boot status (2026-10-09):** the old deterministic crash (~12 min, sound
  init at sub_002AA810 → sub_00333C88, esp corruption from DSOUND stubs) is
  **fixed**. Boot now runs 26+ min without crashing (17 billion kernel calls,
  was ~3M at crash). New blocker: an **audio-queue lock spin** at boot:
  - Threads #2/#3 = job workers (seeded `sub_002D702E`) endlessly running
    poll jobs: `sub_002A1B20`/`sub_002A1BA0` yield + critical-section ping-pong
  - Thread #1 (game main, spawned from `xbe_entry_point`) stuck in the audio
    queue `sub_002A7220`/`sub_002A7260`, contended on lock `0x00F4A160`
    (the game_audio object)
  - Kernel spin signature: ordinal 277 RtlEnterCriticalSection ×7.7B, 294
    RtlLeaveCriticalSection ×7.9B, 238 NtYieldExecution ×1B, 224/231
    Suspend/ResumeThread churn
  - Likely cause: APU/AC97 emulation (`RECOMP_AC97_READY=1`) never draining
    the DSOUND queue → producer/consumer livelock
  - Diagnostics that worked: `RECOMP_WATCHDOG_SECS=120` dump + `[CS]`
    contention backtraces (`xbox_guest_backtrace(10)` in
    `xbox_RtlEnterCriticalSection`) + kernel ordinal counts in the log
- The `blinx2_0NN.rec` scan (000–359, each opened twice) is **not** the
  blocker — the files exist in the game cache (~930 KB each) and load fine.
  The `ERROR_PATH_NOT_FOUND` in the log is only the `media\dds\.dds` probe.
- Game logic runs on a custom scripting VM in the `SRCADV`/`SRCED`/`SRCAC`
  XBE sections; the scripts themselves live in the `.ipk` archives
  (`notes/bytecode vm.txt` points at Nezogoku/ipk-extractor). 8 remaining
  unresolved stubs are in SRCADV — next disasm target if the audio spin is
  resolved first.
- **Diagnostic left in place:** `bridge_NtYieldExecution` in
  `xboxrecomp/src/kernel/kernel_bridge.c` logs the first 8 caller guest
  addresses (`[YIELD] guest retaddr=... esp=...`). It names the spin site.
  Remove it (or gate it behind an env var) once the audio spin is solved.

## Agent orchestration notes

- This workspace is a candidate for Agent Orchestrator (AO) multi-agent runs:
  two git repos (xboxrecomp, blinx2-recomp) with local edits; the workspace
  root is not a repo. `ao spawn` needs `--standalone` unless a project is
  registered at the repo level.
- OpenCode session habit: it pauses for approval (esp. first file access).
  For overnight runs, prefer a harness/daemon with auto-approve, or Claude
  Code subagents (which do not prompt for permission to read project files).
