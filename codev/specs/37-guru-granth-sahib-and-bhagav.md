# Specification: Add the Guru Granth Sahib and the Bhagavad Gita (Gurmukhi + Devanagari)

<!--
SPEC vs PLAN BOUNDARY:
This spec defines WHAT and WHY. The plan defines HOW and WHEN.
Keep implementation phases, file paths, code, and "first we will… then we will…"
out of the spec — those belong in codev/plans/37-*.md.
-->

**Delivery.** One spec, two projects. Project 37 (`feat/guru-granth-sahib`) carries the shared
Indic normalization and the Guru Granth Sahib. Project 38 (`feat/bhagavad-gita`, stacked on 37)
carries the Bhagavad Gita. Plans: `codev/plans/37-*.md` and `codev/plans/38-*.md`.

## Problem Statement

The benchmark covers Abrahamic scripture only: Christian Bibles, LDS works, the Talmud, the
Qur'an, and hadith. It claims to be multi-faith by construction, but no Indic tradition is in the
pool. Two of the world's most-read scriptures are missing:

- **Sri Guru Granth Sahib** (Sikhism), in Gurmukhi script.
- **The Bhagavad Gita** (Hinduism), in Sanskrit, Devanagari script.

Adding them is more than two catalogue entries. The scorer cannot handle either script today.
`normalize()` turns every Indic vowel sign and virama into a space, so words break apart:

```
ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ   ->  ਸਤ ਨ ਮ ਕਰਤ ਪ ਰਖ
धर्मक्षेत्रे              ->  धर मक ष त र
```

`exact` still works, because both sides break the same way. `token_f1` and `contains_reference`
do not: they count fragments as words and find word boundaries in the middle of words. Any run
over these texts would publish wrong numbers. The scorer must be fixed before the first run.

## Current State

- **Catalogue.** Six tradition directories, 21 targets. A text enters the question pool only when
  `language == canonical_language`. Each in-pool text gets 28 questions from four templates.
- **Scripts.** `normalize()` is script-aware for Arabic and Hebrew only. It deletes their marks
  (optional vowel pointing) before the punctuation pass. All other scripts go through
  `[^\w\s]`. Python's `\w` does not match combining marks, so Indic vowel signs (category Mc/Mn)
  become spaces. The same flaw exists in Latin (`naïve` → `nai ve`), but no committed corpus
  shows it.
- **Copies of the rule.** Two more normalizers repeat the flaw: the failure-kind classifier
  (`[^\w\s]|_`) and the viewer's TypeScript port (`[^\p{L}\p{N}\s]`, which drops `\p{M}`).
- **Digits.** Native digits are not folded. Spec 26 already flagged this for Arabic-Indic digits.
- **Generate thresholds.** An entry needs ≥12 words to be identifiable and ≥16 to be completable.
  These were set for English verses.
- **Negatives.** `verify_source` prefers a same-language, different-family passage. A text with no
  same-language partner falls back to cross-language and is flagged (the Talmud's Aramaic today).

## Source Research

### Guru Granth Sahib

| Candidate | Licence of the text | Bulk access | Verdict |
|---|---|---|---|
| **Shabad OS** (`shabados/shabados`, `database/`) | Gurbani marked **public domain** (CC PDM 1.0); code MIT. One condition: no "derogatory treatment" that adds to, deletes from, or alters the words. | Yes: one TOML file per line in git; SQLite releases. | **Recommended.** |
| BaniDB (Khalis Foundation) | Code MIT. The project states a "controlled approach" to the data and is "not completely open". | API only; no dump found. | Rejected: unclear data terms, no bulk export. |
| Sikher GurbaniDB | GPL + CC BY-NC-SA 3.0. | Old dump. | Rejected: older, NC, superseded. |

Shabad OS facts, measured on the real data at commit `7e36a29` (2026-10-22):

- The old `shabados/database` repo was archived in August 2026. The data now lives in the
  `shabados/shabados` monorepo under `database/collections/`. It is 603 MB across 141k TOML files
  and covers many works (Dasam Granth, Bhai Gurdas, and others).
- A Guru Granth Sahib line is a `type = "primary"` content item tagged with asset **`SSA2`**
  (Shabadaarth, SGPC, 2009–2012). There are **60,555 lines across Angs 1–1430**, all 1,430 present.
- Each line carries `page` (the Ang) and `line`. **`line` is the physical printed line, not a
  pankti.** Several panktis share one physical line: 23,026 `(Ang, line)` pairs repeat. Order is
  recorded by `sections → lineGroups → lines`.
- The text contains markup that is not in the printed Granth:
  - **Vishraam (pause) marks** `;` (51,969), `.` (21,417), `,` (3,346), added from a reading
    pothi (Dauder, Damdami Taksaal).
  - **A non-standard vowel order**: bindi + ZWJ + vowel (`ਂ‍ੀ`, 74 occurrences) where standard Unicode
    is vowel + bindi (`ੀਂ`).
  - **Variation selector** U+FE00 (28 cases).
  - **Subscript digits** in raag headings (`ਗਉੜੀ₂`; 37 subscript characters): Shabad OS's disambiguation tags.
- Lines are short. After removing vishraams and numeric counters, the median is **6 words**.
  1,452 lines have ≥12 words and 100 have ≥16 (dandas not counted as words). Twenty eligible line texts occur at more than one
  location (refrains, the Mool Mantar).

### Bhagavad Gita

| Candidate | Licence | Shape | Verdict |
|---|---|---|---|
| **`gita/gita`** (`data/verse.json`) | **Unlicense** (public-domain dedication). The Sanskrit text is ancient and public domain in any case. | One JSON list, 701 items: `chapter_number`, `verse_number`, `text` (Devanagari), plus transliteration and word meanings. | **Recommended.** |
| `vedicscriptures/bhagavad-gita-data` | GPL-3.0 | Per-verse JSON files. | Fallback. GPL on a data compilation adds friction for no gain. |
| GRETIL / TextGrid editions | CC BY-NC-SA 4.0; most carry commentary. | TEI/plain text. | Rejected: NC, commentary-bound. |
| sanskritdocuments.org | "Personal study and research"; no reposting. | HTML/ITRANS. | Rejected: terms forbid redistribution. |

`gita/gita` facts, measured at commit `c6fce39`:

- **701 verses** in 18 chapters. Chapter 13 has 35 verses. It includes the Arjuna verse
  *prakṛtiṃ puruṣaṃ caiva* as 13.1, which the 700-verse Gita Press edition leaves unnumbered.
  **Chapter 13 citations therefore run one ahead of Gita Press.** The edition is not named
  upstream. The transliteration style matches holy-bhagavad-gita.org; this needs confirmation
  before it is recorded as provenance.
- Each `text` ends with an inline number marker (`।।1.1।।`). All 701 markers agree with
  `chapter_number.verse_number`. At least one marker is malformed (`।।18.78।`).
- 33 verses open with a speaker label (`धृतराष्ट्र उवाच`, `श्रीभगवानुवाच`). At least six have the label
  glued to the verse with no separator (`अर्जुन उवाचएवं…`, `श्री भगवानुवाचइदं…`).
- Sanskrit compounds make verses short in words: median **9 words**. 117 verses have ≥12 words
  and 11 have ≥16.
- No verse text repeats.

## Desired State

### Two new traditions, two new targets

| | Guru Granth Sahib | Bhagavad Gita |
|---|---|---|
| Tradition directory | `Sikhism` | `Hinduism` |
| `tradition` | `[Sikhism]` | `[Hinduism]` |
| `work` / `version` | `Sri Guru Granth Sahib` / `Shabad OS (SGPC Shabadaarth)` | `Bhagavad Gita` / `gita/gita` (name to confirm) |
| `language` = `canonical_language` | `pa` | `sa` |
| `document_type` | `scripture` | `scripture` |
| `license` | `public-domain` | `public-domain` |
| `unit_type` | `pankti` | `verse` |
| Citation | `Ang N:k` (see below) | `C:V`, e.g. `2:47` |
| `requested_as` | "the Guru Granth Sahib", "Sri Guru Granth Sahib", "the Adi Granth", "Gurbani" (to review) | "the Bhagavad Gita", "the Gita", "the Bhagavad Gītā" |

Both are in the default pool, because `language == canonical_language`.

### Raw payloads

- **Guru Granth Sahib.** Committing 603 MB of Shabad OS TOML is not acceptable. The committed raw
  payload is a **filtered, unmodified extract**: every `SSA2` primary line with its Ang, physical
  line, upstream line id, and canonical order, exactly as stored. The extract records the
  upstream commit SHA. A reproducible fetch step rebuilds it. "Raw" still means "as obtained";
  filtering selects lines but does not change any of them.
- **Bhagavad Gita.** `verse.json` is committed as downloaded (659 KB).

### Conversion rules (entry text)

The entry text is the scripture as printed, without upstream editorial apparatus.

- **Guru Granth Sahib:**
  - Remove the vishraam marks `;` `.` `,`.
  - Reorder bindi + ZWJ + vowel to standard Unicode order, and remove the variation selector.
  - Remove subscript disambiguation digits.
  - Remove the numeric counters `॥੧॥`, `॥੪॥੯॥੬੦॥`. **Keep** `ਰਹਾਉ`, which is a word of the text.
    Drop dandas too: they are punctuation, `normalize()` folds them to a space, and as
    space-delimited tokens they would count as words against the shared 12/16-word thresholds.
- **Bhagavad Gita:** remove the inline number marker and the speaker label, including glued labels.
  The speaker label is a heading, not part of the shloka.
- **No word of the scripture is added, deleted, or altered.** This satisfies Shabad OS's
  no-derogatory-treatment condition. A test proves it: removing the declared apparatus from the
  raw text yields the entry text, character for character.
- Every converted text has **unique citations**, as for every corpus (fail-fast).

### Guru Granth Sahib citation: `Ang N:k`

`k` is the pankti's 1-based position within Ang N, in canonical order. Physical line numbers
cannot be used because they repeat. The `Ang N:k` form fits the existing colon citation extractor
with no scorer change. It does not match how people cite Gurbani: they usually cite the Ang alone.
See Open Question 1.

### Script-aware normalization for Gurmukhi and Devanagari

- Combining marks in the **Gurmukhi (U+0A00–U+0A7F)** and **Devanagari (U+0900–U+097F)** blocks
  are kept as part of the word. They are never turned into spaces. Unlike Arabic pointing, Indic
  vowel signs are spelling: `ਨਾਮ` and `ਨਮ` are different words.
- The danda `।` and double danda `॥` stay word separators.
- Gurmukhi and Devanagari digits fold to ASCII (`੧` → `1`, `१` → `1`).
- **Latin, Arabic, and Hebrew output is byte-for-byte unchanged.** The rule is block-scoped, like
  the Arabic/Hebrew rule. Fixing `naïve` is out of scope.
- **The same rule applies in all three normalizers**: the scorer, the failure-kind classifier, and
  the viewer. A parity fixture proves the three agree on Gurmukhi and Devanagari samples.

### Rebaseline

The change cannot move any committed score unless a committed answer contains Gurmukhi or
Devanagari. The projection oracle must show **zero moved cells**. If any cell moves, stop and
surface it to the architect, per the sanctioned-rebaseline rule.

## Success Criteria

- [ ] `validate` accepts both new `source.yaml` files; the catalogue lists 23 targets.
- [ ] `convert` produces the Guru Granth Sahib with 60,555 panktis (or a documented count after
      excluding headings, per Open Question 3) across Angs 1–1430, and the Gita with 701 verses
      across 18 chapters. Citations are unique.
- [ ] The apparatus-only test passes for every entry of both texts.
- [ ] `normalize()` keeps the sample Gurmukhi and Devanagari words whole, and folds native digits.
- [ ] Latin, Arabic, and Hebrew normalization is byte-identical on the pinned snapshot.
- [ ] Re-scoring committed runs moves zero cells (projection oracle).
- [ ] The three normalizers agree on the parity fixture.
- [ ] `generate` fills 28 questions for each new text with no shortfall; each template's pool is
      at least its quota.
- [ ] The copyright audit passes. No restricted source is involved.
- [ ] A budgeted live smoke (one cheap model, both texts) scores at least one correct
      `retrieve_quote` answer in each script. Hand review confirms each verdict matches the answer.

## Constraints

- No core pipeline code changes for the corpus itself: one converter function and one registry
  line per source, plus data.
- Generate thresholds (12/16 words) stay unchanged. Changing them would regenerate every text's
  questions. Both new texts clear them; see Risks.
- No re-run of `collect`, `score`, or `generate` over committed run evidence. New runs go to a
  fresh `runs/<id>/`.
- The scorer change is block-scoped. Behaviour outside the two Indic blocks does not change.

## Assumptions

- Shabad OS's public-domain statement covers the Gurbani text in `database/collections/`, which
  replaced the old `data/` folder after the monorepo move. **To confirm** with the README in the
  monorepo, not the archived one.
- The Gita's Sanskrit text in `gita/gita` is the standard 701-verse recension. Its exact source
  edition gets recorded once confirmed.
- `pa` is the right code for the Granth. Its language is mixed (Sant Bhasha: old Punjabi, Braj,
  Lahnda, Persian, and Sanskrit loans), but its script and catalogue identity are Gurmukhi Punjabi.

## Solution Approaches

### Approach 1 (recommended): Pankti units, Shabad OS + gita/gita, block-scoped normalize fix

The design described above. It uses the cleanest licences, the smallest scorer change, and no
change to generate.

### Approach 2 (rejected): Shabad-level or stanza-level Granth units

Merge panktis up to each `॥N॥` counter. Entries would be longer and closer in feel to a Bible
verse, and they would clear the word thresholds easily. Rejected because no shared citation
convention exists at that level, and a stanza id would be invented. Revisit if pankti results sit
at the floor.

### Approach 3 (rejected): Delete Indic marks the way Arabic marks are deleted

This is simpler, but it merges distinct words (`ਨਾਮ` and `ਨਮ`), so wrong answers could score as
correct.

## Open Questions

1. **Granth citation precision.** People usually cite the Ang alone. `cite_passage` needs one
   unique citation per entry, so `Ang N:k` is required, but few models will know `k`. Options:
   (a) keep `Ang N:k` and accept a low `cite_passage` ceiling, reported on the card; (b) score
   `cite_passage` on the Ang only for this text. Option (b) is a scorer change. **Recommend (a)
   for the first run.**
2. **Gita version name.** `version` should name an edition, not a repo. Can the upstream source be
   confirmed (holy-bhagavad-gita.org)?
3. **Headings.** Raag and author headings (`ਗਉੜੀ ਮਹਲਾ ੫`, `॥ ਜਪੁ ॥`) are `SSA2` lines. They never
   reach the question pool (under 12 words). Keep them as `heading` entries for completeness, or
   drop them? **Recommend keep**, so the document matches the Granth.
4. **Repeated lines.** Twenty eligible Granth texts occur at more than one Ang. `cite_passage` could
   ask for one and mark the other location wrong. The Bible has the same issue today. **Recommend**
   leaving generate unchanged and reporting the count on the card.
5. **Same-language negatives.** Both texts are the only one in their language, so every
   `verify_source` negative is cross-script and easy to reject. Add a second text per language
   later (e.g. Dasam Granth or Bhai Gurdas from the same Shabad OS dump; an Upanishad)? Out of
   scope here; flagged on the card.

## Test Scenarios

- Catalogue: both `source.yaml` files load. Missing `requested_as` or a bad licence fails fast.
- Converter (Granth): fixtures covering two panktis on one physical line, a glued ZWJ vowel, a
  subscript heading, a `॥੧॥ ਰਹਾਉ ॥` line, and the Mool Mantar. Assert order, the citations, and the
  cleaned text.
- Converter (Gita): fixtures covering the 13.1 extra verse, a glued speaker label
  (`श्री भगवानुवाचइदं`), and the malformed `।।18.78।` marker.
- Apparatus-only property: over the full payloads, raw minus declared apparatus equals entry text.
- Normalize: the sample words stay whole; `੧२३` → `123`; the Latin/Arabic/Hebrew snapshot is
  unchanged.
- Smallest change the check must catch: one vowel sign split from its word fails the test.
  Largest: a normalizer that deletes all Indic marks (Approach 3) also fails, because `ਨਾਮ` ≠ `ਨਮ`.
- Parity: the scorer, failure-kind, and viewer normalizers give identical tokens on the fixture.
- Generate: both texts reach 28 questions with fixed seeds, deterministically.
- Rebaseline: re-scoring committed runs moves zero cells.

## Risks and Mitigation

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Thin `complete_unit` pools (Gita 11 verses ≥16 words, Granth 100) bias toward the longest units | High | Medium | Pools exceed the quota of 7. Report pool sizes on the card. Revisit thresholds per language in a later spec. |
| Chapter 13 numbering differs from Gita Press | Medium | Medium | Record the recension in `license_detail`/notes. Note on the card that 13.x citations may be off by one. |
| Shabad OS reorganises again | Medium | Low | Pin the commit SHA in provenance. Commit the extract. |
| Mixed-language Granth makes `pa` a simplification | Low | Low | Note it on the card. |
| Viewer and scorer disagree on Indic tokens | Medium | Medium | Parity fixture in both test suites. |
| A missed apparatus character silently changes gold text | Medium | High | The apparatus-only property test runs over the full payloads. |

## References

- Shabad OS monorepo: https://github.com/shabados/shabados (database at `7e36a29`)
- Archived Shabad OS database and licence statement: https://github.com/shabados/database
- BaniDB API: https://github.com/KhalisFoundation/BaniDB-API
- `gita/gita`: https://github.com/gita/gita (Unlicense, `c6fce39`)
- `vedicscriptures/bhagavad-gita-data`: https://github.com/vedicscriptures/bhagavad-gita-data
- GRETIL Bhagavadgītā (TextGrid): https://www.textgridrep.org/browse/49nxz.0
- Spec 15 (scoring contract), Spec 26 (original-language pool, Arabic-Indic digits), Spec 32 (card).
