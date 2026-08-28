# Idea: private rendering IDS

An IDS can serve two different purposes:

- The **outer IDS** is the public transcription and the font's ligature input.
  Its choice of components and structure records an intelligible scholarly
  judgment, even when that judgment is not annotated explicitly.
- An **inner rendering IDS** may be used privately by the font generator when
  a different decomposition produces a better glyph.

The generated font should continue to substitute the literal outer IDS with
one glyph. The inner IDS should affect only that glyph's outline: it should not
replace the transcription, change the ligature sequence, or appear when text
is copied, searched, or cited.

If this distinction is formalized later, a name such as `rendering_ids`,
`outline_ids`, or `glyph_source_ids` may describe the private value more
accurately than `resolved_ids`, which can imply that the alternate
decomposition is editorially authoritative.
