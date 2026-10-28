#!/usr/bin/env python3
"""Build Crooli Sans from the upstream Geist sources.

Crooli Sans keeps every Geist outline exactly as drawn. What changes is the
default character: a handful of Geist's own stylistic alternates are promoted
to the default forms, and the forms they replace move into the matching
stylistic set, so `ss02` etc. now switch back to the original Geist shapes.

The swap is done by renaming shapes, not by remapping characters, so each
shape keeps its own spacing, kerning, mark anchors and (in the variable fonts)
its own variations. Accented letters follow automatically.

Usage: python scripts/build.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.reorderGlyphs import reorderGlyphs
from fontTools.misc.timeTools import timestampNow

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources" / "geist"
FONTS = ROOT / "fonts"

FAMILY = "Crooli Sans"
PS_FAMILY = "CrooliSans"
VERSION = "1.000"
VENDOR = "CROO"
REPO = "https://github.com/xandertaylorx/crooli-sans"

# Geist stylistic sets that become Crooli's defaults, with the new label for
# the feature (it now switches back to the Geist form).
CHARACTER = {
    "ss02": "Double-storey a",  # default: single-storey a
    "ss04": "Classic R",        # default: diagonal-leg R
    "ss06": "Classic G",        # default: spurless G
    "ss08": "Square dots",      # default: round dots and punctuation
}

WEIGHTS = {
    "Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400, "Medium": 500,
    "SemiBold": 600, "Bold": 700, "ExtraBold": 800, "Black": 900,
}

COPYRIGHT = (
    "Copyright 2024 The Geist Project Authors (https://github.com/vercel/geist-font). "
    f"Copyright 2026 The Crooli Sans Project Authors ({REPO})."
)
DESIGNER = "Crooli; Geist by Basement.studio, Andrés Briganti, Mateo Zaragoza"
DESCRIPTION = (
    "Crooli Sans is the Crooli typeface: an open-source fork of Geist with a "
    "friendlier default character. Licensed under the SIL Open Font License 1.1."
)
# Name IDs that may still say "Geist" because they credit the upstream project.
CREDIT_IDS = {0, 9, 10}


# --- character swap -------------------------------------------------------------

def character_swaps(font: TTFont) -> dict[str, str]:
    """Pairs of glyph names to exchange, as a symmetric mapping.

    Applies the chosen stylistic sets in lookup order (as a shaper would with
    all of them on) to find the final form of every affected glyph.
    """
    gsub = font["GSUB"].table
    lookups = sorted({
        i
        for rec in gsub.FeatureList.FeatureRecord
        if rec.FeatureTag in CHARACTER
        for i in rec.Feature.LookupListIndex
    })
    steps = []
    for i in lookups:
        lookup = gsub.LookupList.Lookup[i]
        if lookup.LookupType != 1:
            raise SystemExit(f"Lookup {i} is not a single substitution; cannot promote it.")
        mapping = {}
        for sub in lookup.SubTable:
            mapping.update(sub.mapping)
        steps.append(mapping)

    # Start from the base glyphs only; intermediate forms (e.g. the ss06 G that
    # ss08 then gives a round dot) stay where they are.
    targets = {alt for mapping in steps for alt in mapping.values()}
    final = {}
    for glyph in set().union(*steps) - targets:
        out = glyph
        for mapping in steps:
            out = mapping.get(out, out)
        if out != glyph:
            final[glyph] = out

    swaps: dict[str, str] = {}
    for glyph, alt in final.items():
        if glyph in swaps or alt in swaps:
            raise SystemExit(f"Overlapping swap for {glyph} -> {alt}")
        swaps[glyph] = alt
        swaps[alt] = glyph
    return swaps


def rename_shapes(font: TTFont, swaps: dict[str, str]) -> None:
    """Exchange the shapes behind each glyph-name pair.

    cmap and GSUB keep pointing at the same names; everything that belongs to a
    shape (outline, advance, variations, kerning, anchors, glyph class) moves.
    """
    order = font.getGlyphOrder()
    swapped_order = [swaps.get(n, n) for n in order]

    # gvar decompiles lazily against glyf point counts; load it before glyf moves.
    if "gvar" in font:
        gvar = font["gvar"]
        gvar.variations = {n: gvar.variations[n] for n in order if n in gvar.variations}

    # Decompile the ID-based layout tables against the swapped glyph order, so
    # each shape's data comes back under its new name.
    for tag in ("GDEF", "GPOS", "HVAR"):
        if tag not in font:
            continue
        data = font[tag].compile(font)
        scratch = TTFont()
        scratch.setGlyphOrder(swapped_order)
        table = newTable(tag)
        table.decompile(data, scratch)
        font[tag] = table

    glyf = font["glyf"]
    moved = {}
    for name in order:
        glyph = glyf[name]
        if glyph.isComposite():
            for component in glyph.components:
                component.glyphName = swaps.get(component.glyphName, component.glyphName)
        moved[swaps.get(name, name)] = glyph
    glyf.glyphs = moved

    hmtx = font["hmtx"]
    hmtx.metrics = {swaps.get(n, n): m for n, m in hmtx.metrics.items()}

    if "gvar" in font:
        gvar.variations = {swaps.get(n, n): v for n, v in gvar.variations.items()}

    # The layout tables now list glyphs out of ID order; re-sort every coverage
    # (and its parallel arrays) for the unchanged glyph order.
    reorderGlyphs(font, order)


# --- naming ---------------------------------------------------------------------

def split_style(style: str) -> tuple[str, bool]:
    italic = style.endswith("Italic")
    weight = style.removesuffix("Italic") or "Regular"
    return weight, italic


def display_style(weight: str, italic: bool) -> str:
    if italic:
        return "Italic" if weight == "Regular" else f"{weight} Italic"
    return weight


def set_names(font: TTFont, names: dict[int, str]) -> None:
    table = font["name"]
    # Drop old Mac records and every core name we are about to rewrite.
    table.names = [
        r for r in table.names
        if r.platformID == 3 and (r.nameID >= 256 or r.nameID in (13, 14))
    ]
    for name_id, value in names.items():
        table.setName(value, name_id, 3, 1, 0x409)
    for record in table.names:
        if record.nameID >= 256:
            text = record.toUnicode()
            if "Geist" in text:
                record.string = text.replace("Geist", PS_FAMILY)


def relabel_features(font: TTFont) -> None:
    for rec in font["GSUB"].table.FeatureList.FeatureRecord:
        label = CHARACTER.get(rec.FeatureTag)
        params = rec.Feature.FeatureParams
        if label and params is not None:
            font["name"].setName(label, params.UINameID, 3, 1, 0x409)


def common_names() -> dict[int, str]:
    return {
        0: COPYRIGHT,
        5: f"Version {VERSION}",
        8: "Crooli",
        9: DESIGNER,
        10: DESCRIPTION,
        11: "https://crooli.com",
        12: "https://crooli.com/font",
    }


def name_static(font: TTFont, style: str) -> str:
    weight, italic = split_style(style)
    ribbi = weight in ("Regular", "Bold")
    shown = display_style(weight, italic)
    ps = f"{PS_FAMILY}-{style}"
    names = common_names() | {
        1: FAMILY if ribbi else f"{FAMILY} {weight}",
        2: shown if ribbi else ("Italic" if italic else "Regular"),
        3: f"{VERSION};{VENDOR};{ps}",
        4: f"{FAMILY} {shown}",
        6: ps,
    }
    if not ribbi:
        names |= {16: FAMILY, 17: shown}
    set_names(font, names)

    os2 = font["OS/2"]
    os2.usWeightClass = WEIGHTS[weight]
    os2.fsSelection &= ~((1 << 0) | (1 << 5) | (1 << 6))
    if italic:
        os2.fsSelection |= 1 << 0
    if weight == "Bold":
        os2.fsSelection |= 1 << 5
    if weight == "Regular" and not italic:
        os2.fsSelection |= 1 << 6
    font["head"].macStyle = (1 if weight == "Bold" else 0) | (2 if italic else 0)
    return ps


def name_variable(font: TTFont, italic: bool) -> str:
    style = "Italic" if italic else "Regular"
    ps = f"{PS_FAMILY}-{style}"
    set_names(font, common_names() | {
        1: FAMILY,
        2: style,
        3: f"{VERSION};{VENDOR};{ps}",
        4: f"{FAMILY} {style}" if italic else FAMILY,
        6: ps,
        25: f"{PS_FAMILY}Italic" if italic else PS_FAMILY,
    })
    return ps


def finish(font: TTFont) -> None:
    font["OS/2"].achVendID = VENDOR
    font["head"].fontRevision = float(VERSION)
    font["head"].modified = timestampNow()
    relabel_features(font)


# --- build ----------------------------------------------------------------------

def check(path: Path) -> None:
    font = TTFont(path)
    for record in font["name"].names:
        if "Geist" in record.toUnicode() and record.nameID not in CREDIT_IDS:
            raise SystemExit(f"{path.name}: name {record.nameID} still says Geist")
    family = font["name"].getDebugName(16) or font["name"].getDebugName(1)
    assert family == FAMILY or family.startswith(f"{FAMILY} "), family
    assert len(font.getBestCmap()) > 600
    font.close()


def save(font: TTFont, ttf: Path, woff2: Path) -> None:
    ttf.parent.mkdir(parents=True, exist_ok=True)
    woff2.parent.mkdir(parents=True, exist_ok=True)
    font.save(ttf)
    check(ttf)
    web = TTFont(ttf)
    web.flavor = "woff2"
    web.save(woff2)


def main() -> None:
    statics = sorted((SOURCES / "static").glob("Geist-*.ttf"))
    variables = sorted((SOURCES / "variable").glob("Geist*[[]wght[]].ttf"))
    if not statics or not variables:
        sys.exit("Geist sources missing; see sources/geist/README.txt")

    report = []
    for src in statics:
        font = TTFont(src)
        swaps = character_swaps(font)
        rename_shapes(font, swaps)
        style = src.stem.removeprefix("Geist-")
        ps = name_static(font, style)
        finish(font)
        save(font, FONTS / "ttf" / f"{ps}.ttf", FONTS / "webfonts" / f"{ps}.woff2")
        report.append(f"{ps}: {len(swaps) // 2} glyphs promoted")

    for src in variables:
        italic = "Italic" in src.stem
        font = TTFont(src)
        swaps = character_swaps(font)
        rename_shapes(font, swaps)
        name_variable(font, italic)
        finish(font)
        stem = f"{PS_FAMILY}-Italic[wght]" if italic else f"{PS_FAMILY}[wght]"
        save(font, FONTS / "variable" / f"{stem}.ttf", FONTS / "webfonts" / f"{stem}.woff2")
        report.append(f"{stem}: {len(swaps) // 2} glyphs promoted")

    print("\n".join(report))
    print(f"\nBuilt {len(report)} fonts into {FONTS.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
