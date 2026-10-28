# Plan: Bhagavad Gita (Sanskrit, Devanagari)

**Specification**: [codev/specs/37-guru-granth-sahib-and-bhagav.md](../specs/37-guru-granth-sahib-and-bhagav.md)
**Branch**: `feat/bhagavad-gita`, stacked on `feat/guru-granth-sahib` (project 37).

## Executive Summary

This project adds the Bhagavad Gita as an in-pool Sanskrit text. Project 37 already ships the
Devanagari normalization (one rule for both Indic scripts), so this project is corpus-only: one
payload, one `source.yaml`, one converter, and checks. It needs no scorer change.

**Before Phase 1, settle spec Open Question 2**: the Gita's `version` name. Upstream `gita/gita` does
not name its source edition. The transliteration style matches holy-bhagavad-gita.org (Swami
Mukundananda). Confirm that, or pick a neutral name such as `701-verse recension (gita/gita)`.

## Phases (Machine Readable)

<!-- REQUIRED: porch parses this JSON to track phase progress. Keep it in sync when you add or remove phases; at least two phases. -->

```json
{
  "phases": [
    {"id": "phase_1", "title": "Raw payload: gita/gita verse.json + Hinduism source.yaml"},
    {"id": "phase_2", "title": "Converter: gita_json (verse, C:V, marker and speaker removal)"},
    {"id": "phase_3", "title": "Generate check, docs, budgeted live smoke"}
  ]
}
```

## Phase Breakdown

### Phase 1: Raw payload

**Dependencies**: Project 37 merged into this branch's base.

#### Files to Create / Modify

- `texts/raw/Hinduism/verse.json`: `gita/gita` `data/verse.json` at commit `c6fce39`, committed as
  downloaded (659 KB). Record its SHA-256 in the provenance notes.
- `texts/raw/Hinduism/source.yaml`: one target.
  - `work: Bhagavad Gita`, `version` per Open Question 2.
  - `language: sa`, `canonical_language: sa`, `document_type: scripture`, `tradition: [Hinduism]`.
  - `license: public-domain`, `license_detail: Unlicense (gita/gita); Sanskrit text ancient, public domain`.
  - `requested_as: ["the Bhagavad Gita", "the Gita", "the Bhagavad Gītā"]`.
  - Provenance is `retrieved_from: github.com/gita/gita@c6fce39 (data/verse.json)`, with a dated fetch.
  - Notes record that this is the 701-verse recension, with chapter 13 one ahead of Gita Press.
- Only `text` (Sanskrit) is used. The transliteration and word meanings ride along in the file
  but never reach a `Document`.

#### Acceptance Criteria

- The file's hash matches the upstream blob at the pinned commit.
- `source.yaml` validates.

### Phase 2: Converter `gita_json`

**Dependencies**: Phase 1.

#### Files to Create / Modify

- `pipelines/sacredbench/convert.py`: `convert_gita_json` plus one `CONVERTERS` line.
  - Unit `verse`; citation `C:V` from `chapter_number`/`verse_number`.
  - Remove the trailing number marker (`।।C.V।।`, including the malformed `।।18.78।`). Assert that
    the marker, when present, equals `C.V`, and fail on a mismatch.
  - Remove a leading speaker label (`<name> उवाच` and the sandhi form `श्रीभगवानुवाच`), whether
    separated by a newline or glued to the verse. Derive the full label list from the data (33
    verses) and pin it in the docstring.
  - Join the half-verse lines with a single space.
- `pipelines/tests/test_schema_convert.py`: fixtures for 1.1 (newline label), 12.1 and 13.2
  (glued labels), 13.1 (the extra verse), and 18.78 (malformed marker).
- `pipelines/tests/test_catalogue.py`: the real-tree target count goes from 22 to 23.
- A full-payload property test: raw `text` minus the declared marker and label equals the entry
  text, for all 701 verses.

#### Acceptance Criteria

- 701 entries in 18 chapters. Chapter 13 has 35. Citations are unique.
- No entry text contains `उवाच`/`ुवाच` at its start, a danda-number marker, or a newline.
- The property test passes.

### Phase 3: Generate check, docs, live smoke

**Dependencies**: Phase 2. **Get the architect's budget sign-off before the smoke.**

#### Deliverables

- `pipelines/tests/test_generate.py`: the Gita fills 28 questions deterministically. Expected
  pools: 117 verses ≥12 words, 11 ≥16. That is thin for `complete_unit` (quota 7), so assert it
  explicitly.
- Committed runs are untouched: no `runs/**` file changes. Other texts' questions change, because
  "Bhagavad Gita" sorts first and the RNG is shared. That is expected; the new manifest records
  the new pool. Generating twice with the same seed gives identical output.
- `texts/README.md` and `pipelines/README.md` list the Hinduism source.
- A fresh `runs/<id>/` smoke with one cheap model over the Gita's 28 questions. Hand-review every
  cell. Check in particular that `cite_passage` answers for chapter 13 that use Gita Press numbering
  score incorrect, and record how many there are on the card.

## Risks and Mitigation

| Risk | Mitigation |
|---|---|
| Chapter 13 numbering mismatch inflates `cite_passage` errors | Record the recension in notes and on the card; count the affected cells in the smoke. |
| The speaker-label list misses a form | The property test runs over all 701 verses, and the converter fails on an unknown `उवाच` prefix. |
| The `complete_unit` pool of 11 skews to the longest verses | Report the pool size on the card. Per-language thresholds are a later spec. |
| Upstream edition stays unnamed | A neutral `version` name and an explicit note; no claim about the edition. |
