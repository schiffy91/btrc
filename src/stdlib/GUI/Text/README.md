# Unicode text boundaries

`btrcGraphemeBoundaries` returns UTF-8 byte positions of extended grapheme clusters and the final byte length. Use `btrcGraphemeFloor` and `btrcGraphemeCeil` to snap a byte position to an inclusive boundary for selection, caret positioning or truncation. The result keeps combining sequences, Indic conjuncts, emoji ZWJ sequences and regional-indicator flag pairs together. The Unicode 17.0.0 GraphemeBreakTest fixture exercises every published case, and `python -m tools.unicode_data.grapheme /path/to/ucd` regenerates the compiled property tables. [Unicode Text Segmentation](https://www.unicode.org/reports/tr29/)

`btrcLineBreaks` lists the default Unicode line-wrap opportunities as UTF-8 byte offsets, marking mandatory breaks and the end of text. The caller chooses a suitable candidate for the available layout width. The Unicode 17.0.0 LineBreakTest suite covers the language-independent default rules. Script-specific dictionary segmentation and hyphenation are separate layout choices. Regenerate the tables with `python -m tools.unicode_data.line_break /path/to/ucd`. [Unicode Line Breaking Algorithm](https://www.unicode.org/reports/tr14/)

The Unicode 17.0.0 property tables and official conformance vectors are
generated from the pinned Character Database. The upstream Unicode Data
License applies to those data files. [Pinned Unicode Character Database](https://github.com/unicode-org/unicodetools/tree/725fb6055cd42915c74bcf77b91aa8fb8ef18669/unicodetools/data/ucd/17.0.0) · [Unicode license](UNICODE-LICENSE.txt)
