#!/bin/sh
# Regenerate the UFO sources from the ttf fonts.
#
# extractufo refuses to overwrite an existing UFO, so each font is extracted
# into a temporary directory and then synced into place. rsync --checksum only
# rewrites files whose content changed and deletes files that no longer exist,
# so unchanged glyphs keep their files (and their git index stat info) intact.
set -eu

fonts="BabelStoneHanBasic.ttf BabelStoneHanExtra.ttf BabelStoneHanPUA.ttf"

for name in $fonts
do
    if [ ! -f "$name" ]; then
        echo "error: $name not found" >&2
        exit 1
    fi
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

# Extract all fonts in parallel; extractufo writes FONT_FILE.ufo next to its input.
pids=""
for name in $fonts
do
    ln -s "$PWD/$name" "$tmp/$name"
    extractufo "$tmp/$name" &
    pids="$pids $!"
done

status=0
for pid in $pids
do
    wait "$pid" || status=1
done
if [ "$status" -ne 0 ]; then
    echo "error: extraction failed, existing UFOs left untouched" >&2
    exit 1
fi

# Sync only after every extraction succeeded, so a failure never leaves a
# half-updated or wiped UFO behind.
for name in $fonts
do
    rsync --recursive --checksum --delete "$tmp/$name.ufo/" "$name.ufo/"
done
