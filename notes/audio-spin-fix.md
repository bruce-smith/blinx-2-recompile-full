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
