# Mechanical language conversions

Two of the 30 supported languages are not independent translations. They are mechanical conversions from other languages:

- **English (US)** (en-US) is derived from **English** (en) via spelling substitution
- **Traditional Chinese** (zh-Hant) is derived from **Simplified Chinese** (zh) via character conversion

## English to English (US)

A dictionary of British to American spelling changes. Common substitutions:

- -our to -or (colour to color, behaviour to behavior)
- -ise/-isation to -ize/-ization (organisation to organization)
- -ence to -ense where applicable (licence to license for the noun)
- -re to -er (centre to center)
- -logue to -log (catalogue to catalog)
- Double l to single l (travelling to traveling)

This applies to both i18n string files and content markdown files. The conversion should be a script in the assembler pipeline that reads the English output and produces the en-US variant.

## Simplified Chinese to Traditional Chinese

Use OpenCC (Open Chinese Convert), the standard open-source tool for this conversion. OpenCC handles character-by-character conversion plus phrase-level adjustments (some terms use different words, not just different characters, between simplified and traditional).

Install: `pip install opencc-python-reimplemented` or system package `opencc`

This applies to both i18n string files and content markdown files. The conversion should run after the Simplified Chinese translation is produced.

## Implications for the translation workflow

The assembler translates English into 28 languages. It then mechanically derives the remaining 2. The translation count is 28, not 30. This is noted in the languages data file (script field is the same for each pair).
