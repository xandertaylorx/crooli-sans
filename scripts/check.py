#!/usr/bin/env python3
"""Check Crooli Sans against Geist.

Crooli Sans with no features must shape exactly like Geist with the promoted
stylistic sets switched on (same outlines, advances, kerning and mark
positions), and switching those sets on in Crooli must give back plain Geist.
Every static style and the variable fonts at several weights are checked.

Usage: python scripts/check.py   (needs uharfbuzz; see requirements-dev.txt)
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).parent))
from build import CHARACTER, FONTS, SOURCES  # noqa: E402

SAMPLES = [
    "Crooli Sans — a grand gallery of rally races, 0123456789.",
    "Quartz glyph jocks vex dwarf; Ġ ġ Ȑ ŕ ľ Ľ ļ ł á à â ä ã å ā ă ą ǎ ạ ấ ầ ẩ ẫ ậ ắ ằ ẳ ẵ ặ",
    "Illegal, little, lull… “Real” ‘G-gauge’ R&D: 3.14; e.g. a/b · ¿Qué? ¡Sí!",
    "Ärger über Größe. Øre, Ålesund. Łódź. Țară. Şahin. Ğ. İstanbul. Ĳsselmeer.",
    "Съешь же ещё этих мягких французских булок, да выпей чаю. Ґ Ї Ё ё",
    "AV Ta To LT Yo P. F, r. y. 'quoted' W.A.R. ff fi fl ft tt",
]
WEIGHTS = [100, 250, 400, 560, 700, 900]


def shape(path: Path, text: str, features: dict, wght: int | None = None):
    blob = hb.Blob.from_file_path(str(path))
    font = hb.Font(hb.Face(blob))
    if wght is not None:
        font.set_variations({"wght": wght})
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, features)
    glyphs = [info.codepoint for info in buf.glyph_infos]
    positions = [(p.x_advance, p.x_offset, p.y_offset) for p in buf.glyph_positions]
    return glyphs, positions


def outline(font: TTFont, gid: int):
    glyphs = font.getGlyphSet()
    pen = DecomposingRecordingPen(glyphs)
    glyphs[font.getGlyphName(gid)].draw(pen)
    return pen.value


def compare(crooli: Path, geist: Path, wght: int | None = None) -> list[str]:
    on = {tag: True for tag in CHARACTER}
    texts = SAMPLES + [unicodedata.normalize("NFD", s) for s in SAMPLES]
    cfont, gfont = (TTFont(crooli), TTFont(geist)) if wght is None else (None, None)
    errors = []
    for text in texts:
        for c_feat, g_feat in (({}, on), (on, {})):
            cg, cp = shape(crooli, text, c_feat, wght)
            gg, gp = shape(geist, text, g_feat, wght)
            if cp != gp:
                errors.append(f"positions differ ({'default' if not c_feat else 'sets on'}): {text[:40]!r}")
            if cfont is not None:
                if any(outline(cfont, a) != outline(gfont, b) for a, b in zip(cg, gg)):
                    errors.append(f"outlines differ: {text[:40]!r}")
    return errors


def main() -> None:
    pairs = [
        (FONTS / "ttf" / f"CrooliSans-{src.stem.removeprefix('Geist-')}.ttf", src, None)
        for src in sorted((SOURCES / "static").glob("Geist-*.ttf"))
    ]
    for italic in (False, True):
        crooli = FONTS / "variable" / ("CrooliSans-Italic[wght].ttf" if italic else "CrooliSans[wght].ttf")
        geist = SOURCES / "variable" / ("Geist-Italic[wght].ttf" if italic else "Geist[wght].ttf")
        pairs += [(crooli, geist, w) for w in WEIGHTS]

    failed = 0
    for crooli, geist, wght in pairs:
        errors = compare(crooli, geist, wght)
        label = crooli.name + (f" @ wght {wght}" if wght else "")
        print(("FAIL " if errors else "ok   ") + label)
        for error in errors[:5]:
            print("     " + error)
        failed += bool(errors)
    if failed:
        sys.exit(f"{failed} check(s) failed")
    print(f"\nAll {len(pairs)} checks passed.")


if __name__ == "__main__":
    main()
