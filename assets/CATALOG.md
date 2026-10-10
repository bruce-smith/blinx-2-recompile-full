# Blinx 2 — `.ipk` / `.iph` archive catalog

Generated 2026-10-09. Input: `E:\Blinx2project\game_files` (read-only, from
`Blinx 2.xiso`). Output: `E:\Blinx2project\assets\extracted\<archive>\`.
**Extracted data is copyrighted game content — never commit it.**

## TL;DR

- All 8 archives were extracted with **blipks**. Every entry was checked:
  0 missing files, 0 size mismatches, 0 extraction failures.
- **Round-trip proof of losslessness:** re-packing the extracted trees with
  `blipks-pack` reproduces `tank_tex.ipk`, `media.ipk` and
  `lng_us.ipk`/`.iph` **byte-for-byte**.
- An **`.iph` file is the header of its `.ipk`.** Each `.iph` is
  byte-identical to the first N bytes of its `.ipk`: the IPK1 header plus
  the file table. It holds no extra data, and the tools don't need it.
- The archives hold **textures, localized text-as-texture bundles, sound-effect
  banks, cameras/events, effects and a few small param tables**. They do
  **not** hold the 3D models, motions, stage geometry or game logic. Those
  are in `default.xbe` sections (`MDL*`, `M<nn>`, `G<n>`, `MOT*`, `DATADV`,
  `DATED`), as covered in the open questions.
- **I found no VM bytecode or script files.** The AGENTS.md claim that the
  scripts live in the `.ipk`s doesn't hold up. See "VM scripts" below.
- **Boot texture probe:** `media\dds\.dds` has an **empty basename**, so no
  file can satisfy it. No asset is missing for it. See "Recomp boot" below.

## Tool choice

Both candidates target Blinx 2 (not Blinx 1), and both handle IPK1 with
LZSS compression and nested `.ipk`s.

| tool | commit | verdict |
|---|---|---|
| **blipks** (KeybadeBlox, codeberg) | `8a0d684871b0a275a5ed91b37465536133e51c2b` (2024-05-21) | **Used.** Plain C++17 with no build system needed. It recurses into nested IPKs, handles the `media.ipk` → `Z:\media` quirk, and writes a spec file that `blipks-pack` rebuilds byte-identically. |
| ipk-extractor (Nezogoku, github) | `a7d6a17aa560a9e0399dcea6d94ca6131912603d` (2024-02-06) | Cloned to `tools/ipk-extractor`, **not built** (not needed). Its README says re-compression is not always 1:1, and its `specs/` notes hint at an unconfirmed "LZSS or ZLIB". |

No Python fallback extractor was needed. `scripts/verify_ipk.py` still
contains a standalone IPK1 table parser. Format reminder:

- Header (16 bytes): `"IPK1"`, alignment, count, size.
- Then N 80-byte records: `char path[64]`, compressed flag, stored size,
  offset, decompressed size.
- Nested-archive offsets are relative to the nested archive's own start.

### Exact commands

```bat
:: build (VS 2022 x64 cl; the VS "18" install has a broken vcvarsall)
cd /d E:\Blinx2project\assets\tools
git clone https://codeberg.org/KeybadeBlox/blipks
git clone https://github.com/Nezogoku/ipk-extractor
E:\Blinx2project\assets\scripts\build_blipks.bat
::   -> cl /std:c++17 /O2 /EHsc blipks-unpack.cpp unlzss.cpp  (and blipks-pack.cpp lzss.cpp)
::   -> tools\blipks\bin\blipks-unpack.exe, blipks-pack.exe
```

```sh
# extract (Git Bash; ~75 s for all 8). The cwd = output dir, because blipks
# writes into the current directory.
sh /e/Blinx2project/assets/scripts/extract_all.sh
#   per archive:  cd extracted/<name> && blipks-unpack.exe E:/Blinx2project/game_files/<name>.ipk E:/Blinx2project/assets/specs/<name>.spec.txt
# verify + stats (Python 3.12, isolated mode)
py -3 -I scripts/verify_ipk.py   E:/Blinx2project/game_files E:/Blinx2project/assets/extracted E:/Blinx2project/assets/logs/verify.json
py -3 -I scripts/catalog_stats.py E:/Blinx2project/assets/extracted E:/Blinx2project/assets/logs/files.json
py -3 -I scripts/overlap.py      E:/Blinx2project/assets/extracted
# round-trip check (in a scratch copy of extracted/<name>):  blipks-pack.exe E:/.../specs/<name>.spec.txt ; cmp <name>.ipk game_files/<name>.ipk
```

**Gotcha:** pass the `.ipk` path with **forward slashes**. blipks finds the
archive name by splitting on `/` only. With backslashes, `media.ipk` is not
recognized, and its top-level files lose their `media/` prefix.

### blipks semantics to keep in mind

- Nested `.ipk`s are **flattened**. Their contents are written to their own
  internal paths, and the nested `.ipk` file itself is not written. The
  nesting is recorded in `specs/<name>.spec.txt`; offsets and sizes are in
  `logs/verify.json` → `nested[]` if you need to carve a sub-archive out.
- The first writer of a path wins, and later duplicates are skipped. I
  checked every duplicate:
  - **lng_\***: 18,062 entries → 6,566 files. The 44 case-only duplicates
    have identical stored bytes.
  - **media**: 6,112 → 5,309. All 85 duplicates whose storage differed
    (`media.ipk` vs nested `uniform_tex.ipk`, one compressed and one not)
    were decompressed and compared: **byte-identical**.
- Paths keep the archive's casing (e.g. `arial_16.tga`), while the XBE asks
  for `Arial_16.tga`, `se_enemyTT.bin` vs on-disk `se_enemytt.bin`, and so
  on. Any host-side VFS must be **case-insensitive**.

## Per-archive summary

| archive | .ipk size | entries (incl. nested) | nested ipk | files out | compressed | extracted size | contents |
|---|---|---|---|---|---|---|---|
| `media.ipk` | 105.8 MiB | 6,112 | 26 | 5,309 | 3,862 | 101.9 MiB | global textures, SE banks, cameras, effects, stage texture packs |
| `lng_us.ipk` | 119.7 MiB | 18,062 | 66 | 6,566 | 6,081 | 243.2 MiB | US text-as-texture (`.mix`), localized UI `.dds`, movie events + a 2,630-file **subset of media** |
| `lng_fr/ge/it/jp/sp.ipk` | 119.8–122.9 MiB | 18,062 each | 66 each | 6,566 each | 6,081 each | 243.0–243.7 MiB | same layout as `lng_us`, `_fr`/`_ge`/… suffixed |
| `tank_tex.ipk` | 16.4 MiB | 693 | 0 | 693 | 431 | 16.3 MiB | tank/vehicle DXT textures, **no directory** in the path (archive root) |

All top-level archives use 2048-byte alignment; nested ones use 0. Total
extracted size is about 1.58 GiB.

### Archive relationships

- Each `lng_xx.ipk` = `edit_char/` (14) + `lng_xx/` (3,936 localized) +
  `media/` (2,616). The 2,630 non-localized files are **byte-identical to
  their `media.ipk` copies** and identical across all six languages. Only the
  `lng_xx/` subtree differs between languages, and 3,660–3,769 of its 3,936
  names map 1:1 to the `_us` set.
- `media.ipk/edit_char/*.edt` (45) is identical to the loose
  `game_files/edit_char/*.edt` on the disc.
- **Nested IPKs** (resolved by name; the XBE has `uniform_tex`,
  `plcom_tex`, `title_tex_xx`, `stg%02d%02d_tex_xx`,
  `stg%02d%02d_infotex_xx`, `stg%02d%02d_se`, `mgtu_t?_tex_xx`,
  `tginfo/tsinfo/vsinfo_tex_xx`, `tank_tex`, and `_xx` becomes the language):
  - `media.ipk` → `com_se`, `mgtu_tg_se`, `mgtu_ts_se`, `plcom_tex` (154),
    `uniform_tex` (644), and 21 × `stgRRSS_se`.
  - `lng_us.ipk` → `autosave_us`, `com_tex_us`, `garage/locker/model_shop/shop/theater_{tg,ts}_us`,
    `mgtu_{tg,ts}_{tex,infotex}_us`, `odekake_us`, 21 × `stgRRSS_tex_us` +
    21 × `stgRRSS_infotex_us`, `sys_tex_us`, `title_tex_us`,
    `{tg,ts}edit_tex_us`, `{tg,ts,vs}info_tex_us`, `vsmode_us`.
  - Stage IDs: r01s01/03/04, r02s01/03/04, r03s01/03/04, r04s01/03/04,
    r05s01/03/04, r06s01/04, r09s01/03, r11s01, r12s01.

### Directory breakdown (media.ipk)

| path | files | MiB | types |
|---|---|---|---|
| `media/dds` | 3,715 | 55.40 | `.dds` |
| `media/se` | 63 | 18.82 | `.bin` (XSSB sound banks) |
| `media/mix` | 32 | 17.77 | `.mix`, one per stage `rRRsSS.mix` |
| `media/tga` | 219 | 3.66 | `.tga` |
| `media/epm` (+`ev`,`r01`–`r05`,`r03ev`,`sibuki`) | 262 | ~3.5 | `.eff` 170, `.dds` 90, `.eft` 1, `Thumbs.db` 1 |
| `media/dds_iz` | 70 | 0.71 | `.dds` |
| `media/bumpdata` | 17 | 0.70 | `.bum` (`0.bum`–`16.bum`) |
| `media/mess_mix` / `mis_mix` | 49 / 3 | 0.66 / 0.02 | `.mix` |
| `media/icb` | 310 | 0.26 | `.icb` |
| `media/event` | 191 | 0.17 | `EVCAMST*.CAM` 117, `ST*.EVB` 74 |
| `media/Fonts` | 2 | 0.13 | `arial_16.abc`, `arial_16.tga` |
| `media/cam` | 331 | 0.09 | `cam*.cam` |
| `edit_char` | 45 | <0.01 | `.edt` |

### Directory breakdown (lng_us.ipk, localized part)

| path | files | MiB | types |
|---|---|---|---|
| `lng_us/mess_mix` | 1,478 | 96.86 | `.mix`, dialogue/message pages as textures |
| `lng_us/mvev` | 638 | 40.27 | `.dds`, movie/event subtitle frames |
| `lng_us/mgtu_mix` | 535 | 33.56 | `.mix`, mini-game/tutorial text |
| `lng_us/dds` | 956 | 32.57 | `.dds`, localized UI |
| `lng_us/messex_mix` | 68 | 4.52 | `.mix` |
| `lng_us/mis_mix` | 105 | 3.43 | `.mix`, mission text |
| `lng_us/bbsex` | 118 | 2.27 | `.dds`, `bbs_*_words*` (edit/word board) |
| `lng_us/event` | 38 | 0.04 | `movie_NNN_us.EVB` |

## Per-type summary (unique files: media + lng_us localized + tank_tex)

| ext | count | MiB | magic / format | identification |
|---|---|---|---|---|
| `.dds` | 6,280 | ~176 | `DDS ` | Standard DirectDraw Surface: DXT1 3,571 / DXT3 2,053 / DXT5 633 / uncompressed 16-bit 13 / 32-bit 10. Opens in any DDS viewer. High entropy is just DXT data; none are still compressed. |
| `.mix` | 2,270 | ~157 | `MIXF` | Texture bundle: `"MIXF"`, u32 0x20, u32 name-table end, u32 data offset (0x800), …, u32 count @0x1C, then `count × char[32]` texture names, then an **`XPR0`** Xbox packed resource at 0x800. All 2,306 checked (`media` plus all of `lng_us`) have `XPR0` there. Text and stage textures are drawn as XPR textures. |
| `.bin` (`media/se`) | 63 | 18.8 | `XSSB` (62); `dsp.bin` is different | Sound-effect banks. `XSSB` = Xbox DirectSound/XACT-era sound bank, format not yet decoded (no RIFF/WAVE inside). `dsp.bin` (15 KB, zero header) is most likely the DSP effect image (`%smedia\se\dsp.bin`), which the APU/AC97 emulation path may need. |
| `.tga` | 220 | 3.8 | `00 01 01 00` | TGA, colour-mapped (paletted). `arial_16.tga` is type 2 (truecolour). |
| `.icb` | 310 | 0.26 | `00 01 01 00` | Same paletted-TGA layout as `.tga` (icon bitmaps `%smedia\icb\%s.icb`: emblems, boots, …). |
| `.cam` | 448 | 0.12 | small int header | Camera paths: `cam%02d%02d_%03d.cam` (stage) and `EVCAMST%02d%02d_%03d.CAM` (event). |
| `.evb` | 112 | 0.17 | `01 00 00 00`, size, count, … | Event timelines `ST%02d%02d_%03d.EVB` and `lng_%s\event\movie_%03d_%s.EVB`. These are fixed-size records of ints + float positions/angles (e.g. 3.14159), **not bytecode**. |
| `.eff` | 170 | 0.42 | `00000000` | Particle/effect definitions (`%smedia\epm\%s`). Format undecoded. |
| `.eft` | 1 | <0.01 | `EFT ` | `epm/r04` effect table. |
| `.bum` | 17 | 0.70 | none | Bump/height data `media\BumpData\%d.bum`. |
| `.edt` | 45 | 0.06 | small ints | Character-edit model parameter lists `mdl_param_list_t{g,s}%03d.edt`. |
| `.abc` | 1 | <0.01 | `04000000` | Font glyph metrics for `Arial_16`. |
| `.db` | 1 | 0.03 | `D0CF11E0` | `Thumbs.db` (Windows Explorer cache). Junk shipped by the developers. |

**Nothing failed to extract and nothing looks still-compressed.** Every
decompressed size matches the table, and every file's magic matches its type.

### Loose disc files (not in IPKs, for completeness)

| dir | files | size | format |
|---|---|---|---|
| `movie/` | 64 `.sfd` + 37 `.adx` + 9 `.aix` | 2.1 GB | CRI Sofdec video (MPEG-PS `00 00 01 BA`), CRI ADX audio, CRI AIX (`AIXF`) multi-track audio |
| `adx/` | 68 `.adx` | 151 MB | CRI ADX BGM (`80 00`), loaded as `adx\%s.adx` |
| `voice/` | 243 `.adx` | 58 MB | CRI ADX voice, loaded as `voice\%s.adx` |
| `demoplay/` | 2 `.dat` | 312 KB | attract-mode input recordings (`r01s01demo.dat`, `r01s03demo.dat`) |
| `edit_char/` | 45 `.edt` | 57 KB | identical to `media.ipk/edit_char` |
| `UDATA/4d530065/` | `TitleImage.xbx`, `TitleMeta.xbx` | 13 KB | **save templates** (dashboard save icon + metadata). `TDATA` is empty. |

No `.xwb`/`.wav` or Xbox ADPCM files exist anywhere. Audio is CRI ADX/AIX
(BGM, voice, movies) plus XSSB banks (SFX).

## Notable files

### Recomp boot

- **`media\dds\.dds` probe.** The XBE builds texture paths with
  `"%s%s\%s.dds"` (and `"%smedia\dds\..."`). The boot log probe
  `\Device\CdRom0\media\dds\.dds` therefore comes from an **empty texture
  name**, so no file can satisfy it, and there is no loose `media\` dir on
  the real disc either.
  - Either the game is probing for an optional loose-file override (a
    dev-style fallback) before it reads from the IPK, or a name field is
    still empty because something upstream hasn't been initialized.
  - It is harmless as long as the IPK path is taken afterwards.
- **Textures the code names explicitly:**
  - `media/dds/sys_white.dds` and `media/dds/sys_black.dds`: present in
    `media.ipk` and every `lng_*`.
  - `media/Fonts/arial_16.{abc,tga}`.
  - `media/bumpdata/*.bum`.
  - `media\Textures\Waterfog.xpr`: **absent from every archive and from the
    disc**. It's a dead dev reference, or an optional file.
- **Sound banks the boot / audio init loads:** `media\se\se_system.bin`,
  `dsp.bin`, `se_sweeper*.bin`, `se_tomtom*.bin`, `se_vehicle.bin`,
  `se_gimmick_*.bin`, `se_infoevent.bin`, all in
  `extracted/media/media/se/`. These are relevant to the audio-queue
  livelock in AGENTS.md: if the emulated DSOUND/APU path never consumes
  these XSSB banks, that's a candidate starvation point.
- **`z:\blinx2_%03d.rec` + `blinx2data.bin`.** The XBE writes 360 cache
  slots to the Z: utility partition. In
  `%LOCALAPPDATA%\xboxrecomp\Cache` they are 929,792 bytes each and **all
  zero**: preallocated, never filled. The game probably copies nested IPKs
  from the DVD into these slots (the `media.ipk` → `Z:\media` convention
  that blipks documents). `blinx2data.bin` is not in any archive; the game
  creates it at runtime.
- The `.iph` headers are likely what the game reads to index each `.ipk`
  without reading 120 MB. If the recomp's file layer serves them verbatim
  from `game_files`, no change is needed.

### Modding

- **Text/UI translation:** `lng_xx/mess_mix`, `mgtu_mix`, `mis_mix` and
  `messex_mix` `.mix` files are XPR0 texture bundles. Text is pre-rendered
  as images, so translation means editing textures. `lng_xx/dds`,
  `lng_xx/bbsex` and `lng_xx/mvev` hold plain DDS.
- **Repacking:** run `blipks-pack specs/<name>.spec.txt` from inside an
  edited copy of `extracted/<name>`. It rebuilds both `.ipk` and `.iph`
  byte-identically when nothing has changed. Remember that `lng_xx` carries
  its own copy of 2,630 `media` files, so edit both copies.
- **Stage texture packs:** `media/mix/rRRsSS.mix` plus the nested
  `stgRRSS_tex_xx` and `uniform_tex`/`plcom_tex` archives.
- **Character-edit parameters:** `edit_char/mdl_param_list_*.edt`.

### VM scripts (SRCADV)

**No script or bytecode files exist in any IPK.** Every extension is
accounted for above, and the only record-structured candidates (`.evb`,
`.cam`, `.eff`, `.edt`) are plain float/int data tables. In the XBE:

- `SRCADV`, `SRCED` and `SRCAC` are **x86 code**. Their strings are
  instruction-byte noise, consistent with them yielding real functions in
  `disasm --extra-sections`.
- They are paired with **`DATADV`** (movie/event names such as
  `TS_prologue`, `LastBoss_ev_a` and `omake_01_swe`) and **`DATED`** (the
  staff credits, e.g. "Developed by Artoon").

This reads as linker section grouping per module (ADV = adventure/story
mode, ED = ending/credits, AC = ?), not a scripting VM. The "custom VM"
note in AGENTS.md and `notes/bytecode vm.txt` looks like speculation. I'd
treat SRCADV as ordinary game code.

## Open questions

1. **Models, motions and stage geometry are in the XBE**, not the IPKs:
   - `MDL*` sections: GIM, AO, GA, BS5, PL, EN, BK, RT, BN, BT, ST, TC, SK,
     OB, SR, NT, YP, TT, KF, BEN, MG, TNK.
   - `M11`–`M121` (per stage) and `G1`–`G5`.
   - `MOTPL`/`MOTP0` (motions), `MSHIP`, `COMTNK`, `GIMCOM`.

   Extracting and identifying those formats is a separate task, using the
   section table in `game_files/mygame_analysis.json`.
2. **Formats still undecoded:** XSSB sound banks (header `XSSB`, ver
   `0x20011217`?), `dsp.bin`, `.eff`/`.eft`, `.bum`, `.edt`, `.cam`/`.evb`
   record layouts, and the MIXF fields at 0x10–0x18. The XPR0 payloads need
   an XPR → DDS converter, and no off-the-shelf one has been tried yet.
3. **What fills `z:\blinx2_NNN.rec`?** Does the game copy nested IPKs into
   them on first boot? If so, the all-zero cache files in
   `%LOCALAPPDATA%\xboxrecomp\Cache` may mean that copy step never ran or
   failed silently in the recomp.
4. Why is the texture name empty in the `media\dds\.dds` probe? Set a
   breakpoint or log on the `"%s%s\%s.dds"` sprintf caller (string at XBE
   file offset `0x3c34c8`) to see which texture slot it is.
5. Nested-IPK carving: blipks doesn't write the nested `.ipk` blobs. If the
   recomp or a modder needs them standalone, carve from `logs/verify.json`
   (`nested[].base` / `size`).

## Files in this directory

- `tools/blipks/` (built, `bin/`) and `tools/ipk-extractor/`: upstream
  clones.
- `scripts/`: `build_blipks.bat`, `extract_all.sh`, `verify_ipk.py`,
  `catalog_stats.py`, `overlap.py`.
- `specs/<name>.spec.txt`: blipks archive specs (the input for repacking).
- `logs/<name>.log`: unpack logs. `logs/verify.json` holds the full entry
  tables, nested offsets and duplicate check; `logs/files.json` holds
  per-file ext/size/magic/entropy.
- `extracted/<name>/`: the data. **Do not commit.**
