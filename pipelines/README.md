# pipelines — sacredbench

The Phase 1 benchmark pipeline (spec: `codev/specs/1-phase1-benchmark-pipeline.md`).
One `uv` project, Typer CLI, JSONL seams between stages, fail-fast throughout.
Provider layer ported from multibench `workflows/judging/judging/providers.py`
@ 14f6c9d4.

```
source JSON ──convert──▶ standard docs ──generate──▶ questions.jsonl
questions.jsonl × model panel ──collect──▶ answers.jsonl ──score──▶ scores.jsonl + summary
```

## Source catalogue (`texts/raw/**/source.yaml`)

`texts/raw` is grouped **one directory per tradition**, each holding many works,
versions, and source shapes. Every tradition directory carries one committed
`source.yaml` — a *targets manifest*: shared provenance plus a `targets:` list,
where each target is one `(work, version, language)` unit with its `payload`
glob, `converter`, `tradition[]`, `license`, and (Spec 26) `requested_as` and
`canonical_language`. See `pipelines/sacredbench/catalogue.py` for the schema;
loading is fail-fast.

- **`license`** is a three-value gate: `public-domain` / `open` / `restricted`
  (the real upstream string, e.g. the Talmud's `CC-BY-NC`, is kept verbatim in
  `license_detail`). `restricted` targets are copyrighted texts whose
  **payloads are git-ignored and local-only** — NABRE (an English translation) and the
  Greek Orthodox TLG extracts (an original-language Greek edition); their `source.yaml` is
  still committed so the catalogue stays complete and auditable.
- **`requested_as`** is the non-empty list of names a person actually uses for this edition
  (e.g. `["King James Version", "KJV", "KJV Bible"]`); `generate` renders `<edition>` in the
  prompt as a seeded choice from it, never the raw `version`. **`canonical_language`** is the
  language the benchmark treats as the text's own (usually the language of composition); a text
  is in the default question pool only when **`language == canonical_language`**, so most
  translations — Talmud English, the Vatican English encyclicals — are excluded and recorded in
  the manifest with a reason. **Exception (working-group policy, issue #27 Q1):** the English
  Bibles (KJV/ASV/WEB) are translations but carry `canonical_language: en` so they stay in the
  pool; the Qur'an (`ar`), Talmud Aramaic (`he`), TLG Greek (`grc`) and the Sri Guru Granth Sahib
  (`pa`, Gurmukhi; Spec 37) are genuine originals.
- `convert` and `generate` **exclude `restricted` targets by default**; pass
  `--include-restricted` to opt in (and supply the local payload). `validate` is
  unaffected by license.
- **Standardized-path convention:** a target's converted output lives under
  `texts/standardized/<source-id>/<target-slug>/` mirroring
  `texts/raw/<source-id>`, so `generate` recovers a document's `license` **and** its text
  metadata (`requested_as` / `canonical_language`) from its path. The interchange `Document`
  format is unchanged (it carries neither).

```bash
# Validate the whole catalogue and list the selected (non-restricted) targets
uv --project pipelines run python -m sacredbench catalogue
uv --project pipelines run python -m sacredbench catalogue --include-restricted
```

Run everything from the **repo root**:

```bash
uv --project pipelines run python -m sacredbench --help

# 1. Convert catalogue targets into the standard flat format. This is
#    catalogue-driven: every selected target is converted via its registered
#    converter and written under the standardized-path convention
#      texts/standardized/<source-id>/<target-slug>/
#    so `generate` can recover each document's license from its path. Restricted
#    targets are excluded unless --include-restricted is passed.
uv --project pipelines run python -m sacredbench convert                 # all selected targets
uv --project pipelines run python -m sacredbench convert --converter bible_flat    # just one converter
uv --project pipelines run python -m sacredbench convert --source "Protestant Christian"
# Restricted targets (require the local held-back payloads, e.g. NABRE):
uv --project pipelines run python -m sacredbench convert --include-restricted
# NOTE: with the Greek Orthodox TLG payloads present locally, a whole-corpus
#   `convert --include-restricted` fail-fasts on the still-unregistered `tlg`
#   converter. Until that converter lands, convert NABRE on its own:
uv --project pipelines run python -m sacredbench convert --include-restricted --source "Roman Catholic"
#   (verified 2026-10-11: NABRE converts 35,091 verses; the committed run's audit
#    content layer ran clean against the real NABRE payload — 32,070 fingerprints.)

# 2. Mechanically validate any standard-format documents (license-agnostic)
uv --project pipelines run python -m sacredbench validate texts/standardized

# 2b. (Optional) Assemble the working group's interchange document per
#     (work, version, language): merges shards (e.g. the dozens of per-tractate
#     Talmud Bavli Aramaic files into one document), dedupes by (citation, text),
#     unions traditions, and checks the inverse-grouping round-trip before writing
#     texts/interchange/ (rebuildable, gitignored).
uv --project pipelines run python -m sacredbench export texts/standardized

# 3. Generate questions (four working-group templates; deterministic; original-language-only
#    by default). A text (one work/version/language group) is in the pool iff
#    language == canonical_language; excluded texts are recorded in the manifest with a
#    reason (there is no --include-translations). Each in-pool text gets --per-text questions
#    (default 28) split over the active templates. verify_source false-premise negatives are
#    drawn cross-family (hadith collections are one family), same-language preferred. Inputs
#    are standardized docs under texts/standardized; restricted docs are excluded (opt in with
#    --include-restricted), and a doc whose license/metadata can't be recovered from its path
#    is refused (fail-closed).
uv --project pipelines run python -m sacredbench generate texts/standardized --per-text 28

# 4. Collect answers from the model panel (resumable; non-zero exit on failures).
#    `generate` also writes runs/questions.jsonl.manifest.json (seed, params,
#    corpus hash, question-set digest). collect stamps that digest into every
#    answer row and REFUSES to resume an answers file built for a different
#    question set (regenerate, or point --out at a fresh file); score refuses a
#    file that mixes question sets.
cp configs/models.example.yaml configs/models.yaml   # then edit; keys via env
uv --project pipelines run python -m sacredbench collect runs/questions.jsonl configs/models.yaml

# 5. Score and print the summary. Per-task contract: retrieve_quote/complete_unit
#    -> the OR of the SELECTED named graders' verdicts (default `strict` + `containment`
#    => `normalized OR contains_reference`; pick a subset with `--evaluator strict` /
#    `--evaluator containment`; a paid/separate-pass grader is expressible, never default
#    -> issue #21); verify_source -> the LEADING-stance Yes/No equals expected (Spec 26: a
#    buried/negation-evasion verdict is refused, not correct — #23 closed);
#    cite_passage -> the SINGLE extracted citation must equal ground truth (a multi-candidate
#    hedge scores 0). Every answered cell also gets an OUTCOME (correct/incorrect/refused): a
#    decline is `refused` and excluded from `accuracy = correct/(correct+incorrect)`, with
#    `coverage = (correct+incorrect)/n` reported beside it. The summary breaks down per model x
#    task x TRADITION and per model x TEXT (one text = one work/version/language). Optional flags:
#      --summary-md PATH            also write the markdown summary (Phase 8 evidence)
#      --questions Q --config CFG   report missing/failed cells against the panel x
#                                   question-set roster (expected_n / 'miss N')
uv --project pipelines run python -m sacredbench score runs/answers.jsonl \
    --questions runs/questions.jsonl --config configs/models.yaml --summary-md runs/summary.md
#    The summary also carries a `panel` block (provider, model (the raw API id), the
#    `tools` list (e.g. `["web_search"]`; `[]` when off), endpoint, and `served_by` host(s);
#    no secrets, so the >=3-model / >=2-provider bar is checkable from the committed artifact)
#    and a `usage` block (per-model + total input/output tokens; cost only if the
#    run config supplies per-model prices — prices are never invented).

# 6. Copyright audit (runs in the test gate): fail if any committed artifact is
#    derived from a restricted source. Two layers: ORIGIN (always) — the artifact's
#    (work, version, language) maps to a restricted catalogue target; and CONTENT —
#    when the held-back restricted PAYLOADS are present locally, the restricted unit
#    texts are fingerprinted and any committed file containing one is flagged (this
#    catches a restricted unit mislabeled with a public source). In CI / a fresh
#    clone the payloads are absent, so only the origin layer runs — acceptable
#    because restricted payloads are never committed, making origin the enforceable
#    proxy there.
uv --project pipelines run python -m sacredbench audit runs/ texts/standardized

# 7. Edition index (Spec 32): export the editions that share a citation, for the
#    FAccT card's cross-edition reading (in-process) and issue #21 (via the file).
#    One row per (work, citation, language) with >=2 wordings; same-canonical-language
#    editions only; restricted editions (NABRE, TLG) are never indexed. Writes JSONL +
#    a sibling .manifest.json (corpus_hash, row_count, digest, excluded_restricted).
uv --project pipelines run python -m sacredbench edition-index --out texts/edition_index.jsonl

# 8. FAccT benchmark card (Spec 32): read a finished run and write facct.json + facct.md
#    beside it — the run census (who the questions represent), the three outcomes taken
#    verbatim from scores.jsonl, and the Bible retrieve_quote edition counterfactual. Pure
#    analysis: never re-scores, never calls a model; every number is derived from the run.
uv --project pipelines run python -m sacredbench facct runs/<id>
```

Tests: `uv --project pipelines run pytest pipelines` (fixtures are real-SHAPE but
synthetic TEXT — no copyrighted translation is committed).

Module map: `catalogue.py` `source.yaml` targets manifest + discovery + license
gating · `schema.py` standard format + validation · `convert.py` source-format
converters (registry) · `export.py` assemble shards → interchange + round-trip ·
`generate.py` templates → questions · `config.py` model
panel YAML · `providers.py` anthropic/openai-compatible/gemini seam ·
`collect.py` resumable fan-out · `score.py` metrics + summary (panel + usage) ·
`audit.py` restricted-origin/-content copyright audit · `jev.py` paid Jev judge
(Decisions API) → resumable sidecar, diagnostic only, never rescoring · `cli.py` Typer app.

Verified live (2026-10-10): 3-question smoke vs claude-haiku-5-5 — collect and
score worked end-to-end; Haiku returned a near-miss paraphrase of Luke 19:17
(NABRE) that scored exact=0/normalized=0/token_f1=0.62, exactly the failure mode
the benchmark exists to measure.
