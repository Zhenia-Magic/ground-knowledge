# Quote audit

Generated from the current case files by `scripts/audit_quotes.py`. The companion JSON records the current hashed verification snapshot; its generation timestamp is not a claim that every unchanged URL was refetched on that date.

A checkmark means one complete verbatim sentence was found in one fetched-text segment and is bound to both the displayed-sentence hash and checked-text hash. It verifies the text match, not whether the sentence entails the assigned position. `fuzzy`, `missing`, and `unchecked` wording is not rendered as a quotation and cannot automatically confirm an evidence root.

| Case | Sources | Position exact | Fuzzy | Missing | Unchecked |
|---|---:|---:|---:|---:|---:|
| blackholes.kb.json | 15 | 15 | 0 | 0 | 0 |
| covid.kb.json | 29 | 29 | 0 | 0 | 0 |
| eggs.kb.json | 23 | 23 | 0 | 0 | 0 |

Position excerpts: **67 exact of 67**; 0 fuzzy, 0 missing, 0 unchecked.

All stored excerpts (position, dependency, and factor): **112 exact of 112**; 0 fuzzy, 0 missing, 0 unchecked. Every non-exact item is visibly downgraded and excluded from automatic root confirmation.

## Remaining non-exact position wording

These entries remain visible as unquoted summaries with a warning; they are never silently certified.
