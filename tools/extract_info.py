#!/usr/bin/env python3
"""Extract everything except the glyphs layer from a TrueType font into a UFO.

Usage: python3 tools/extract_info.py <font.ttf> <out.ufo>

This is extractufo (ufo-extractor) with its glyph steps removed: fontinfo.plist,
lib.plist (glyph order, Unicode variation sequences and the font-wide TrueType
programs), features.fea, kerning.plist and groups.plist come out exactly as
extractufo writes them. The glyphs layer is written by tools/ttf2ufo, which
must be run on the same font; <out.ufo>/glyphs is left empty here.
"""
import sys

from extractor.formats.opentype import (
    TRUETYPE_INSTRUCTIONS_KEY,
    extractControlValues,
    extractFontProgram,
    extractGlyphOrder,
    extractMaxpValues,
    extractOpenTypeFeatures,
    extractOpenTypeInfo,
    extractOpenTypeKerning,
    extractPreProgram,
    extractUnicodeVariationSequences,
)
from fontTools.ttLib import TTFont
from ufoLib2 import Font

# GPOS lookup types extractor turns into glyph anchors, which ttf2ufo does not write
ANCHOR_LOOKUP_TYPES = {4, 5, 6}


def gpos_has_anchors(source):
    if "GPOS" not in source:
        return False
    for lookup in source["GPOS"].table.LookupList.Lookup:
        lookup_type = lookup.LookupType
        if lookup_type == 9:  # extension
            lookup_type = lookup.SubTable[0].ExtensionLookupType
        if lookup_type in ANCHOR_LOOKUP_TYPES:
            return True
    return False


def main(font_path, ufo_path):
    source = TTFont(font_path)
    if gpos_has_anchors(source):
        sys.exit(f"{font_path}: GPOS mark attachment (glyph anchors) is not supported")
    ufo = Font()

    # The same steps as extractor.formats.opentype.extractFontFromOpenType,
    # minus extractOpenTypeGlyphs, extractGlyphPrograms and extractAnchors.
    extractOpenTypeInfo(source, ufo)
    extractUnicodeVariationSequences(source, ufo)
    extractGlyphOrder(source, ufo)
    kerning, groups = extractOpenTypeKerning(source, ufo)
    ufo.groups.update(groups)
    ufo.kerning.clear()
    ufo.kerning.update(kerning)
    ufo.features.text = extractOpenTypeFeatures(source)
    if "glyf" in source:
        lib = ufo.lib[TRUETYPE_INSTRUCTIONS_KEY] = {
            "formatVersion": "1",
            "maxFunctionDefs": 0,
            "maxInstructionDefs": 0,
            "maxStackElements": 0,
            "maxStorage": 0,
            "maxTwilightPoints": 0,
            "maxZones": 0,
        }
        extractControlValues(source, lib)
        extractFontProgram(source, lib)
        extractMaxpValues(source, lib)
        extractPreProgram(source, lib)
    source.close()

    ufo.save(ufo_path, structure="package")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
