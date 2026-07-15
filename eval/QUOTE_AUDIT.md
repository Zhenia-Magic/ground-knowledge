# Quote audit

Generated from the current case files by `scripts/audit_quotes.py`. The companion JSON preserves
the last network-audit results and is pruned to the current inventory; its audit timestamp is not a
claim that every URL was refetched on this document's generation date.

A checkmark means one complete verbatim sentence was found in one fetched-text segment and is bound to both the displayed-sentence hash and checked-text hash. It verifies the text match, not whether the sentence entails the assigned position. `fuzzy`, `missing`, and `unchecked` wording is not rendered as a quotation and cannot automatically confirm an evidence root.

| Case | Sources | Position exact | Fuzzy | Missing | Unchecked |
|---|---:|---:|---:|---:|---:|
| 177f5ec738c9.kb.json | 35 | 35 | 0 | 0 | 0 |
| 51fb332b4e96.kb.json | 67 | 67 | 0 | 0 | 0 |
| blackholes.kb.json | 15 | 15 | 0 | 0 | 0 |
| covid.kb.json | 26 | 26 | 0 | 0 | 0 |
| eggs.kb.json | 20 | 20 | 0 | 0 | 0 |

Position excerpts: **163 exact of 163**; 0 fuzzy, 0 missing, 0 unchecked.

All stored excerpts (position, dependency, and factor): **308 exact of 308**; 0 fuzzy, 0 missing, 0 unchecked. Every non-exact item is visibly downgraded and excluded from automatic root confirmation.

## Remaining non-exact position wording

These entries remain visible as unquoted summaries with a warning; they are never silently certified.
