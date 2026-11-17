#!/bin/sh
# Regenerate the UFO sources from the ttf fonts.
#
# The output matches extractufo byte for byte, but is produced in two parts:
#   - tools/extract_info.py (ufo-extractor) writes everything except the glyphs
#     into a staging directory; those few files are then synced into place.
#   - tools/ttf2ufo (Rust) writes the glyphs layer straight into the UFO.
# Both only rewrite files whose content changed and delete files that no longer
# exist, so unchanged glyphs keep their files (and their git index stat info).
set -eu

fonts="BabelStoneHanBasic.ttf BabelStoneHanExtra.ttf BabelStoneHanPUA.ttf"

for name in $fonts
do
    if [ ! -f "$name" ]; then
        echo "error: $name not found" >&2
        exit 1
    fi
done

cargo build --quiet --release --manifest-path tools/ttf2ufo/Cargo.toml
ttf2ufo=tools/ttf2ufo/target/release/ttf2ufo

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

# Extract the non-glyph data first (in parallel), so a failure leaves the UFOs
# untouched.
pids=""
for name in $fonts
do
    python3 tools/extract_info.py "$name" "$tmp/$name.ufo" &
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

for name in $fonts
do
    # ttf2ufo renders every glyph before writing, so it fails before touching
    # the UFO; it runs on all cores, so the fonts go one at a time.
    "$ttf2ufo" "$name" "$name.ufo"
    rsync --recursive --checksum --delete --exclude /glyphs/ "$tmp/$name.ufo/" "$name.ufo/"
done
