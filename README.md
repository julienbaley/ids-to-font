# ids-to-font

Build presentation-only WOFF2 or TTF fonts from Ideographic Description
Sequences (IDS) or encoded Unicode characters.

The default IDS mode keeps text literal and uses the OpenType `rlig` feature
to replace supported sequences with generated outlines. Unicode supplement
mode accepts existing characters, retrieves their outlines and decompositions
from Zi.tools, and maps each glyph to its real Unicode code point.

IDS component glyphs are zero-width placeholders, so generated IDS fonts must
be used in explicit font runs rather than as global fallbacks.

When an unresolved IDS contains exactly one `□` lacuna component and
`--match-font` is supplied, the tool finds encoded examples with the same IDS
structure in a pinned CJKVI IDS index. It learns the component allocation from
up to eight examples present in the reference font, retains only contours from
the readable components, and draws a dotted box in the damaged region.

Generated TrueType outlines are marked as containing overlapping contours so
stroke intersections retain the source SVG's filled appearance. Each
separately filled SVG stroke is also normalized to the same contour direction
before the paths are combined into one font glyph; this prevents
opposite-winding strokes from becoming holes.

## IDS input

The input is UTF-8 text containing one IDS expression per non-empty
line:

```text
⿰鳥叴
⿱弔口
⿺辶寺
```

Whitespace inside an expression, braces, comments, and non-IDS lines are
rejected. Duplicate lines are harmless.

## Encoded Unicode input

Unicode mode accepts one Unicode scalar or `U+` value per non-empty line:

```text
𬘄
U+26B82
```

The character itself is the font's cmap value. Zi.tools supplies its outline
and may supply one or more level-1 IDS decompositions. These decompositions
are recorded as input aliases; they do not replace the encoded character.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
```

## Usage

```bash
ids-to-font ids.txt --output-directory build
```

The generated font maps each scalar occurring in the input to a zero-width
placeholder and applies an `rlig` substitution for each complete IDS. The
document text remains the literal IDS sequence. For TTF output, the generated
LaTeX package validates supported expressions and emits them unchanged:

```tex
\usepackage{ids-glyphs}

Received text \ids{⿰鳥叴} continues here.
```

This writes a content-addressed WOFF2 font and `ids-glyphs.json`:

```text
build/ids-glyphs-<sha256-prefix>.woff2
build/ids-glyphs.json
```

Generate a TTF for desktop or LaTeX use instead:

```bash
ids-to-font ids.txt \
  --output-format ttf \
  --output-directory build
```

This also writes `ids-glyphs.sty`, a generated LaTeX package paired with the
content-addressed TTF:

```text
build/ids-glyphs-<sha256-prefix>.ttf
build/ids-glyphs.json
build/ids-glyphs.sty
```

Place the `.sty` and TTF beside the document, then compile with XeLaTeX or
LuaLaTeX:

```tex
\usepackage{ids-glyphs}

Received text \ids{⿰鳥叴} continues here.
```

`\ids{...}` validates the expression, selects the generated font, and emits
the literal IDS for OpenType shaping. For advanced formatting, `\idsfont` is
the generated font switch and `\idschar{...}` is equivalent to `\ids{...}`.
An unknown IDS expression produces a LaTeX error rather than disappearing as
zero-width component glyphs.

The default format is `woff2`; the `.sty` package is generated only for TTF
output. Run the command once per desired format.

## Unicode supplements

Generate a font containing encoded characters that are missing from a
companion Han font:

```bash
ids-to-font missing-characters.txt \
  --mode unicode \
  --family-name "Odes Unicode Supplement" \
  --basename odes-unicode-supplement \
  --match-font /path/to/BabelStoneHan.ttf \
  --output-directory build
```

The supplement's cmap contains the original code points, so ordinary Unicode
input remains ordinary Unicode:

```tex
𬘄
```

The output JSON records every Zi.tools level-1 decomposition and identifies
the first returned decomposition as `preferred_decomposition`.

For LaTeX, generate TTF output and identify the primary font that should fall
back to the supplement:

```bash
ids-to-font missing-characters.txt \
  --mode unicode \
  --output-format ttf \
  --match-font build/primary-han.ttf \
  --latex-primary-font build/primary-han.ttf \
  --output-directory build
```

Place the primary TTF, supplement TTF, and generated `.sty` together. The
package provides `\idshanfamily`, which configures xeCJK fallback under
XeLaTeX and luaotfload fallback under LuaLaTeX:

```tex
\usepackage{unicode-supplement}

{\idshanfamily 一𬘄一}
```

The decomposition aliases remain available as a convenient alternative:

```tex
\ids{⿰𦁆糸}
```

This emits the real character `𬘄` from the supplement font.

## Matching a companion Han font

To make IDS glyphs share the optical size, baseline, and line spacing of a
font used for ordinary Han characters:

```bash
ids-to-font ids.txt \
  --match-font /path/to/BabelStoneHan.ttf \
  --output-directory build
```

The tool measures full-width CJK Unified Ideographs in the reference font and the
active IDS glyph set. It then applies one uniform scale and vertical shift to every
IDS outline, adopts the reference font's normalized vertical metrics, and
selects the closest safe half-unit outline inset or expansion within a bounded
range to match median ink density. The derived scale, shift, density, outline
inset, and reference sample sizes are recorded under `calibration` in the
output mapping.

Matching is optical rather than stylistic: outlines from different type
designs will retain their individual stroke shapes.

Zi.tools requests are made sequentially with a configurable delay:

```bash
ids-to-font ids.txt --delay 10 --output-directory build
```

Font metadata that affects byte-for-byte output is explicit:

```bash
ids-to-font ids.txt \
  --font-date 2026-08-25 \
  --copyright "KAGE-generated outlines preserved from Zi.tools." \
  --output-directory build
```

The pinned FontTools and Brotli versions, identical inputs, format, and
metadata produce the same font bytes.

## Output mapping

The JSON contains:

- `mode`, either `ligature` or `unicode`;
- `font`, the generated font filename;
- `font_format`, either `woff2` or `ttf`;
- `latex_package`, the generated `.sty` filename for TTF output;
- `glyphs`, the active IDS output glyph names or encoded code points;
- `decompositions` and `preferred_decomposition` for encoded glyphs;
- `provider`, the outline provider used for this build.

## Licensing

The `ids-to-font` software is available under the MIT License.

The glyph outlines returned by Zi.tools are derived from KAGE data. Generated
fonts and outline data may be subject to the licences and attribution
requirements of Zi.tools, KAGE, and their underlying glyph sources. This
software does not relicense downloaded glyph data.
