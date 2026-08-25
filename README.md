# ids-to-font

Build a presentation-only WOFF2 or TTF font and a matching IDS-to-PUA JSON mapping
from a newline-delimited list of Ideographic Description Sequences (IDS).

The tool resolves each IDS through the Zi.tools API, converts the returned KAGE
outline to a font glyph, and assigns a code point in the Unicode BMP Private
Use Area.

Generated TrueType outlines are marked as containing overlapping contours so
stroke intersections retain the source SVG's filled appearance. Each
separately filled SVG stroke is also normalized to the same contour direction
before the paths are combined into one font glyph; this prevents
opposite-winding strokes from becoming holes.

## Input

The input is UTF-8 text containing one IDS expression per non-empty
line:

```text
⿰鳥叴
⿱弔口
⿺辶寺
```

Whitespace inside an expression, braces, comments, and non-IDS lines are
rejected. Duplicate lines are harmless.

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
```

## Usage

```bash
ids-to-font ids.txt --output-directory build
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

The default format is `woff2`. Run the command once per desired format; both
formats use the same PUA assignments when given the same previous mapping.

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

Reuse permanent PUA assignments from an earlier output mapping:

```bash
ids-to-font ids.txt \
  --previous-mapping previous/ids-glyphs.json \
  --output-directory build
```

Existing assignments are preserved. Code points assigned to expressions that
are no longer active remain reserved and are never silently reassigned.

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

The pinned FontTools and Brotli versions, identical inputs, the same previous
mapping, format, and metadata produce the same font bytes.

## Output mapping

The JSON contains:

- `font`, the generated font filename;
- `font_format`, either `woff2` or `ttf`;
- `glyphs`, the active IDS-to-character mappings represented by the font;
- `assignments`, the permanent assignment history used by later builds;
- `provider`, the outline provider used for this build.

PUA values are presentation identifiers, not textual data. Consumers must
always use the JSON mapping paired with the generated font.

## Licensing

The `ids-to-font` software is available under the MIT License.

The glyph outlines returned by Zi.tools are derived from KAGE data. Generated
fonts and outline data may be subject to the licences and attribution
requirements of Zi.tools, KAGE, and their underlying glyph sources. This
software does not relicense downloaded glyph data.
