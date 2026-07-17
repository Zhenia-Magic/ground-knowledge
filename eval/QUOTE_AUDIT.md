# Quote audit

Generated from the current case files by `scripts/audit_quotes.py`. The companion JSON records the current hashed verification snapshot; its generation timestamp is not a claim that every unchanged URL was refetched on that date.

A checkmark means one complete verbatim sentence was found in one fetched-text segment and is bound to both the displayed-sentence hash and checked-text hash. It verifies the text match, not whether the sentence entails the assigned position. `fuzzy`, `missing`, and `unchecked` wording is not rendered as a quotation and cannot automatically confirm an evidence root.

| Case | Sources | Position exact | Fuzzy | Missing | Unchecked |
|---|---:|---:|---:|---:|---:|
| 177f5ec738c9.kb.json | 34 | 34 | 0 | 0 | 0 |
| 51fb332b4e96.kb.json | 68 | 68 | 0 | 0 | 0 |
| blackholes.kb.json | 15 | 15 | 0 | 0 | 0 |
| covid.kb.json | 29 | 29 | 0 | 0 | 0 |
| eggs.kb.json | 21 | 21 | 0 | 0 | 0 |
| tylenol.kb.json | 24 | 22 | 2 | 0 | 0 |

Position excerpts: **189 exact of 191**; 2 fuzzy, 0 missing, 0 unchecked.

All stored excerpts (position, dependency, and factor): **391 exact of 397**; 6 fuzzy, 0 missing, 0 unchecked. Every non-exact item is visibly downgraded and excluded from automatic root confirmation.

## Remaining non-exact position wording

These entries remain visible as unquoted summaries with a warning; they are never silently certified.

- `tylenol.kb.json` · **fuzzy** · [Chu et al. — Acetaminophen's Role in Autism and ADHD: A Mitochondrial Perspective (Int. J. Mol. Sci.)](https://www.mdpi.com/1422-0067/26/17/8585)
- `tylenol.kb.json` · **fuzzy** · [FDA — Responds to Evidence of Possible Association Between Autism and Acetaminophen Use During Pregnancy (press announcement)](https://www.fda.gov/news-events/press-announcements/fda-responds-evidence-possible-association-between-autism-and-acetaminophen-use-during-pregnancy)
