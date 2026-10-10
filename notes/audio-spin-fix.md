# Blinx 2 boot: audio-queue lock spin — root cause and fix (2026-10-09)

## Root cause

`bridge_PsCreateSystemThreadEx` (xboxrecomp `src/kernel/kernel_bridge.c`)
ignored the `CreateSuspended` argument (`STACK_ARG(7)`) and always started the
host thread immediately.

Blinx 2's audio init `sub_002A1CD0` → `sub_002A1BE0` creates its three audio
threads through `_beginthreadex` → XAPI `CreateThread` (`sub_0029817F`,
which passes `CreateSuspended = (flags >> 2) & 1`) with `CREATE_SUSPENDED`
(flags = 4):

| thread routine   | handle slot  | role                                     |
|------------------|--------------|------------------------------------------|
| `sub_002A1B20`   | `0xF4A17C`   | audio service loop, resumes `0xF4A140`   |
| `sub_002A1BA0`   | `0xF4A190`   | second service loop                      |
| `sub_002A17B0`   | `0xF4A140`   | audio worker: does work, then **suspends itself** via `SuspendThread([0xF4A140])` |

The game stores each handle only after `CreateThread` returns, runs setup
`sub_002A1A10`, and then resumes all three (`0x002A1DCC..0x002A1DEF`). Because
the threads were already running, `sub_002A17B0` called
`SuspendThread(0)` while the handle slot was still 0. That fails, so instead of
parking it looped hot, and `sub_002A1B20` hammered `ResumeThread` on the same
slot. All three contended on the game_audio lock `0x00F4A160`. This is the
"audio-queue spin". It is **not** an AC97/APU drain problem.

## Evidence

- `dbg_wd.err` (pre-fix): `ordinal 231 NtSuspendThread x675621` and
  `ordinal 301 RtlNtStatusToDosError x675641` from the 4th thread's stack
  (`esp=0x0169AF54`), i.e. every suspend failed. Resume x937k from thread #2
  (`esp=0x01598F58`) also failed.
- Watchdog dump: main was inside `_beginthreadex` for `sub_002A17B0`
  (`edi=002A17B0`, flags `4` on the guest stack at `0x00F7D31C`, fake handle
  `BEEF0001` still in the out-slot).
- Generated code: `sub_002A1BE0` (`recomp_0023.c` ~22200) pushes flags `4`
  for all three creates. `sub_002A17B0` ends its loop with
  `call 0x00297F3D` (SuspendThread wrapper) on `[0xF4A140]`.

## Fix

`xboxrecomp/src/kernel/kernel_bridge.c`:
- `bridge_PsCreateSystemThreadEx` reads `CreateSuspended` and passes it to
  `bridge_spawn_thread(..., suspended)`, which creates the host thread with
  `CREATE_SUSPENDED`. The title's own `NtResumeThread` on the handle token
  releases it. The log line now shows `(suspended)`.
- `bridge_PsCreateSystemThread` (ordinal 254, which has no CreateSuspended arg)
  passes 0.
- The `[YIELD]` diagnostic in `bridge_NtYieldExecution` is now gated behind
  `RECOMP_YIELD_TRACE=1`.

### Verified (`build/Release/susp2.err`)
- All three threads log `(suspended)`.
- 2 minutes after audio init: no `RtlNtStatusToDosError` (it had been x675k),
  NtSuspendThread 5.3k vs NtResumeThread 13.6k, NtYieldExecution 13.6k (was
  ~1B over a run). `[CS]` waits on `0x00F4A160` and `0x00339ADC` all end in
  "acquired".

## Next blocker #1 (solved with an env switch): DirectSound DSP doorbell

With the spin gone, main deadlocked inside DirectSound: `sub_0033439F` →
`sub_003341BE` holds the DSOUND global lock `0x00339ADC` (taken at
`0x003321F8`), writes command `3` to `[ebx]` with `ebx = scratch + 0x810`, and
spins at `loc_00334325` (`cmp [ebx],0 / jne`) waiting for the GP DSP to clear
it. The GP DSP is a passthrough stub, so the word never clears. This is the same
pattern `xbox_memory_layout.c` documents for DDS9/Wreckless. The watchdog regs
gave `ebx = 0x803D0810`. The address is stable across runs.

Work-around: `RECOMP_DSP_ACK=0x803D0810` (the timer tick zeroes the word).
`blinx2-recomp/src/main.c` now sets this by default unless the variable is
already set. Verified: boot passes DirectSound init. This is a handshake ack,
not a DSP: whatever results DirectSound reads back from the GP stay wrong
(see the ponytail note in `xboxrecomp/src/apu/apu_dsp.c`).

## Current blocker: main-thread fault in SetLastError (TLS base 0)

Deterministic, about 150–260 s into boot (after DirectSound init, during the
first post-audio file activity):

```
[CRASH] Access violation ... fault addr=... (read)   Xbox VA of fault: 0xFFFFFF6C
  in sub_00299449+0x90            (XAPI SetLastError)
  Xbox regs: eax=0xFFFFFFDB ecx=0 esp=0x00FEFEC0
  host thread <main>, g_fs_base=0x00004000
  Native stack: sub_00299449 <- sub_001B8240+0x4DF <- sub_0005F960+0x5FC4
                <- sub_0029A166+0x381   (title main entry)
  guest stack: [esp+0] 0x00298C6E (XAPI CreateFile, the 0xB7
                ERROR_ALREADY_EXISTS path) <- 0x001B82C6 (sub_001B8240)
```

- `SetLastError` is `[[fs:[4] + _tls_index*4] + 8] = err` with
  `_tls_index = -37`. `ecx = fs:[4]` read **0**, though loader init set it to
  `0x00770094` (log: `TLS: 148-byte block at 0x00770000, fs:[4] =
  0x00770094`). Something zeroed the main TIB's `+4` (guest VA `0x4004`)
  after init. It could be the first `SetLastError` of the run (CreateFile only
  calls it on the ALREADY_EXISTS path), so earlier calls do not prove it was
  ever intact at this point.
- The host thread is the main thread (same id as the `[CS]` waiter whose
  guest backtrace sits at `0x00F7D354`), yet guest `esp = 0x00FEFEC0` lies
  above the main stack top `0x00F7FFF0`, in the image's `.data` BSS. Main's
  esp has drifted or been reloaded by about +0x72000. Guest code never writes
  `fs:[4]` directly (checked: no `MEM32(XBOX_FS_BASE + 4) =` in gen), and the
  host call chain is a plain, shallow one (no longjmp/EH continuation).
- `RECOMP_WATCH=0x4004` cannot arm: guest page `0x4000` is outside the
  runtime's watchable windows ("not in a mapped window").

Leads, cheapest first:
1. Log `MEM32(0x4004)` and `g_esp` in the kernel-call path (e.g. on every
   NtCreateFile from the main thread) to bracket when each goes bad, then bisect
   with the `[KERNEL] #N ... ret=` log (`RECOMP_KERNEL_LOG_BUDGET`).
2. Suspect lifted-frame bugs in the aligned-frame `sub_0005F960`
   (`push ebp; mov ebp,esp; and esp,~7; sub esp,0x38; ... esp = ebp` on an
   early-exit path). A wrong `ebp` there would explain both symptoms if `esp`
   then lands in BSS and later pushes overwrite whatever lives there.
3. Make `RECOMP_WATCH` accept the TIB page so the write that zeroes `0x4004`
   names itself.

## How to verify

```powershell
cd E:\Blinx2project\blinx2-recomp\build\Release
$env:RECOMP_AC97_READY="1"; $env:RECOMP_WATCHDOG_SECS="900"
.\blinx_2_recomp.exe 2> boot.err      # RECOMP_DSP_ACK now defaults in main.c
# expect: "DSP ack: 1 command word(s)", PsCreateSystemThreadEx #2..#4
# "(suspended)", no ordinal 301 storm, then the SetLastError [CRASH] above
```

Diagnostics added this session:
- `RECOMP_YIELD_TRACE=1`: first 8 `NtYieldExecution` call sites.
- `RECOMP_SAMPLE_MS=<n>`: main-thread host-RIP sampler. It reports self and
  inclusive top-30 every 30 s. It interleaves with the rest of stderr and is
  heavy on output, so turn it off when you need a clean crash dump.

## Other findings

- The `.rec` scan's slowness is **stderr I/O bound**, not guest compute: a
  host-RIP sampler (`RECOMP_SAMPLE_MS=20`, new in `blinx2-recomp/src/main.c`)
  put 99.9% of main-thread samples in `ZwWriteFile` under
  `fprintf`/`fputs`. Its duration varies run to run (4–15 min) with how fast the
  redirected stderr is drained.
- `blinx2-recomp` now links with `/DEBUG` (public-symbol PDB, relink only), so
  crash dumps and the sampler name `sub_XXXXXXXX` frames. The VEH native-stack
  printer used to filter on the non-ASLR base `0x14xxxxxxx` and never printed a
  frame. It now unwinds from the fault context and prints the host thread id
  and `g_fs_base`.

## Files changed (local only, uncommitted)

- `xboxrecomp/src/kernel/kernel_bridge.c` — CreateSuspended fix and the
  `[YIELD]` env-gate
- `blinx2-recomp/src/main.c` — `RECOMP_SAMPLE_MS` sampler, VEH native-stack
  fix, default `RECOMP_DSP_ACK=0x803D0810`
- `blinx2-recomp/CMakeLists.txt` — `/DEBUG` link option (the pre-existing
  `RECOMP_ABI_CHECK` diagnostic left as it was)

---

# Follow-up (2026-10-09 late): SetLastError AV — root cause and fix

## Root cause: runtime memory layout overlapped the image

The runtime placed its private region at fixed VAs that assume the image
ends below 0x00700000:

| runtime block                         | old VA                    |
|---------------------------------------|---------------------------|
| RW data / fake KTHREAD / PRCB / TLS   | 0x00700000 – 0x00770200   |
| kernel data exports                   | 0x00740000                |
| main stack (8 MB)                     | 0x00780000 – 0x00F80000   |
| bump heap (zero-fills each block)     | 0x00F80000 – 0x04000000   |

Blinx 2's image ends at **0x0303AC20** (base + SizeOfImage). `.data` alone
runs 0x003E14C0–0x0103DB40 (≈12 MB of BSS), and 64 sections are loaded up to
0x02C68B44. So:
- the main stack and the fake TLS/KTHREAD blocks lived inside the game's BSS;
- every heap block, including the game's CRT heap (heap #2,
  `NtAllocateVirtualMemory` 1 MB reserve → 0x00F81000) and thread stacks,
  sat on BSS or model sections and was zero-filled on top of them.

At the crash, the main thread's guest esp (0x00FEFEC0) was inside the CRT
heap block and `fs:[4]` (TLS base) read 0: stack, heap and game globals were
overwriting each other.

## Fix (xboxrecomp `src/kernel/xbox_memory_layout.[ch]`)
- `g_xbox_rt_base` (default 0x00700000) and `g_xbox_stack_size`
  (default 8 MB) are now runtime values. `XBOX_RT_VA(va)` rebases each
  historical address. `XBOX_STACK_BASE`, `XBOX_KERNEL_DATA_BASE` and the
  `FAKE_*` blocks go through it, and `XBOX_HEAP_BASE` follows the stack.
- In `xbox_MemoryLayoutInit`, if `base + SizeOfImage > 0x00700000`, the region
  moves to the next 64 KB boundary above the image and the main stack shrinks
  to 1 MB. Images that end below 0x00700000 get exactly the old layout.
- `g_heap_next` starts lazily at `XBOX_HEAP_BASE`, which is no longer a
  compile-time constant.

New layout for Blinx 2 (log): region 0x03040000, stack 0x030C0000–0x031C0000
(ESP 0x031BFFF0), TLS block 0x030B0000 (`fs:[4]` = 0x030B0094), kernel data
0x03080000, heap 0x031C0000–0x04000000 (14 MB).

Sanity checks:
- **Stack size:** the title asks for 64 KB. That is the XBE PE stack commit
  `0x10000`, which its CreateThread wrapper `sub_0029817F` uses (via
  `MEM32(0x10130)`) when the size argument is 0, as it is for the main thread
  `sub_0029A166`. 1 MB is 16× that. Audio threads ask for 12 KB and get
  512 KB. Deepest main-thread esp seen earlier was ~12 KB below the top.
- **No other collisions:** the contiguous window (0x80000000, and the
  0xF0000000 alias of it) is a separate file mapping, not a view of low RAM, so
  `MmAllocateContiguousMemory` and the DSP doorbell (0x803D0810) cannot touch
  0x03040000–0x04000000. `NtAllocateVirtualMemory` with base 0 is served from
  the heap. With an explicit base it only commits inside existing regions.

## Verified (`build/Release/reloc.err`)
No crash in 1200 s (it was deterministic at 150–260 s). Main thread alive at
the watchdog: 502 M icalls, guest esp 0x031BC358 (inside the new stack),
working in the file/texture loader (`sub_001B8388`/`001B8410`/`001B8860`
frames, called from `sub_00036948`).

## Next blocker (to investigate)
- **Heap pressure:** 14.4 of 14.9 MB used after audio init (the game took
  2 MB and then 4 MB blocks). The next big allocation may fail. If so, give
  the region back RAM: the runtime-private 512 KB plus the 1 MB stack are the
  only fixed costs above the image, so the real limit is 64 MB − image.
  Check whether `xbox_SetTotalRam(128 MB)` (devkit) is acceptable for this
  title.
- **Texture probes:** after audio init the game probes 125×
  `media\dds\.dds` (empty name) and 55× a garbled
  `media\dds\s\com_tex_us.ipk<bytes>2x-.dds`. `com_tex_us` is a pack inside
  `lng_us.ipk` (assets/CATALOG.md), so a loose-file probe with a garbage name
  suggests the pack lookup returned nothing and a name buffer was read
  uninitialised. That is the first thing to trace from `sub_001B8240`.

## The "new spin" after the layout fix (watchdog at 1200 s), diagnosed

Kernel counts at 1200 s: ord 294/277 ≈155 M each, 238 ≈18 M, 224/231
≈9.7 M/4.9 M. By the `esp` in each `[KERNEL] summary` line:

- **esp 0x037D…/0x0385…/0x038D… = the three audio service threads**
  (`sub_002A1B20`/`sub_002A1BA0`/`sub_002A17B0`, stacks in the relocated
  heap). Their loop by design is `while(!stop){ work; SwitchToThread();
  …; ResumeThread(audio) }` with the game_audio lock around the work, so they
  produce all of the 277/294/238/224/231 volume. This is the intended idle
  polling, now with correct suspend/resume, and not a hang. It does burn host
  CPU. A later optimisation could make `NtYieldExecution` `Sleep(0)`/`Sleep(1)`
  after N consecutive yields.
- **esp 0x031BC340/58 = main thread, not lock-bound.** Its latest calls
  alternate ord 190 `NtCreateFile` / 301 `RtlNtStatusToDosError`. It keeps
  failing loose-file opens in the texture loader:
  - `sub_000367D0(name, …)` (texture load by name): `sprintf(0xF2DF48,
    fmt@0x3D7E54 / 0x3D7E3C, root 0xB22DD8, dir, name)` → `sub_001B8830` →
    `sub_001B83B0` (opens `0xF2DD30`, with `_us`/`IPK`/`ipk` fallback variants)
    → `sub_001B8320` (bounded `CreateFile` retries).
  - Names arriving are empty (`media\dds\.dds`, 125× in the log) or garbage:
    `media\dds\s\com_tex_us.ipk` + `FF FF FF FF` + `2x-` (55×).
- **Trigger:** right after audio init, main reads the nested pack inside
  `lng_us.ipk` (offset 1,185,792, 1,425,408 bytes, `IPK1`, 253 records, first
  `media\dds\d_hikari_blue.dds`). On disk the data is correct, and the read
  returned the full length with the right magic. After it, every texture
  name the game resolves is empty or garbage. The garbage looks like an outer
  IPK record read at the wrong offset: the tail of a 64-byte path
  (`…s\com_tex_us.ipk`) running into the record's flag/size/offset dwords.
- The IPK archive opener `sub_001B8C60` was checked against raw x86 at its
  header copy and record-normalise loop (`0x001B8DDC–0x001B8E60`, stride
  0x50, `sub_001B8080` per record). The lift is faithful there.

**Next step:** find who calls `sub_000367D0` with the bad names and where
those names come from (the texture-name table built from the pack). Log the
name argument plus the caller retaddr at `sub_000367D0` entry (a small
`recomp_manual.c` wrapper, or `RECOMP_TRACE_ARGS` if the lifter supports it
for that function). Then check whether the table is filled from the nested
pack (LZSS-decompressed entries: a lifted bit-twiddling bug there would garble
exactly this kind of data), or from a model/stage blob.

## Texture-loader loop: snapshot findings (2026-10-10)

Taken with `RECOMP_MEMDUMP_SECS=120` (last snapshot ~1680 s in, deep in the
loop: 482 empty-name probes, 55 garbled).

- **The garbled name is a pack-request descriptor read as a texture name.**
  Pack load requests live in a 0x30-byte-stride array just below the archive
  slot table, starting at 0xDE1178. Each entry is `name[0x20]`; `+0x20`
  state (2); `+0x22` request id (the field `sub_00012F50` iterates via
  `esi = 0xDE119A`, calling `sub_001B8240`); `+0x24` pointer to the nested
  IPK header in the heap (0x032C1030 → `IPK1`); then 0x38C000 and the size
  0x15BEA6. Entry 0 holds `lng_us\com_tex_us.ipk`. The bad name pointer is
  **0xDE117D = descriptor + 5** (5 = `strlen("media")`, the root archive
  slot 0 at 0xDE1250).
- **The archive slots are fine.** Slot 0 (0xDE1250) is `media` with a live
  handle token (0x48000169) and its header buffer (0x031D9320, `IPK1`).
- **The texture-name tables are empty.** `sub_00037090(eax = {names,
  count})` walks 0x24-byte entries (`name[0x20]` + texture id) and calls
  `sub_000367D0` for each. Its callers in `sub_00172880` take the tables
  from a per-stage structure (`0xDD9158`/`0xDD9170` + index, `+0x90`). The
  whole 0xDD9140–0xDD91FC block is **zero** in the snapshot. With null or
  leftover table pointers, the walk reads whatever the pointer arithmetic
  lands on: the descriptor (garbled name), then zero-filled 0x24 strides
  (empty names → `media\dds\.dds`).
- Ruled out: the IPK opener `sub_001B8C60` header copy and per-record
  normalise (`sub_001B8080`, which takes the substring after the last
  backslash via strrchr `sub_002D53C0`) are faithfully lifted. `g_df` is
  thread-local, so no direction-flag race. The bytes read from disk are
  correct.

**Next:** find what should fill the per-stage texture tables at 0xDD9158+
(likely stage/model data in the `M*`/`DATED` sections fixed up at load, or
records parsed from the nested pack) and why it didn't run or ran on the
wrong data. Watch a table slot with `RECOMP_WATCH=0x00DD9170` (it is in
`.data` BSS, so it can be armed) to catch the writer, or confirm nothing
ever writes it.

## Loader bug: XBE section cap of 64 (fixed, xboxrecomp 74588d8)

Comparing the snapshot with the XBE: every section matched except the last
nine, which were 100% zero: MDLYP, MDLTT, MDLKF, MSHIP, MDLBEN, COMTNK,
MDLTNK (3 MB), MOTP0, $$XTIMAGE (0x02C68D60–0x0303AC20). The loader capped
`num_sections` at 64, and Blinx 2 has 73. The cap is now 1024 (the loop is
bounded by the file size). The log now reads `Loaded 73/73 sections`.

Effect on the texture loop: the empty/garbled probes remain (635/55), so
the stage texture tables are a separate defect. The boot now goes further and
crashes. Main faults reading guest 0xB2AC65AF in `sub_000364D0` (texture load),
via `sub_0005F960` → `sub_000605D0` → `sub_00037010` → `sub_00037090` →
`sub_000367D0` → `sub_000364D0`. That is presumably the loader acting on the
data it got for a bad name instead of failing the open.

## Texture-name flood: root cause and fix (2026-10-10)

**Root cause: an unresolved stub, not data.** A `--trace-functions` build
(regenerated into a temp dir; only `recomp_0001.c` differed, so the regen is
deterministic) showed guest esp going 0x031BE7A4 → 0x031BE32C across
`call sub_000364D0` (the DDS→D3D texture builder). It came back 0x478 bytes
low. `sub_000367D0` then popped garbage, and `sub_00037090`'s name pointer
(`edi`) came back 0. From then on it walked "names" at 0x24, 0x48, … (low
memory, zeros), which produced the `media\dds\.dds` flood. The leak was the
D3DX routine `sub_002F4EBC`. It was lifted as 36 bytes (prologue + `sub esp,
0x434`), and its two continuations `0x002F4EE0`/`0x002F4F06` were never
disassembled. They compiled to `g_esp += 4` stubs, so the function returned
with its frame still on the stack (`[ABI] … epilogue never ran, esp delta
-1084`).

**Why:** the gen had been produced from a disasm run that swept only DSOUND
as an extra section. The summary showed D3DX 3 functions, XGRPH 10, D3D 94.
There were 389 unresolved stubs.

**Fix (Approach C):** re-ran the whole pipeline with `--extra-sections
DSOUND,D3D,D3DX,XGRPH,XPP,SRCADV,SRCED,SRCAC` (DOLBY excluded: DSP56300
microcode, not x86):
- Functions 8,688 → 10,525: D3DX 459, XGRPH 735, D3D 295, XPP 230, SRCADV 261,
  SRCED 21, SRCAC 20; `.text` unchanged at 8,182. `tail_jump_alias` 1,301 (no
  flood).
- Stubs 389 → 204 (157 of them in `.text`).
- `sub_002F4EBC` is now 924 bytes / 314 insns.

**Verified:** full rebuild and a 1500 s boot. **0** empty-name probes and
**0** `com_tex_us` probes (were 635/55). No crash. ABI checker: 5 lines.

## Next blocker: boot stalls in newly lifted XGRPH code

The same run no longer reaches audio init (no `PsCreateSystemThreadEx`
#2–#4, heap at block #4). At the watchdog, main (esp 0x031BDE88) was in
compute: 58 k kernel calls in 1500 s, mostly CRT-heap CS enter/leave. Its
frames run through XGRPH `sub_0031D095` → `sub_0031CA69` →
`sub_0031E929` (recursive, about 8 KB deep) → the CRT heap (`0x0029D7BA` /
`0x0029D910`). These XGRPH routines were `g_esp += 4` stubs before and now
run for real. It is either a slow-but-progressing lift (e.g. the shader
assembler) or a loop that never terminates. Sampler run in progress.

## XGRPH "stall" verdict, doorbell moved, stderr bottleneck (2026-10-10)

- **XGRPH stall: slow-but-progressing, not a loop.** The sampler put the
  newly lifted XGRPH code at a few samples each. **~75% of the main thread
  was in `ZwWriteFile` under `fprintf`**, i.e. the unbuffered stderr log. On
  a bad run the log managed ~4 lines/s and the boot did not reach audio
  init in 25 min. blinx2-recomp `b6f555a` makes stderr fully buffered (1 MB,
  500 ms flusher; crash handler and watchdog already fflush). The `.rec`
  scan plus audio init now take ~1 min.
  `RECOMP_STDERR_UNBUFFERED=1` restores the old behaviour.
- **The DirectSound doorbell moved** (0x803D0810 → 0x80A20810) once D3D
  allocated contiguous memory for real, and the hang returned. It is now
  resolved at run time by a watcher thread following
  `[[[[[[g_pDS@0xEC4C0C]+0x4]+0x14]+0x8]+0x10]] + 0x810`. The chain was
  confirmed from the hang dump: the spinning frame's `this` 0x80A44134 sits
  at `[g_pDS+4]+0x14`. The `+0xC` path read off the call chain leads to an
  object with `[this+8] = 0`. Log: `[DSP] DirectSound doorbell at
  0x80A20810` / `command acknowledged`.

## Current blocker: D3D waits for the GPU (2026-10-10)

With the doorbell acked the boot passes DirectSound init and **starts
rendering**: the NV2A USER pushbuffer shows `PUT = GET = 0x2BB0`. At the
900 s watchdog main is in the game's frame code (`sub_0005F960` →
`sub_000604B0`) → D3D `sub_002E1060` → `sub_002E8420` →
`sub_002E8110(device->[0x2C], 2)`. That is D3D's pushbuffer-space/fence
wait. It compares a GPU progress value read through `[device+0x30]` and
blocks in `KeWaitForSingleObject`. Ordinal 159 had 364 M calls, so the wait
returns and is retried. The dump shows `PFIFO PUT=0 GET=0 REF=0`.
Suspect: the emulated NV2A never advances the value D3D polls
(reference counter / GET mirror), or never signals the event D3D waits on.

## GPU-idle shim, heap map, PSFD regen; current blocker: Sofdec movie (2026-10-10)

- **D3D GPU wait:** D3D's device (pointer at 0x2F1FB8) holds the CPU's next
  fence time at `+0x2C` and a pointer at `+0x30` to the GPU's completed time
  (written back by the GPU on hardware). Idle is `gpu + 2 == cpu`
  (`sub_002E7E80`). With its flag set it also spins until NV2A reg 0x400B10
  bits 2–6 equal `gpu << 2`. Nothing executes the pushbuffer by default
  (RECOMP_PB_EXEC off) and the aperture is plain RAM, so
  `sub_002E8110` waited forever (KeWaitForSingleObject ×364 M). Workaround in
  blinx2-recomp `f779577`: a watcher sets `gpu = cpu - 2` and echoes the
  register (`RECOMP_GPU_IDLE_SHIM=0` disables it). The runtime's own
  `xbox_Nv2aMirrorFence` copies values verbatim and cannot express the `-2`.
- **Heap exhaustion** at the movie start (14.9/14.9 MB): `xbox_SetMapSize(128
  MB)` gives a 78 MB heap while the title still sees 64 MB of RAM. The real
  overhead is the runtime's fixed 512 KB stack per guest thread (titles ask for
  12–64 KB). Worth fixing in the runtime later.
- **PSFD_I/B/P/00 are x86** (CRI Sofdec decoder, reached only via function
  pointers), not data. They are now in `--extra-sections`. Seeds added via
  `tools.seed_from_log` from a run log: `0x001B8BF0` (IPK loader thread) and
  `0x00366CBC`, `0x003674FA` (XPP ICALL targets that failed to resolve). The
  seed file is not tracked in git, so re-add these if it is lost. Result:
  10,549 functions, 204 stubs, no unresolved ICALLs at run time.
- **Current blocker:** the boot writes save metadata, caches `tank_tex.ipk`
  into Partition5, opens `movie\logo_mgs.sfd`, and reads its first 2 MB (two
  async 1 MB reads, MPEG-PS pack header `00 00 01 BA`). Then the movie stops
  pulling data and main idles in its top loop (watchdog at 900 s). Next:
  find what Sofdec waits on per frame: decode progress in PSFD (PSFD_I/PSFD_P
  still show 0 detected functions), a vblank/present-driven tick, or its
  audio (ADX) clock.

## Intro movies fixed: vblank counter (2026-10-10)

- **Cause:** the main loop's frame pacing, `sub_0005F960` @ 0x00060475:
  `while ((int)[0xAE7388] < target);`. The sampler had main 97.7% self in
  `sub_0005F960`, and a write watch on 0xAE7388 never fired. The counter is
  bumped only by the title's vblank callback **0x000604A0** (`mov eax,
  [0xAE7388]; inc eax; mov [0xAE7388], eax; ret`), registered via D3D
  `SetVerticalBlankCallback` (`sub_002E0D90`) and called from D3D's NV2A ISR
  (`KeConnectInterrupt` vector 3 → 0x002EA2E0). The runtime raises that
  interrupt only with `RECOMP_VBLANK` set, and the callback was never
  disassembled (only its address is passed). With `RECOMP_VBLANK=1` every
  call logged `[ICALL] Failed to resolve VA 0x000604A0`.
- **Fix (blinx2-recomp `ae52bde`):** `main.c` defaults `RECOMP_VBLANK=1`.
  `recomp_manual.c` implements the callback via `recomp_lookup_manual`.
  Ruled out: letting the `.sfd` open fail. With `game_files\movie`
  renamed, the game retries the open forever.
- **Then:** Sofdec called PSFD_I `0x0033A340` / PSFD_P `0x0033B040`
  (undetected), plus `0x002D0450`, and the run crashed on garbage pointers.
  These are seeded now, together with `0x000604A0`. `0x001B8DE6`, which
  `seed_from_log` proposed, was skipped: it is a return address inside
  `sub_001B8C60` and appeared only because of the corruption. Full seed list
  added on 2026-10-10: `0x001B8BF0`, `0x00366CBC`, `0x003674FA`,
  `0x002D0450`, `0x0033A340`, `0x0033B040`, `0x000604A0`. Regen: 10,553
  functions, 200 stubs.
- **Verified:** `logo_mgs.sfd` → `logo_artoon.sfd` → `blinx2_opening.sfd`
  all play. No unresolved ICALLs and no crash in 900 s. Next is the title-screen
  texture load (see AGENTS.md "Current blocker").
