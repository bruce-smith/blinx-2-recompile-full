# Blinx 2 asset extraction

To reproduce:

1. Clone `https://codeberg.org/KeybadeBlox/blipks` (commit `8a0d684`) into
   `tools\blipks`.
2. Build it with `scripts\build_blipks.bat`. This compiles
   `blipks-unpack.cpp unlzss.cpp` and `blipks-pack.cpp lzss.cpp` with the
   VS 2022 x64 `cl /std:c++17 /O2 /EHsc` and writes `tools\blipks\bin\`.
3. Run `sh scripts/extract_all.sh` from Git Bash (~75 s). It runs
   `blipks-unpack.exe E:/Blinx2project/game_files/<name>.ipk specs/<name>.spec.txt`
   from inside `extracted\<name>\` for each of the 8 `.ipk`s.
   - Use forward slashes in the input path.
   - The `.iph` files are just copies of each `.ipk`'s header and aren't
     needed.
4. Check the result with
   `py -3 -I scripts/verify_ipk.py E:/Blinx2project/game_files E:/Blinx2project/assets/extracted logs/verify.json`.
   Expect `missing=0 badsize=0`. The 85 `media` "conflicts" are duplicates
   stored with different compression; their contents were confirmed
   identical.
5. Optionally, re-pack an archive with `blipks-pack.exe specs/<name>.spec.txt`
   from a copy of its extracted tree. It should `cmp` identical to the
   original.

`extracted/` is copyrighted game data (~1.6 GiB) and must never be
committed. See `CATALOG.md` for what's inside.
