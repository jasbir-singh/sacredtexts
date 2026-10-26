# Plan: Guru Granth Sahib + Indic script normalization

**Specification**: [codev/specs/37-guru-granth-sahib-and-bhagav.md](../specs/37-guru-granth-sahib-and-bhagav.md)
**Branch**: `feat/guru-granth-sahib` (from `main`). The Bhagavad Gita (project 38) stacks on top.

## Executive Summary

This project adds Sri Guru Granth Sahib Ji as an in-pool text and fixes the scorer for Gurmukhi
and Devanagari. The scorer fix comes first, because a corpus scored by a broken normalizer
publishes wrong numbers. It covers both scripts in one rule, so project 38 adds the Gita with no
scorer work.

The order follows the data flow: scorer → raw payload → converter → generate → live smoke. Each
phase is one atomic commit and ends green.

**Open-question defaults** (spec §Open Questions; the user can overturn any of them before the
phase that uses it):

- Q1: citation `Ang N:k`. Accept the `cite_passage` ceiling and report it on the card.
- Q3: keep raag/author headings in the document. **Decided in Phase 3:** every line is a `pankti`;
  no heading classifier. Headings never reach the pool (under 12 words), and a wrong guess on a
  long line would make a prompt call scripture "that heading".
- Q4: generate unchanged. Report the 20 repeated line texts on the card.
- Q5: same-language negatives are out of scope. The cross-language fallback is flagged.

## Phases (Machine Readable)

<!-- REQUIRED: porch parses this JSON to track phase progress. Keep it in sync when you add or remove phases; at least two phases. -->

```json
{
  "phases": [
    {"id": "phase_1", "title": "Indic normalization: scorer, failure-kind, viewer, parity, zero-move rebaseline"},
    {"id": "phase_2", "title": "Raw payload: Shabad OS SGGS extract + Sikhism source.yaml"},
    {"id": "phase_3", "title": "Converter: shabados_sggs (panktis, Ang N:k, apparatus removal)"},
    {"id": "phase_4", "title": "Generate check, card counts, docs"},
    {"id": "phase_5", "title": "Budgeted live smoke"}
  ]
}
```

## Phase Breakdown

### Phase 1: Indic normalization

**Dependencies**: None.

#### Objective

Gurmukhi and Devanagari words survive `normalize()` whole, and native digits fold to ASCII. Latin,
Arabic, and Hebrew output stays byte-for-byte unchanged. All three normalizers agree.

#### Files to Create / Modify

- `pipelines/sacredbench/score.py`: in the script-aware step (before the punctuation pass), keep
  combining marks (Mn/Mc) in U+0900–U+097F and U+0A00–U+0A7F as word characters. Fold Gurmukhi
  digits U+0A66–U+0A6F and Devanagari digits U+0966–U+096F to ASCII. Dandas U+0964/U+0965 stay
  separators. Python's `\w` rejects Mc/Mn, so the punctuation regex needs an explicit
  allowance for those blocks, scoped so nothing outside them changes.
- `pipelines/sacredbench/failure_kind.py`: apply the same rule in `_normalize`. Teach `_script` to
  recognise `gurmukhi` and `devanagari`, so a Latin-transliterated answer to Gurmukhi ground truth
  classifies as wrong-script.
- `apps/viewer/src/lib/failureKind.ts`: the same rule in `normalize` (`[^\p{L}\p{N}\p{M}\s]` scoped to
  the two blocks, or an equivalent) and in its script detection.
- `fixtures/failure_kind_cases.json`: add Gurmukhi and Devanagari cases (a correct recital, a
  wrong-script transliteration, a native-digit citation). Both suites already load this file.
- `pipelines/tests/test_normalize_nonlatin.py`: new Indic tests (below).

#### Acceptance Criteria

- `normalize("ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ ॥")` returns `"ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ"`.
- `normalize("धर्मक्षेत्रे कुरुक्षेत्रे")` keeps two tokens.
- `੧੨੩` and `१२३` both normalize to `123`.
- `ਨਾਮ` ≠ `ਨਮ` after normalization, so marks are kept, not deleted.
- The existing Latin snapshot and the Arabic/Hebrew tests pass unchanged.
- The `test_contains_reference_rebaseline.py` projection oracle moves **zero** committed cells. If
  any cell moves, stop and surface it to the architect; do not rebaseline silently.
- The Python and TS suites agree on every fixture case.

#### Test Plan

- Make each test fail first on `main`'s normalizer, then pass.
- Smallest change the check must catch: one vowel sign split off its word.
- Largest: a normalizer that deletes every Indic mark (spec Approach 3) must also fail, through the
  `ਨਾਮ` ≠ `ਨਮ` case.
- Run both lanes: `uv --project pipelines run pytest pipelines` and `pnpm -C apps/viewer test`.

### Phase 2: Raw payload

**Dependencies**: None (it can run beside Phase 1, but commits after it).

#### Objective

A committed, reproducible, verbatim extract of every Guru Granth Sahib line from Shabad OS, with
pinned provenance.

#### Files to Create / Modify

- `texts/raw/Sikhism/build_extract.py`: a stdlib-only script (`tomllib`, `json`). It reads a local
  checkout of `shabados/shabados` at a given commit and writes the extract. Run with `python3 -I`
  against a sparse clone of `database/collections/{lines,line-groups,sections}`.
- `texts/raw/Sikhism/sggs_shabados.json`: the extract, about 9 MB. It has an `upstream`
  header (repo, commit SHA, asset `SSA2`, build date) and a `lines` list. Each line carries its
  upstream id, `ang`, physical `line`, canonical `order`, and `data` **exactly as stored**.
- `texts/raw/Sikhism/source.yaml`: one target, with fields from the spec's Desired State table.
  Provenance is `retrieved_from: github.com/shabados/shabados@<sha>`, `fetch_method: filtered
  extract (SSA2 primary lines), build_extract.py`, and a dated `fetch_date`. `license:
  public-domain`, with `license_detail` quoting the PDM statement and the no-derogatory-treatment
  condition.

#### Canonical order (derive from the data, not docs)

The extract fixes one order for all 60,555 lines. Derive it from `sections → lineGroups → lines`.
Record how the sections' own order was found; if no explicit section order exists, say so and
sort sections by their first line's `(ang, line)`. The order must satisfy this invariant:
**`(ang, line)` never decreases along it**. The script fails if the invariant breaks.

#### Acceptance Criteria

- Re-running the script at the pinned SHA reproduces the committed file byte for byte.
- The file has 60,555 lines, Angs 1–1430, all present.
- Every `data` string equals the upstream TOML value (spot-check plus a full-run hash check in the
  script).
- `source.yaml` validates. Before trusting the licence, confirm that the monorepo's database
  README carries the same public-domain statement as the archived repo.

### Phase 3: Converter `shabados_sggs`

**Dependencies**: Phases 1–2.

#### Objective

One `Document`: `unit_type` `pankti`, citation `Ang N:k`, and text that is the
printed Granth without Shabad OS apparatus.

#### Files to Create / Modify

- `pipelines/sacredbench/convert.py`: `convert_shabados_sggs` plus one `CONVERTERS` line. Rules:
  - Remove vishraam `;` `.` `,`.
  - Rewrite `ਂ‍ੀ` (bindi, ZWJ, sihari-ii) to `ੀਂ`, and drop U+FE00.
  - Remove subscript digits U+2080–U+2089.
  - Remove numeric counters `॥<Gurmukhi digits>॥`, including chains like `॥੪॥੯॥੬੦॥`. Keep `ਰਹਾਉ`.
  - Collapse whitespace.
  - `k` is the 1-based position within the Ang in canonical order.
  - Drop dandas (decided in Phase 3: as separate tokens they inflate generate's word counts).
  - Correct two upstream Ang errors (`JJSV` 1337→1336, `V41B` 1377→1378), confirmed against
    BaniDB. Reading order comes from the sections, so these were the only Ang decreases.
- `pipelines/tests/test_schema_convert.py`: fixtures for two panktis on one physical line, a glued
  ZWJ vowel, a subscript heading, `॥੧॥ ਰਹਾਉ ॥`, the Mool Mantar, and a counter chain.
- `pipelines/tests/test_catalogue.py`: the real-tree target count goes from 21 to 22.
- A full-payload property test: for every line, raw text minus the declared apparatus equals the
  entry text. It is skipped only if the payload is absent, which it never is (the payload is
  committed).

#### Acceptance Criteria

- `convert` yields 60,555 panktis. Citations are unique; Angs run 1–1430.
- The property test passes over all 60,555 lines.
- No word is added, removed, or changed. The property test is the proof.

### Phase 4: Generate check, card counts, docs

**Dependencies**: Phase 3.

#### Objective

The Granth enters the default pool and fills 28 questions. Docs reflect the new tradition and the
Indic rule.

#### Files to Create / Modify

- `pipelines/tests/test_generate.py`: the Granth fills every template quota deterministically
  under a fixed seed. Expected pools: 1,452 entries ≥12 words, 100 ≥16. `verify_source` negatives
  fall back to cross-language, flagged.
- Card (`facct.py`), only if its census needs a field: pool sizes and the 20 repeated texts. Skip
  if the existing census already shows them.
- `texts/README.md`, `pipelines/README.md` (catalogue section), and `codev/resources/arch-critical.md`
  (the normalize bullet: add Gurmukhi/Devanagari next to Arabic/Hebrew).

#### Acceptance Criteria

- `generate` over the default pool includes the Granth with 28 questions.
- Committed runs are untouched: no `runs/**` file changes. Generation uses one RNG across texts in
  sorted order, and fakes draw from the whole pool, so adding a text changes other texts'
  questions. That is expected. The new manifest records the new pool and digest.
- The new question set is reproducible: generating twice with the same seed gives identical output.
- The copyright audit passes.

### Phase 5: Budgeted live smoke

**Dependencies**: Phases 1–4. **Get the architect's budget sign-off before spending.**

#### Objective

See the real path work: Gurmukhi prompt → model answer → score.

#### Deliverables

- A fresh `runs/<id>/` with one cheap model over the Granth's 28 questions only.
- A hand review of every scored cell: the verdict matches the answer. In particular, check that
  `contains_reference` credits a correct recital that differs only in vishraam or counters, and
  that a transliterated answer is classified as wrong-script.
- Decide with the user whether to commit the run as evidence. Per the copyright gate, it may be
  committed, because the source is public domain.

## Risks and Mitigation

| Risk | Mitigation |
|---|---|
| The Indic rule leaks outside its blocks and moves committed scores | Zero-move oracle in Phase 1; stop on any move. |
| Shabad OS has no explicit section order | The invariant check; the fallback sort is documented in the script. |
| Adding a text reshuffles other texts' questions, so pre/post runs are not comparable item by item | Expected. Compare runs per text, not per question. Per-text seeding is a later spec if the paper needs it. |
| 9 MB extract bloats the repo | Comparable to existing payloads (Sunni Islam 46 MB, Judaism 67 MB). |
