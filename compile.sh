#!/bin/sh
# Compile the UFO sources back to TrueType fonts in build/.
#
# Usage: sh compile.sh [UFO ...]   (default: all three UFOs)
#
# The UFOs come from extractufo and keep the source fonts' TrueType outlines
# and hinting. Each glyph's hinting is stored with a hash of its outline, and
# ufo2ft drops the hinting if the compiled outline differs, so fontmake must
# not alter the contours:
#   --keep-direction         contours are already in TrueType direction
#   --ttf-curves keep-quad   curves are already quadratic; cu2qu would move
#                            each contour's start point
#   --keep-overlaps          overlap removal would rewrite the outlines
set -eu

if [ "$#" -eq 0 ]; then
    set -- BabelStoneHanBasic.ttf.ufo BabelStoneHanExtra.ttf.ufo BabelStoneHanPUA.ttf.ufo
fi

for ufo in "$@"
do
    if [ ! -d "$ufo" ]; then
        echo "error: $ufo not found" >&2
        exit 1
    fi
done

mkdir -p build

pids=""
for ufo in "$@"
do
    name=$(basename "$ufo" .ttf.ufo)
    fontmake -u "$ufo" -o ttf \
        --keep-direction --ttf-curves keep-quad --keep-overlaps \
        --output-path "build/$name.ttf" &
    pids="$pids $!"
done

status=0
for pid in $pids
do
    wait "$pid" || status=1
done
exit "$status"
