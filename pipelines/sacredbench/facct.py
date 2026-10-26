"""FAccT benchmark-card data (Spec 32). Reworked from PR #30 (Jonathan Karr).

Reads a finished run — ``scores.jsonl``, ``summary.json``, ``answers.jsonl`` and the question
``manifest`` — plus the catalogue, and assembles the card's machine-readable data:

1. the **run census** — who the questions represent, by tradition / language / document type /
   license, the catalogue source languages that contribute zero questions, and the texts excluded
   from the pool with the manifest's reason;
2. the three **outcomes** (``correct`` / ``incorrect`` / ``refused``) taken verbatim from the
   scoring contract (``metrics.outcome`` in ``scores.jsonl``); and
3. the Bible ``retrieve_quote`` **edition counterfactual** — incorrect cells whose answer contains
   some *other* indexed edition's wording of the same citation.

It never re-scores, never calls a model, and **fails fast** (``FacctError``, no partial data) on
inconsistent evidence. Outcomes come only from ``metrics.outcome`` (``outcomes.py`` is the single
refusal definition): there is no second refusal rule and no ``fabrication`` label here. The
counterfactual reuses ``score.bounded_contains`` + ``score.normalize`` — the exact containment
predicate behind the headline — never a private matcher.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from sacredbench import catalogue as cat
from sacredbench import generate as gen
from sacredbench import score
from sacredbench.edition_index import (
    EditionIndex,
    atomic_write_texts,
    index_documents,
    load_edition_documents,
    lookup_key,
)

_BIBLE = "The Bible"
_OUTCOMES = ("correct", "incorrect", "refused")


class FacctError(Exception):
    pass


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FacctError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FacctError(f"{path}: not readable JSON ({e})") from e


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FacctError(f"missing required file: {path}")
    rows: list[dict] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as e:
            raise FacctError(f"{path}: line {i + 1} is not valid JSON ({e})") from e
    return rows


def post_run_filter(targets, manifest: dict) -> list:
    """The catalogue targets that existed when ``manifest``'s run was generated: every
    restricted target (never in a manifest), plus each non-restricted target the manifest
    lists as selected or excluded. A non-restricted target it does not list came later."""
    known = {
        (st.get("work"), st.get("version"), st.get("language"))
        for st in (manifest.get("selected_texts") or []) + (manifest.get("excluded_texts") or [])
    }
    return [t for t in targets if t.license == "restricted" or t.text_key in known]


def _census(manifest: dict, raw_root: Path) -> dict:
    selected = manifest.get("selected_texts") or []
    excluded = manifest.get("excluded_texts") or []
    targets_by_key = {t.text_key: t for t in cat.all_targets(cat.discover_catalogue(raw_root))}

    texts: list[dict] = []
    by_tradition: Counter = Counter()
    by_language: Counter = Counter()
    by_document_type: Counter = Counter()
    by_license: Counter = Counter()
    for st in selected:
        key = (st.get("work"), st.get("version"), st.get("language"))
        target = targets_by_key.get(key)
        if target is None:
            raise FacctError(f"selected text {key} has no catalogue target")
        tradition = list(target.tradition)
        texts.append(
            {
                "work": target.work,
                "version": target.version,
                "language": target.language,
                "tradition": tradition,
                "document_type": target.document_type,
                "license": target.license,
            }
        )
        for trad in tradition:
            by_tradition[trad] += 1
        by_language[target.language] += 1
        by_document_type[target.document_type] += 1
        by_license[target.license] += 1

    # Languages present in the catalogue — as a target's language OR a text's canonical language —
    # that contribute zero questions to the pool. The canonical-language union surfaces e.g. Latin
    # (the encyclicals' canonical language, carried by no target's `language`), not only Greek.
    # Only the catalogue AS OF THIS RUN counts: generate records every non-restricted target as
    # selected or excluded, so a non-restricted target missing from the manifest was added later
    # (Spec 37's Guru Granth Sahib) and must not change a historic run's card.
    catalogue_languages = set()
    for t in post_run_filter(targets_by_key.values(), manifest):
        catalogue_languages.add(t.language)
        catalogue_languages.add(t.canonical_language)
    pool_languages = {st.get("language") for st in selected}
    zero_question_languages = sorted(catalogue_languages - pool_languages)

    return {
        "n_texts": len(texts),
        "n_questions": manifest.get("n_questions"),
        "selected_texts": texts,
        "by_tradition": dict(sorted(by_tradition.items())),
        "by_language": dict(sorted(by_language.items())),
        "by_document_type": dict(sorted(by_document_type.items())),
        "by_license": dict(sorted(by_license.items())),
        "excluded_texts": [
            {
                "work": e.get("work"),
                "version": e.get("version"),
                "language": e.get("language"),
                "reason": e.get("reason"),
            }
            for e in excluded
        ],
        "zero_question_languages": zero_question_languages,
    }


def _index_unique(rows: list[dict], kind: str) -> dict[tuple[str, str], dict]:
    """Index rows by ``(question_id, model_id)``, failing fast on a missing or duplicate key."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r.get("question_id"), r.get("model_id"))
        if key[0] is None or key[1] is None:
            raise FacctError(f"{kind} row missing question_id/model_id: {key}")
        if key in out:
            raise FacctError(f"duplicate {kind} row for {key}")
        out[key] = r
    return out


def _outcome_counts(scores: list[dict]) -> dict[tuple[str, str], Counter]:
    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for s in scores:
        task = s.get("task")
        if task is None:
            raise FacctError(f"score row {s.get('question_id')}/{s.get('model_id')} is missing 'task'")
        outcome = (s.get("metrics") or {}).get("outcome")
        if outcome not in _OUTCOMES:
            raise FacctError(
                f"score row {s.get('question_id')}/{s.get('model_id')} has unknown outcome {outcome!r}"
            )
        counts[(s["model_id"], task)][outcome] += 1
    return counts


def _verify_against_summary(counts: dict[tuple[str, str], Counter], summary: dict) -> None:
    """Both directions: the scores' (model, task) set must equal the summary's, every per-task
    outcome count must agree, and each model's ``_overall`` must equal the sum of its task counts —
    so neither an empty/short ``scores.jsonl`` nor a corrupted ``_overall`` can slip through."""
    models = summary.get("models") or {}
    score_keys = set(counts)
    summary_keys = {
        (model, task)
        for model, blocks in models.items()
        for task in blocks
        if task != "_overall"
    }
    if score_keys != summary_keys:
        raise FacctError(
            "scores.jsonl and summary.json cover different model/task sets: "
            f"only-in-scores={sorted(score_keys - summary_keys)}, "
            f"only-in-summary={sorted(summary_keys - score_keys)}"
        )
    for (model, task), c in counts.items():
        block = models[model][task]
        for outcome in _OUTCOMES:
            if int(block.get(outcome, 0)) != c[outcome]:
                raise FacctError(
                    f"scores.jsonl and summary.json disagree for {model}/{task} on {outcome}: "
                    f"scores={c[outcome]} summary={block.get(outcome)}"
                )
    for model in models:
        agg = Counter()
        for (m, _task), c in counts.items():
            if m == model:
                for outcome in _OUTCOMES:
                    agg[outcome] += c[outcome]
        overall = models[model].get("_overall") or {}
        for outcome in _OUTCOMES:
            if int(overall.get(outcome, 0)) != agg[outcome]:
                raise FacctError(
                    f"summary.json _overall for {model} disagrees with the summed task scores on "
                    f"{outcome}: _overall={overall.get(outcome)} scores={agg[outcome]}"
                )


def _rates(correct: int, incorrect: int, refused: int) -> dict:
    """accuracy = correct/(correct+incorrect); coverage = (correct+incorrect)/n — the Spec 15
    contract, recomputed from the verified counts so no rate is copied from summary.json."""
    answered = correct + incorrect
    n = answered + refused
    return {
        "correct": correct,
        "incorrect": incorrect,
        "refused": refused,
        "n": n,
        "accuracy": round(correct / answered, 4) if answered else 0.0,
        "coverage": round(answered / n, 4) if n else 0.0,
    }


def _outcomes(counts: dict[tuple[str, str], Counter], summary: dict) -> dict:
    # Every figure here is derived from the verified scores counts — counts AND rates — so nothing
    # is copied from summary.json (summary was only used to cross-check the counts).
    models = summary.get("models") or {}
    out: dict[str, dict] = {}
    for model in sorted(models):
        tasks = sorted(t for (m, t) in counts if m == model)
        by_task = {
            task: _rates(counts[(model, task)]["correct"], counts[(model, task)]["incorrect"],
                         counts[(model, task)]["refused"])
            for task in tasks
        }
        agg = {o: sum(by_task[t][o] for t in by_task) for o in _OUTCOMES}
        out[model] = {
            "by_task": by_task,
            "overall": _rates(agg["correct"], agg["incorrect"], agg["refused"]),
        }
    return out


def _counterfactual(
    scores: list[dict],
    ans_by: dict[tuple[str, str], dict],
    index: EditionIndex,
    selected_keys: set[tuple[str, str, str]],
) -> dict:
    per_model: dict[str, dict] = {}
    for model_id in {s.get("model_id") for s in scores}:
        per_model[model_id] = {"numerator": 0, "denominator": 0, "tagged": []}  # seed so 0-miss models show 0/0

    for s in scores:
        if s.get("task") != "retrieve_quote":
            continue
        if (s.get("metrics") or {}).get("outcome") != "incorrect":
            continue
        answer_row = ans_by[(s["question_id"], s["model_id"])]
        source = (answer_row.get("question") or {}).get("source") or {}
        if source.get("work") != _BIBLE:
            continue
        model = s["model_id"]
        per_model[model]["denominator"] += 1
        citation = source.get("citation") or ""
        language = source.get("language") or ""
        requested_version = source.get("version")
        # by_cite is keyed on (work, language, citation): the lookup is already scoped to this
        # question's work AND language, so a same-work different-language edition is never a candidate.
        key = lookup_key(source.get("work") or "", language, citation)
        if key is None:
            continue  # non-Bible-style citation: never matched to a Bible edition
        answer_text = answer_row.get("answer") or ""
        matched: list[str] = []
        for passage in index.by_cite.get(key, []):
            # only editions the RUN actually selected count (so adding a Bible edition to the
            # catalogue later cannot change this historic run's card), and never the requested one.
            if (passage.work, passage.version, passage.language) not in selected_keys:
                continue
            if passage.version == requested_version:  # the requested edition is not "another edition"
                continue
            if passage.version in matched or not score.normalize(passage.text):
                continue
            if score.bounded_contains(answer_text, passage.text):
                matched.append(passage.version)
        if matched:
            per_model[model]["numerator"] += 1
            per_model[model]["tagged"].append(
                {
                    "tag": "other_edition",
                    "question_id": s["question_id"],
                    "citation": citation,
                    "requested_version": requested_version,
                    "other_editions": sorted(matched),
                }
            )

    for block in per_model.values():
        block["tagged"].sort(key=lambda t: (t["citation"], t["question_id"]))
    return {m: per_model[m] for m in sorted(per_model)}


def build_facct(run_dir: Path, raw_root: Path = cat.RAW_ROOT) -> dict:
    """Assemble the FAccT card data for a finished run. Pure: no model call, no re-score, no write.

    Raises :class:`FacctError` (before any caller writes anything) on missing files, a score row
    that will not join to an answer row, an unresolved catalogue target, an unknown outcome, or a
    ``scores.jsonl`` ↔ ``summary.json`` count disagreement.
    """
    run_dir = Path(run_dir)
    scores = _load_jsonl(run_dir / "scores.jsonl")
    answers = _load_jsonl(run_dir / "answers.jsonl")
    summary = _load_json(run_dir / "summary.json")
    manifest = _load_json(run_dir / "questions.jsonl.manifest.json")

    ans_by = _index_unique(answers, "answer")
    score_by = _index_unique(scores, "score")
    if set(score_by) != set(ans_by):
        only_scores = sorted(set(score_by) - set(ans_by))
        only_answers = sorted(set(ans_by) - set(score_by))
        raise FacctError(
            f"scores.jsonl and answers.jsonl do not join one-to-one: "
            f"{len(only_scores)} score row(s) without an answer (e.g. {only_scores[:3]}), "
            f"{len(only_answers)} answer row(s) without a score (e.g. {only_answers[:3]})"
        )

    counts = _outcome_counts(scores)
    _verify_against_summary(counts, summary)

    manifest_n = manifest.get("n_questions")
    if manifest_n is not None:
        distinct_questions = len({qid for qid, _model in score_by})
        if int(manifest_n) != distinct_questions:
            raise FacctError(
                f"manifest n_questions={manifest_n} but scores.jsonl has {distinct_questions} "
                "distinct question_ids"
            )

    census = _census(manifest, raw_root)
    bible_editions = sorted(t["version"] for t in census["selected_texts"] if t["work"] == _BIBLE)
    scope = CARD_PROSE["counterfactual_scope_template"].format(
        n=len(bible_editions), versions=", ".join(bible_editions)
    )
    # the editions this run actually selected — the counterfactual considers only these, so a Bible
    # edition added to the catalogue later cannot change this historic run's card.
    selected_keys = {
        (t.get("work"), t.get("version"), t.get("language"))
        for t in (manifest.get("selected_texts") or [])
    }
    indexed_docs, all_nonrestricted, _excluded = load_edition_documents(raw_root)
    # `selected_corpus_hash` pins the counterfactual's raw-edition CONTENT to only the editions this
    # run selected: it changes iff a selected edition's wording changes (the committed-card regression
    # test then fails with a clear diff — remedy: regenerate the card), and is unaffected by unrelated
    # catalogue additions (a new drop-in tradition leaves a historic card buildable and byte-identical).
    # It is recorded, not enforced; the run's own `corpus_hash` stays a copy of the manifest value.
    selected_docs = [d for d in all_nonrestricted if (d.work, d.version, d.language) in selected_keys]
    selected_corpus_hash = gen.corpus_hash(selected_docs)
    index = index_documents(indexed_docs)
    return {
        "run": run_dir.name,
        "question_set_digest": manifest.get("question_set_digest"),
        "corpus_hash": manifest.get("corpus_hash"),
        "selected_corpus_hash": selected_corpus_hash,
        "panel": summary.get("panel", {}),
        "evaluators": summary.get("evaluators", []),
        "census": census,
        "outcomes": _outcomes(counts, summary),
        "edition_counterfactual": {
            "scope": scope,
            "bible_editions": bible_editions,
            "by_model": _counterfactual(scores, ans_by, index, selected_keys),
        },
    }


# ============================================================================================
# CARD PROSE — the one editable place.
#
# Jonathan Karr owns this wording while drafting the FAccT paper. Everything a reader reads as
# words (not numbers) lives in this block; it is deliberately separated from the counting logic
# above, which Jonathan does not need to touch. The markdown renderer below interpolates the
# numbers from the card data — no figure is ever typed into this prose, so the card cannot drift
# from the run it describes.
# ============================================================================================
CARD_PROSE = {
    "title_template": "FAccT benchmark card — {run}",
    "tagline": "What this benchmark run is allowed to mean — and what it is not.",
    # the task names glossed for a reader who has not read the pipeline (only the tasks actually
    # present in the run are rendered — the gloss list is not a fixed count)
    "tasks_heading": "The tasks",
    "tasks_intro": "Each question uses one of these tasks:",
    "task_glosses": {
        "retrieve_quote": "quote a named edition's exact wording of a citation",
        "complete_unit": "continue a verse or unit from its opening words",
        "cite_passage": "name the citation a quoted passage comes from",
        "verify_source": "judge whether a passage really is from a claimed source",
    },
    "panel_heading": "The panel",
    "panel_intro": (
        "The models behind the numbers, with any tools they were given — tool use is part of a "
        "model's identity here, so the same model with search on and off are different panellists."
    ),
    "panel_note": (
        "Provider is the API protocol the run used, not the model's maker — an `anthropic/…` model "
        "reached over an OpenAI-compatible endpoint shows provider `openai`; read Model ID and "
        "Endpoint for the real source."
    ),
    "tools_none": "none",
    "census_heading": "Who the questions represent",
    "census_intro": (
        "The questions are drawn from original-language editions only: a text is asked about just "
        "when the edition is in its own canonical language. The tables below are the make-up of the "
        "questions in this run — not a ranking of anyone's scripture, and not a measure of how well "
        "a model knows a faith."
    ),
    "census_count_template": "This run asked **{questions} questions** across **{texts} texts**.",
    "language_names": {"en": "English", "ar": "Arabic", "he": "Hebrew", "grc": "Greek", "la": "Latin",
                       "pa": "Punjabi"},
    "tradition_table_heading": "By tradition",
    "tradition_table_note": (
        "A text shared by more than one tradition is counted under each, so these can total more than "
        "the number of texts."
    ),
    "texts_table_heading": "The texts asked about",
    "zero_languages_label": "Languages with zero questions:",
    "zero_language_note": (
        "A language listed here is present in the catalogue but asked no questions in this run. It "
        "is a held-back or out-of-pool source, not a gap the models failed to cover."
    ),
    "excluded_label": "Excluded from the pool.",
    "excluded_note": (
        "These texts are in the catalogue but outside this run's pool, each for the stated reason "
        "(an edition whose language is not its canonical language)."
    ),
    "outcomes_heading": "What the models did",
    "outcomes_intro": (
        "Each answer is one of three outcomes: correct, incorrect, or a refusal. A refusal — the "
        "model declining to answer — is neither right nor wrong, so it is set aside: accuracy counts "
        "only answered questions, and coverage is the share of questions that were answered. A high "
        "accuracy on low coverage is not mastery; read the two together."
    ),
    "correctness_intro": "What counts as correct depends on the task:",
    "correctness_by_task": {
        "retrieve_quote": "the answer must *contain* the requested edition's wording",
        "complete_unit": "the continuation must *contain* the reference wording",
        "cite_passage": "the answer must name the one correct citation",
        "verify_source": "the answer must give the correct leading Yes / No",
    },
    "correctness_containment_note": (
        "For the two text-retrieval tasks, 'contain' is a word-bounded, script-aware match (graders: "
        "{evaluators}) — not an exact string match — the same match the edition question below uses."
    ),
    "overall_label": "overall",
    "counterfactual_heading": "Would another edition have passed?",
    "counterfactual_intro_template": (
        "{n} of the texts are different editions of the same Bible ({versions}). When a model was "
        "asked for one edition's wording of a verse and missed, it sometimes answered with a faithful "
        "wording of the *same verse from a different edition*. The count below is how many of those "
        "misses were really another edition of the right verse."
    ),
    "counterfactual_scope_label": "Scope:",
    "counterfactual_scope_template": (
        "Bible retrieve_quote cells only. complete_unit is excluded (its gold is a partial unit with "
        "no well-defined sibling-edition segment); the {n} Bible editions ({versions}) are the only "
        "sibling editions in the pool, and non-Bible citations (Arabic surah:ayah, hadith numbers, "
        "Talmud daf:line) are never matched to a Bible edition."
    ),
    "counterfactual_zero_note": (
        "A model shown 0 of 0 had no incorrect Bible retrieve_quote answers to reconsider."
    ),
    "claims_heading": "What this card claims",
    "claims": [
        "For this panel, on these original-language editions, the accuracy-with-coverage figures above "
        "are how often each model succeeded at each task — quoting the requested wording, completing a "
        "unit, naming a citation, or judging a source — with refusals set aside.",
        "Some Bible misses are edition mismatches, not wrong verses; the edition count says how many.",
    ],
    "failure_heading": "What would make this card wrong",
    "failure": [
        "If the scoring contract behind these outcomes changed and the card were not rebuilt from the "
        "new scores, every number here would be stale.",
        "If a citation were matched to an edition it does not belong to, the edition count would be "
        "inflated; the count is computed for Bible verse citations only, for exactly this reason.",
    ],
    "non_conclusions_heading": "What this card does not conclude",
    "non_conclusions": [
        "It does not rank traditions and does not measure knowledge of any faith.",
        "A tradition's row is the slice that was asked — which may be a hadith collection or an "
        "English-language question set — not that community's whole scripture.",
        "The edition count is reported for the English Bible editions only; the other texts have no "
        "second indexed edition in this run, so the question does not arise for them.",
    ],
    "review_heading": "Community review",
    "review_note": (
        "Scholar and community review of this card is not attached. The card reports what the run "
        "measured; it is not an adjudication by any tradition."
    ),
    # table column headers (reader-facing labels, kept here so all wording is in one place)
    "headers": {
        "panel": ["Model", "Provider", "Model ID", "Tools", "Endpoint"],
        "tradition": ["Tradition", "Texts"],
        "texts": ["Text", "Language", "Tradition", "Type", "License"],
        "outcomes": ["Model", "Task", "Correct", "Incorrect", "Refused", "Accuracy", "Coverage"],
        "counterfactual": ["Model", "Another edition would have passed", "Of incorrect Bible retrieve_quote"],
    },
}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{round(x * 100, 1)}%"


def _n(x) -> str:
    return "—" if x is None else f"{x:,}"


def _lang(code: str) -> str:
    """Human language name with its ISO code, e.g. ``Hebrew (he)`` (code alone if unknown)."""
    name = CARD_PROSE["language_names"].get(code)
    return f"{name} ({code})" if name else code


def _table(headers: list[str], rows: list[list[str]], aligns: list[str] | None = None) -> list[str]:
    aligns = aligns or ["---"] * len(headers)
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(aligns) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def report_markdown(report: dict) -> str:
    """Render the human-readable card from the card data. Every number comes from ``report``
    (which is derived from ``scores.jsonl`` / ``summary.json``); all wording comes from
    :data:`CARD_PROSE`. No figure is typed into the prose, so the card cannot drift from the run."""
    p = CARD_PROSE
    census = report["census"]
    cf = report["edition_counterfactual"]
    bibles = cf["bible_editions"]
    lines: list[str] = [f"# {p['title_template'].format(run=report['run'])}", "",
                        f"*{p['tagline']}*", ""]

    # --- panel ---
    panel = report.get("panel") or {}
    if panel:
        lines += [f"## {p['panel_heading']}", "", p["panel_intro"], ""]
        panel_rows = [
            [model, info.get("provider", "—"), info.get("model", "—"),
             ", ".join(info.get("tools") or []) or p["tools_none"], info.get("endpoint", "—")]
            for model, info in panel.items()
        ]
        lines += _table(p["headers"]["panel"], panel_rows)
        lines += ["", f"*{p['panel_note']}*", ""]

    # --- tasks gloss (only the tasks actually present in the run) ---
    present_tasks = sorted({task for block in report["outcomes"].values() for task in block["by_task"]})
    if present_tasks:
        lines += [f"## {p['tasks_heading']}", "", p["tasks_intro"], ""]
        for task in present_tasks:
            gloss = p["task_glosses"].get(task)
            lines.append(f"- **{task}**" + (f" — {gloss}" if gloss else ""))
        lines.append("")

    # --- census ---
    lines += [f"## {p['census_heading']}", "", p["census_intro"], ""]
    lines += [p["census_count_template"].format(questions=_n(census["n_questions"]),
                                                texts=_n(census["n_texts"])), ""]
    lines += [f"**{p['tradition_table_heading']}**", ""]
    lines += _table(p["headers"]["tradition"],
                    [[t, c] for t, c in census["by_tradition"].items()], ["---", "---:"])
    lines += ["", f"*{p['tradition_table_note']}*", ""]
    lines += [f"**{p['texts_table_heading']}**", ""]
    lines += _table(
        p["headers"]["texts"],
        [[f"{t['work']} ({t['version']})", _lang(t["language"]), ", ".join(t["tradition"]),
          t["document_type"], t["license"]] for t in census["selected_texts"]],
    )
    lines.append("")
    if census["zero_question_languages"]:
        names = ", ".join(_lang(c) for c in census["zero_question_languages"])
        lines += [f"**{p['zero_languages_label']}** {names}. " + p["zero_language_note"], ""]
    if census["excluded_texts"]:
        lines += [f"**{p['excluded_label']}** {p['excluded_note']}", ""]
        for e in census["excluded_texts"]:
            lines.append(f"- {e['work']} ({e['version']}, {e['language']}) — {e['reason']}")
        lines.append("")

    # --- outcomes ---
    lines += [f"## {p['outcomes_heading']}", "", p["outcomes_intro"], ""]
    lines += [p["correctness_intro"], ""]
    for task in present_tasks:  # per-task correctness rule, only for tasks present
        rule = p["correctness_by_task"].get(task)
        if rule:
            lines.append(f"- **{task}** — {rule}")
    lines += ["", p["correctness_containment_note"].format(
        evaluators=", ".join(report.get("evaluators") or [])), ""]
    rows: list[list[str]] = []
    for model, block in report["outcomes"].items():
        for task, t in block["by_task"].items():
            rows.append([model, task, t["correct"], t["incorrect"], t["refused"],
                         _pct(t["accuracy"]), _pct(t["coverage"])])
        o = block["overall"]
        rows.append([model, f"**{p['overall_label']}**", o["correct"], o["incorrect"], o["refused"],
                     f"**{_pct(o['accuracy'])}**", f"**{_pct(o['coverage'])}**"])
    lines += _table(p["headers"]["outcomes"], rows,
                    ["---", "---", "---:", "---:", "---:", "---:", "---:"])
    lines.append("")

    # --- edition counterfactual ---
    lines += [f"## {p['counterfactual_heading']}", ""]
    lines += [p["counterfactual_intro_template"].format(n=len(bibles), versions=", ".join(bibles)), ""]
    lines += _table(p["headers"]["counterfactual"],
                    [[m, b["numerator"], b["denominator"]] for m, b in cf["by_model"].items()],
                    ["---", "---:", "---:"])
    lines.append("")
    if any(b["denominator"] == 0 for b in cf["by_model"].values()):
        lines += [p["counterfactual_zero_note"], ""]
    lines += [f"*{p['counterfactual_scope_label']} {cf['scope']}*", ""]

    # --- prose sections ---
    for heading, items in ((p["claims_heading"], p["claims"]),
                           (p["failure_heading"], p["failure"]),
                           (p["non_conclusions_heading"], p["non_conclusions"])):
        lines += [f"## {heading}", ""]
        lines += [f"- {item}" for item in items]
        lines.append("")
    lines += [f"## {p['review_heading']}", "", p["review_note"], ""]

    return "\n".join(lines)


def write_card(report: dict, json_path: Path, md_path: Path) -> None:
    """Write ``facct.json`` and ``facct.md`` atomically — both or neither.

    Both files are rendered in memory first, then written through the shared
    :func:`edition_index.atomic_write_texts` (collision-safe temps, swap-all, rollback on failure),
    so a failure never leaves a fresh file beside a stale one.
    """
    atomic_write_texts([
        (Path(json_path), json.dumps(report, ensure_ascii=False, indent=1) + "\n"),
        (Path(md_path), report_markdown(report)),
    ])
