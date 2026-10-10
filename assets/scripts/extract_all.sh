#!/bin/sh
# Extract every .ipk under game_files into assets/extracted/<archive>/ with blipks-unpack.
# Input path must use forward slashes: blipks keys its media.ipk special case off the text after the last '/'.
set -u
GF=E:/Blinx2project/game_files
A=/e/Blinx2project/assets
UNPACK=$A/tools/blipks/bin/blipks-unpack.exe
mkdir -p "$A/extracted" "$A/specs" "$A/logs"
cd /e/Blinx2project/game_files
find . -iname '*.ipk' | sed 's#^\./##' | while read -r rel; do
  name=$(basename "$rel" .ipk)
  out="$A/extracted/$name"
  rm -rf "$out"; mkdir -p "$out"
  ( cd "$out" && "$UNPACK" "$GF/$rel" "E:/Blinx2project/assets/specs/$name.spec.txt" ) > "$A/logs/$name.log" 2>&1
  echo "$rel exit=$? files=$(find "$out" -type f | wc -l)"
done
