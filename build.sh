#!/bin/sh
# Regenerate the UFO sources from the ttf fonts.
#
# Uses ttf2ufo (https://crates.io/crates/ttf2ufo), whose output matches
# ufo-extractor's extractufo byte for byte. Install it with:
#   cargo install --locked ttf2ufo@0.1.0
#
# --update rewrites only files whose content changed and deletes files the font
# no longer produces, so unchanged glyphs keep their files (and their git index
# stat info). Each UFO is checked before anything is written, so a failure
# leaves it untouched.
set -eu

fonts="BabelStoneHanBasic.ttf BabelStoneHanExtra.ttf BabelStoneHanPUA.ttf"

if ! command -v ttf2ufo >/dev/null 2>&1; then
    echo "error: ttf2ufo not found; install it with: cargo install --locked ttf2ufo@0.1.0" >&2
    exit 1
fi

for name in $fonts
do
    if [ ! -f "$name" ]; then
        echo "error: $name not found" >&2
        exit 1
    fi
done

# ttf2ufo runs on all cores, so the fonts go one at a time.
for name in $fonts
do
    ttf2ufo --update "$name" "$name.ufo"
done
