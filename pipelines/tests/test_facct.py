"""FAccT card data (Spec 32, Phase 2).

Outcome fidelity (counts == scores.jsonl == summary.json), the Bible retrieve_quote edition
counterfactual (numerator/denominator/tags, complete_unit excluded, non-Bible never matched,
requested edition not tagged), fail-fast on inconsistent evidence, and the no-fabrication /
no-private-matcher regressions. The counterfactual reuses score.bounded_contains verbatim.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from textwrap import dedent

import pytest

from typer.testing import CliRunner

from sacredbench import facct as facct_mod
from sacredbench import generate as gen
from sacredbench.cli import app
from sacredbench.edition_index import load_edition_documents
from sacredbench.facct import FacctError, build_facct, report_markdown, write_card


def _corpus_hash(root: Path) -> str:
    """generate's corpus hash over the fixture's full non-restricted set — what build_facct pins the
    run manifest's corpus_hash against."""
    _indexed, all_docs, _excl = load_edition_documents(root / "texts" / "raw")
    return gen.corpus_hash(all_docs)

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]

PROV = (
    "provenance:\n"
    "  retrieved_from: example.org/repo\n"
    "  fetch_method: downloaded\n"
    '  fetch_date: "2026-01-01"\n'
)

# Three fixture Bible editions with deliberately disjoint wordings for Test 1:1, so a WEB
# answer to an ASV-requested citation is a clean other_edition match.
_KJV = {"Test 1:1": "alpha beta gamma delta", "Test 2:2": "mkjv two two unique",
        "Test 3:3": "kjv three correct text", "Test 5:5": "kjv five five words",
        "Test 6:6": "kjv six six alpha"}
_ASV = {"Test 1:1": "epsilon zeta eta theta", "Test 5:5": "asv five five words",
        "Test 6:6": "asv six six beta"}
_WEB = {"Test 1:1": "iota kappa lambda mu", "Test 5:5": "web five five words",
        "Test 6:6": "web six six gamma"}


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")
    return path


def _bible_payload(verses: dict[str, str]) -> str:
    rows = []
    for cite, text in verses.items():
        book, cv = cite.rsplit(" ", 1)
        ch, vs = cv.split(":")
        rows.append({"book": book, "chapter": int(ch), "verse": int(vs), "text": text})
    return json.dumps(rows)


def _raw_tree(root: Path) -> Path:
    raw = root / "texts" / "raw"
    base = (
        "    converter: bible_flat\n"
        "    work: The Bible\n"
        "    language: en\n"
        "    document_type: scripture\n"
        "    tradition: [Protestant Christian]\n"
        "    license: public-domain\n"
        "    requested_as: [the Bible]\n"
        "    canonical_language: en\n"
    )
    _write(
        raw / "Protestant Christian" / "source.yaml",
        PROV + "targets:\n"
        "  - payload: kjv.json\n    version: KJV\n" + base
        + "  - payload: asv.json\n    version: ASV (1901)\n" + base
        + "  - payload: web.json\n    version: WEB\n" + base,
    )
    _write(raw / "Protestant Christian" / "kjv.json", _bible_payload(_KJV))
    _write(raw / "Protestant Christian" / "asv.json", _bible_payload(_ASV))
    _write(raw / "Protestant Christian" / "web.json", _bible_payload(_WEB))
    return raw


# (task, work, version, language, citation, answer, outcome)
_CELLS = [
    ("retrieve_quote", "The Bible", "ASV (1901)", "en", "Test 1:1", "the verse is iota kappa lambda mu", "incorrect"),  # -> tag WEB
    ("retrieve_quote", "The Bible", "KJV", "en", "Test 2:2", "nothing matching at all here", "incorrect"),  # no tag
    ("retrieve_quote", "The Bible", "KJV", "en", "Test 3:3", "kjv three correct text", "correct"),
    ("complete_unit", "The Bible", "ASV (1901)", "en", "Test 1:1", "iota kappa lambda mu", "incorrect"),  # excluded (complete_unit)
    ("retrieve_quote", "The Qur'an", "Uthmani", "ar", "2:255", "a wrong answer", "incorrect"),  # non-Bible, not matched
    ("retrieve_quote", "The Bible", "WEB", "en", "Test 5:5", "I cannot provide that", "refused"),
    # answer carries ONLY the REQUESTED edition's wording (KJV) -> must NOT be tagged other_edition
    ("retrieve_quote", "The Bible", "KJV", "en", "Test 6:6", "kjv six six alpha", "incorrect"),
]


def _make_run(root: Path, *, model: str = "m1") -> Path:
    run = root / "runs" / "fixture"
    answers, scores = [], []
    for i, (task, work, version, language, citation, answer, outcome) in enumerate(_CELLS):
        qid = f"{task}-{i:04d}"
        answers.append({
            "question_id": qid, "model_id": model, "task": task, "answer": answer,
            "question": {
                "id": qid, "task": task, "prompt": "p",
                "expected": {"text": "gold"},
                "source": {"tradition": ["T"], "work": work, "version": version,
                           "language": language, "document_type": "scripture", "citation": citation},
            },
        })
        scores.append({"question_id": qid, "model_id": model, "task": task,
                       "metrics": {"correct": int(outcome == "correct"), "outcome": outcome}})

    # summary.json counts derived from the cells so they agree by construction
    by_task: dict[str, dict] = {}
    for (task, *_rest), s in zip(_CELLS, scores):
        b = by_task.setdefault(task, {"correct": 0, "incorrect": 0, "refused": 0})
        b[s["metrics"]["outcome"]] += 1
    for b in by_task.values():
        answered = b["correct"] + b["incorrect"]
        n = answered + b["refused"]
        b["n"] = n
        b["accuracy"] = round(b["correct"] / answered, 4) if answered else 0.0
        b["coverage"] = round(answered / n, 4) if n else 0.0
    tot = {"correct": sum(b["correct"] for b in by_task.values()),
           "incorrect": sum(b["incorrect"] for b in by_task.values()),
           "refused": sum(b["refused"] for b in by_task.values())}
    answered = tot["correct"] + tot["incorrect"]
    tot["n"] = answered + tot["refused"]
    tot["accuracy"] = round(tot["correct"] / answered, 4) if answered else 0.0
    tot["coverage"] = round(answered / tot["n"], 4) if tot["n"] else 0.0
    summary = {
        "models": {model: {**by_task, "_overall": tot}},
        "panel": {model: {"provider": "p", "model": "m", "tools": []}},
        "evaluators": ["strict", "containment"],
    }
    manifest = {
        "question_set_digest": "deadbeef",
        "corpus_hash": _corpus_hash(root),  # must match build_facct's hash of the fixture raw tree
        "n_questions": len(_CELLS),
        "selected_texts": [
            {"work": "The Bible", "version": "KJV", "language": "en"},
            {"work": "The Bible", "version": "ASV (1901)", "language": "en"},
            {"work": "The Bible", "version": "WEB", "language": "en"},
        ],
        "excluded_texts": [
            {"work": "Papal Encyclicals", "version": "Vatican English", "language": "en",
             "reason": "language 'en' != canonical_language 'la'"},
        ],
    }
    _write(run / "answers.jsonl", "\n".join(json.dumps(r) for r in answers) + "\n")
    _write(run / "scores.jsonl", "\n".join(json.dumps(r) for r in scores) + "\n")
    _write(run / "summary.json", json.dumps(summary))
    _write(run / "questions.jsonl.manifest.json", json.dumps(manifest))
    return run


def _build(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    return build_facct(run, raw_root=raw), run, raw


# --- census ------------------------------------------------------------------


def test_census(tmp_path):
    report, _run, _raw = _build(tmp_path)
    c = report["census"]
    assert c["n_texts"] == 3 and c["n_questions"] == 7
    assert c["by_tradition"] == {"Protestant Christian": 3}
    assert c["by_language"] == {"en": 3}
    assert c["by_license"] == {"public-domain": 3}
    assert c["by_document_type"] == {"scripture": 3}
    assert c["excluded_texts"] == [
        {"work": "Papal Encyclicals", "version": "Vatican English", "language": "en",
         "reason": "language 'en' != canonical_language 'la'"}
    ]
    assert {t["version"] for t in c["selected_texts"]} == {"KJV", "ASV (1901)", "WEB"}


# --- outcomes ----------------------------------------------------------------


def test_outcome_counts_match_scores(tmp_path):
    report, _run, _raw = _build(tmp_path)
    rq = report["outcomes"]["m1"]["by_task"]["retrieve_quote"]
    assert (rq["correct"], rq["incorrect"], rq["refused"]) == (1, 4, 1)
    cu = report["outcomes"]["m1"]["by_task"]["complete_unit"]
    assert (cu["correct"], cu["incorrect"], cu["refused"]) == (0, 1, 0)
    ov = report["outcomes"]["m1"]["overall"]
    assert (ov["correct"], ov["incorrect"], ov["refused"]) == (1, 5, 1)
    assert ov["n"] == 7


def _run_with_unselected_editions(root: Path) -> tuple[Path, Path]:
    """A raw tree + run where the catalogue holds a 4th English Bible and a Spanish Bible that are
    NOT in the run's selected_texts, used to prove the counterfactual ignores them (BLOCKING 2)."""
    raw = root / "texts" / "raw"
    base = ("    converter: bible_flat\n    work: The Bible\n    document_type: scripture\n"
            "    tradition: [Protestant Christian]\n    license: public-domain\n"
            "    requested_as: [the Bible]\n")
    _write(
        raw / "Bibles" / "source.yaml",
        PROV + "targets:\n"
        "  - payload: kjv.json\n    version: KJV\n    language: en\n" + base + "    canonical_language: en\n"
        "  - payload: asv.json\n    version: ASV (1901)\n    language: en\n" + base + "    canonical_language: en\n"
        "  - payload: fourth.json\n    version: FOURTH\n    language: en\n" + base + "    canonical_language: en\n"
        "  - payload: rvr.json\n    version: RVR\n    language: es\n" + base + "    canonical_language: es\n",
    )
    _write(raw / "Bibles" / "kjv.json", _bible_payload({"Gen 1:1": "kjv one one", "Gen 1:2": "kjv one two"}))
    _write(raw / "Bibles" / "asv.json", _bible_payload({"Gen 1:1": "asv one one", "Gen 1:2": "asv one two"}))
    _write(raw / "Bibles" / "fourth.json", _bible_payload({"Gen 1:1": "fourth one one"}))
    _write(raw / "Bibles" / "rvr.json", _bible_payload({"Gen 1:2": "spanish uno dos"}))

    # all requested KJV, all incorrect; answers carry a NON-selected edition (c1 FOURTH, c2 Spanish)
    # and one SELECTED edition (c3 ASV) as the positive control.
    cells = [
        ("Gen 1:1", "the answer is fourth one one"),   # FOURTH not in selected -> not tagged
        ("Gen 1:2", "it reads spanish uno dos"),        # Spanish (es) different language -> not tagged
        ("Gen 1:2", "it reads asv one two"),            # ASV selected, different edition -> tagged
    ]
    answers, scores = [], []
    for i, (citation, answer) in enumerate(cells):
        qid = f"retrieve_quote-{i:04d}"
        answers.append({"question_id": qid, "model_id": "m1", "task": "retrieve_quote", "answer": answer,
                        "question": {"id": qid, "task": "retrieve_quote", "prompt": "p",
                                     "expected": {"text": "gold"},
                                     "source": {"tradition": ["Protestant Christian"], "work": "The Bible",
                                                "version": "KJV", "language": "en",
                                                "document_type": "scripture", "citation": citation}}})
        scores.append({"question_id": qid, "model_id": "m1", "task": "retrieve_quote",
                       "metrics": {"correct": 0, "outcome": "incorrect"}})
    summary = {"models": {"m1": {"retrieve_quote": {"correct": 0, "incorrect": 3, "refused": 0, "n": 3,
                                                    "accuracy": 0.0, "coverage": 1.0},
                                 "_overall": {"correct": 0, "incorrect": 3, "refused": 0, "n": 3,
                                              "accuracy": 0.0, "coverage": 1.0}}},
               "panel": {"m1": {"provider": "p", "model": "m", "tools": []}},
               "evaluators": ["strict", "containment"]}
    manifest = {"question_set_digest": "d", "corpus_hash": _corpus_hash(root), "n_questions": 3,
                "selected_texts": [{"work": "The Bible", "version": "KJV", "language": "en"},
                                   {"work": "The Bible", "version": "ASV (1901)", "language": "en"}],
                "excluded_texts": []}
    run = root / "runs" / "excl"
    _write(run / "answers.jsonl", "\n".join(json.dumps(r) for r in answers) + "\n")
    _write(run / "scores.jsonl", "\n".join(json.dumps(r) for r in scores) + "\n")
    _write(run / "summary.json", json.dumps(summary))
    _write(run / "questions.jsonl.manifest.json", json.dumps(manifest))
    return run, raw


def test_counterfactual_counts_only_run_selected_editions(tmp_path):
    run, raw = _run_with_unselected_editions(tmp_path)
    block = build_facct(run, raw_root=raw)["edition_counterfactual"]["by_model"]["m1"]
    assert block["denominator"] == 3  # all three are incorrect Bible retrieve_quote cells
    assert block["numerator"] == 1    # only the ASV (selected) answer is rescued
    assert len(block["tagged"]) == 1
    tag = block["tagged"][0]
    assert tag["citation"] == "Gen 1:2" and tag["other_editions"] == ["ASV (1901)"]
    # the 4th English Bible (not selected) and the Spanish edition (other language) never appear
    all_tagged = json.dumps(block["tagged"])
    assert "FOURTH" not in all_tagged and "RVR" not in all_tagged


# --- edition counterfactual --------------------------------------------------


def test_counterfactual(tmp_path):
    report, _run, _raw = _build(tmp_path)
    block = report["edition_counterfactual"]["by_model"]["m1"]
    # denominator = incorrect Bible retrieve_quote = Test 1:1 (ASV) + Test 2:2 (KJV) + Test 6:6 (KJV) = 3
    #   (the Qur'an cell is non-Bible; complete_unit is excluded; Test 3:3 correct; Test 5:5 refused)
    assert block["denominator"] == 3
    assert block["numerator"] == 1
    assert len(block["tagged"]) == 1
    tag = block["tagged"][0]
    assert tag["tag"] == "other_edition"
    assert tag["citation"] == "Test 1:1"
    assert tag["requested_version"] == "ASV (1901)"
    assert tag["other_editions"] == ["WEB"]  # requested ASV excluded; KJV wording not in the answer


def test_requested_edition_only_answer_not_tagged(tmp_path):
    report, _run, _raw = _build(tmp_path)
    block = report["edition_counterfactual"]["by_model"]["m1"]
    # the Test 6:6 cell (KJV requested, answer is exactly the KJV wording) is an incorrect Bible
    # retrieve_quote cell -> it IS in the denominator, but the requested edition is never counted
    # as "another edition", so it is NOT tagged. (Deleting the version==requested guard breaks this.)
    assert "Test 6:6" not in {t["citation"] for t in block["tagged"]}
    assert block["denominator"] == 3 and block["numerator"] == 1


def test_complete_unit_and_non_bible_excluded(tmp_path):
    report, _run, _raw = _build(tmp_path)
    tagged = report["edition_counterfactual"]["by_model"]["m1"]["tagged"]
    # the complete_unit cell (also Test 1:1 / ASV, WEB wording in its answer) is never tagged
    assert all(t["citation"] != "Test 1:1" or t["requested_version"] == "ASV (1901)" for t in tagged)
    assert len(tagged) == 1  # only the retrieve_quote one
    # and the Qur'an 2:255 cell contributes nothing (non-Bible)
    assert report["edition_counterfactual"]["by_model"]["m1"]["denominator"] == 3


def test_scope_note_mentions_bible_retrieve_quote_only(tmp_path):
    report, _run, _raw = _build(tmp_path)
    scope = report["edition_counterfactual"]["scope"].lower()
    assert "retrieve_quote" in scope and "complete_unit" in scope


# --- fail-fast ---------------------------------------------------------------


def test_missing_file_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    (run / "summary.json").unlink()
    with pytest.raises(FacctError, match="missing required file"):
        build_facct(run, raw_root=raw)


def test_non_joining_score_row_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    with (run / "scores.jsonl").open("a") as f:
        f.write(json.dumps({"question_id": "ghost", "model_id": "m1", "task": "retrieve_quote",
                            "metrics": {"outcome": "correct"}}) + "\n")
    with pytest.raises(FacctError, match="without an answer"):
        build_facct(run, raw_root=raw)


def test_scores_summary_disagreement_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    summary = json.loads((run / "summary.json").read_text())
    summary["models"]["m1"]["retrieve_quote"]["incorrect"] += 5  # deliberate mismatch
    (run / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(FacctError, match="disagree"):
        build_facct(run, raw_root=raw)


def test_empty_scores_fails_fast(tmp_path):
    # scores AND answers emptied (so the join is vacuously one-to-one) but summary still full:
    # the bidirectional summary check must still refuse a card with no score rows behind it.
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    (run / "scores.jsonl").write_text("")
    (run / "answers.jsonl").write_text("")
    with pytest.raises(FacctError, match="different model/task sets"):
        build_facct(run, raw_root=raw)


def test_dropped_task_scores_fails_fast(tmp_path):
    # drop complete_unit from BOTH scores and answers (join stays one-to-one); summary still lists
    # it -> the summary-set check catches a task the card would otherwise silently omit.
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    for name in ("scores.jsonl", "answers.jsonl"):
        kept = [l for l in (run / name).read_text().splitlines()
                if json.loads(l)["task"] != "complete_unit"]
        (run / name).write_text("\n".join(kept) + "\n")
    with pytest.raises(FacctError, match="different model/task sets"):
        build_facct(run, raw_root=raw)


def test_corrupted_overall_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    summary = json.loads((run / "summary.json").read_text())
    summary["models"]["m1"]["_overall"]["correct"] += 9  # overall inconsistent with task scores
    (run / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(FacctError, match="_overall"):
        build_facct(run, raw_root=raw)


def test_duplicate_answer_row_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    first = (run / "answers.jsonl").read_text().splitlines()[0]
    with (run / "answers.jsonl").open("a") as f:
        f.write(first + "\n")  # duplicate (question_id, model_id)
    with pytest.raises(FacctError, match="duplicate answer row"):
        build_facct(run, raw_root=raw)


def test_unmatched_answer_row_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    with (run / "answers.jsonl").open("a") as f:
        f.write(json.dumps({"question_id": "orphan", "model_id": "m1", "task": "retrieve_quote",
                            "answer": "x", "question": {"source": {}}}) + "\n")
    with pytest.raises(FacctError, match="without a score"):
        build_facct(run, raw_root=raw)


def test_score_row_missing_task_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    # add matching answer + a score row with no 'task'
    with (run / "answers.jsonl").open("a") as f:
        f.write(json.dumps({"question_id": "notask", "model_id": "m1", "task": "retrieve_quote",
                            "answer": "x", "question": {"source": {}}}) + "\n")
    with (run / "scores.jsonl").open("a") as f:
        f.write(json.dumps({"question_id": "notask", "model_id": "m1", "metrics": {"outcome": "correct"}}) + "\n")
    with pytest.raises(FacctError, match="missing 'task'"):
        build_facct(run, raw_root=raw)


def test_selected_corpus_hash_tracks_selected_edition_content(tmp_path):
    # selected_corpus_hash pins the CONTENT of the run's selected editions: editing a selected
    # edition's wording changes it (so the committed-card regression test fails with a clear diff —
    # remedy: regenerate), while the card still builds (no fail-fast on a full-corpus mismatch).
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    before = build_facct(run, raw_root=raw)["selected_corpus_hash"]
    mutated = dict(_KJV)
    mutated["Test 1:1"] = "a quietly changed kjv wording"
    _write(raw / "Protestant Christian" / "kjv.json", _bible_payload(mutated))
    after = build_facct(run, raw_root=raw)  # still builds — not a FacctError
    assert after["selected_corpus_hash"] != before


def test_unrelated_corpus_addition_leaves_card_byte_identical(tmp_path):
    # a drop-in tradition the run never selected must NOT change a historic card (arch invariant:
    # adding a corpus is a no-core-change data drop) — selected_corpus_hash and the card are stable.
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    before = build_facct(run, raw_root=raw)
    # add an unrelated public-domain work to the catalogue (not in the run's selected_texts)
    base = ("    converter: bible_flat\n    work: Later Addition\n    language: en\n"
            "    document_type: scripture\n    tradition: [New Tradition]\n    license: public-domain\n"
            "    requested_as: [later]\n    canonical_language: en\n")
    _write(raw / "Later" / "source.yaml", PROV + "targets:\n  - payload: later.json\n    version: v1\n" + base)
    _write(raw / "Later" / "later.json", _bible_payload({"New 1:1": "brand new unrelated verse"}))
    after = build_facct(run, raw_root=raw)
    assert after == before  # selected_corpus_hash unchanged and the whole card byte-identical


def test_n_questions_mismatch_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    manifest = json.loads((run / "questions.jsonl.manifest.json").read_text())
    manifest["n_questions"] = 999  # disagrees with the distinct question_ids in scores
    (run / "questions.jsonl.manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FacctError, match="distinct question_ids"):
        build_facct(run, raw_root=raw)


def test_rates_are_recomputed_not_copied(tmp_path):
    # corrupt the summary rates but keep counts consistent; the card must show recomputed rates
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    summary = json.loads((run / "summary.json").read_text())
    summary["models"]["m1"]["retrieve_quote"]["accuracy"] = 0.999  # a lie the card must not echo
    (run / "summary.json").write_text(json.dumps(summary))
    report = build_facct(run, raw_root=raw)
    rq = report["outcomes"]["m1"]["by_task"]["retrieve_quote"]
    assert rq["accuracy"] == round(1 / 5, 4)  # correct 1 / (correct 1 + incorrect 4), recomputed


def test_build_does_not_mutate_evidence(tmp_path):
    import hashlib

    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    inputs = ["scores.jsonl", "answers.jsonl", "summary.json", "questions.jsonl.manifest.json"]
    before = {f: hashlib.sha256((run / f).read_bytes()).hexdigest() for f in inputs}
    report = build_facct(run, raw_root=raw)
    write_card(report, run / "facct.json", run / "facct.md")
    after = {f: hashlib.sha256((run / f).read_bytes()).hexdigest() for f in inputs}
    assert before == after  # the card never rewrites the run evidence it reads


def test_unresolved_catalogue_target_fails_fast(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    manifest = json.loads((run / "questions.jsonl.manifest.json").read_text())
    manifest["selected_texts"].append({"work": "Nonexistent", "version": "X", "language": "en"})
    (run / "questions.jsonl.manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FacctError, match="no catalogue target"):
        build_facct(run, raw_root=raw)


# --- regressions: no fabrication, no private matcher -------------------------


def test_no_fabrication_label_in_output(tmp_path):
    report, run, _raw = _build(tmp_path)
    write_card(report, run / "facct.json", run / "facct.md")
    assert "fabrication" not in (run / "facct.json").read_text().lower()


def test_module_defines_no_private_containment_or_normalizer():
    src = inspect.getsource(facct_mod)
    # facct.py must reuse score's predicate, not define its own containment/normalization
    assert "score.bounded_contains" in src
    assert "def normalize" not in src
    assert "def bounded_contains" not in src  # does not redefine it


# --- markdown card (Phase 3) -------------------------------------------------


def test_markdown_has_all_prose_sections(tmp_path):
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report)
    for heading in ("Who the questions represent", "What the models did",
                    "Would another edition have passed?", "What this card claims",
                    "What would make this card wrong", "What this card does not conclude",
                    "Community review"):
        assert f"## {heading}" in md


def test_markdown_numbers_come_from_data_not_typed(tmp_path):
    report, run, raw = _build(tmp_path)
    md = report_markdown(report)
    acc = report["outcomes"]["m1"]["by_task"]["retrieve_quote"]["accuracy"]
    assert f"{round(acc * 100, 1)}%" in md  # 1/5 = 20.0%

    # flip one incorrect retrieve_quote cell to correct in BOTH scores and summary; the rendered
    # accuracy must move with the data (proving nothing is typed into the prose).
    scores = [json.loads(l) for l in (run / "scores.jsonl").read_text().splitlines()]
    for s in scores:
        if s["question_id"] == "retrieve_quote-0001":  # Test 2:2, was incorrect
            s["metrics"] = {"correct": 1, "outcome": "correct"}
    (run / "scores.jsonl").write_text("\n".join(json.dumps(s) for s in scores) + "\n")
    summary = json.loads((run / "summary.json").read_text())
    rq = summary["models"]["m1"]["retrieve_quote"]
    rq["correct"] += 1
    rq["incorrect"] -= 1
    ov = summary["models"]["m1"]["_overall"]
    ov["correct"] += 1
    ov["incorrect"] -= 1
    (run / "summary.json").write_text(json.dumps(summary))

    md2 = report_markdown(build_facct(run, raw_root=raw))
    assert "40.0%" in md2  # 2/5 now
    assert "40.0%" not in md  # and was not there before


def test_markdown_every_outcome_and_counterfactual_number_is_in_the_card(tmp_path):
    # systematic drift guard: every count/accuracy/coverage for every model x task x overall, and
    # every counterfactual numerator/denominator, must appear in the rendered card.
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report)
    for model, block in report["outcomes"].items():
        rows = list(block["by_task"].values()) + [block["overall"]]
        for t in rows:
            assert f"{round(t['accuracy'] * 100, 1)}%" in md
            assert f"{round(t['coverage'] * 100, 1)}%" in md
            for key in ("correct", "incorrect", "refused"):
                assert str(t[key]) in md
    for b in report["edition_counterfactual"]["by_model"].values():
        assert str(b["numerator"]) in md and str(b["denominator"]) in md


def test_markdown_lists_all_selected_texts_with_license(tmp_path):
    # the human card must carry the per-text census (spec: all selected texts by tradition/
    # language/document_type/license), not only aggregate counts.
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report)
    for t in report["census"]["selected_texts"]:
        assert f"{t['work']} ({t['version']})" in md
        assert t["license"] in md


def test_markdown_bible_count_is_derived_not_typed(tmp_path):
    # the counterfactual prose interpolates the Bible edition count/versions from the data; the
    # literal word "three" must not be typed (the fixture has 3 Bibles, but the prose says "3 (...)").
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report).lower()
    assert "three of the texts" not in md
    assert "the three english bibles" not in md


def test_markdown_has_no_fabrication_and_no_verse_bodies(tmp_path):
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report)
    assert "fabrication" not in md.lower()
    # the card embeds citations and numbers only — never the edition wording text
    for body in ("iota kappa lambda mu", "alpha beta gamma delta", "epsilon zeta eta theta"):
        assert body not in md


def test_cli_writes_both_files_into_run_dir(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw)])
    assert result.exit_code == 0, result.output
    assert (run / "facct.json").exists() and (run / "facct.md").exists()
    assert "fabrication" not in (run / "facct.md").read_text().lower()


def test_cli_rejects_output_path_outside_run(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw),
                                 "--md", str(tmp_path / "escape.md")])
    assert result.exit_code != 0
    assert not (tmp_path / "escape.md").exists()
    assert not (run / "facct.json").exists()  # nothing written when the path is rejected


def test_cli_both_or_neither_on_bad_evidence(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    (run / "summary.json").unlink()  # build will fail
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw)])
    assert result.exit_code != 0
    assert not (run / "facct.json").exists() and not (run / "facct.md").exists()


def test_markdown_renders_panel_and_correctness_rule(tmp_path):
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report)
    assert "## The panel" in md
    assert "m1" in md and "| p |" in md  # provider from the fixture panel
    # the correctness rule (containment + the evaluator names) is stated on the card
    assert "contain" in md.lower()
    assert "strict, containment" in md


def test_markdown_glosses_only_tasks_present(tmp_path):
    report, _run, _raw = _build(tmp_path)
    md = report_markdown(report)
    assert "**retrieve_quote**" in md and "**complete_unit**" in md
    # cite_passage / verify_source are not in the fixture run, so they are not glossed
    assert "**cite_passage**" not in md and "**verify_source**" not in md


def test_write_card_is_atomic_rollback_on_second_stage_failure(tmp_path, monkeypatch):
    report, run, _raw = _build(tmp_path)
    jp, mp = run / "facct.json", run / "facct.md"
    jp.write_text("OLD-JSON")
    mp.write_text("OLD-MD")
    import os as _os

    real_replace = _os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # fail on the second swap (the markdown)
            raise OSError("boom")
        return real_replace(src, dst)

    from sacredbench import edition_index as ei_mod

    monkeypatch.setattr(ei_mod.os, "replace", flaky_replace)  # write_card delegates to the shared helper
    with pytest.raises(OSError):
        write_card(report, jp, mp)
    # both files are left byte-identical to their prior contents (first swap rolled back)
    assert jp.read_text() == "OLD-JSON"
    assert mp.read_text() == "OLD-MD"
    # no stray temp files left in the run dir
    assert not list(run.glob("facct.*.tmp")) and not list(run.glob("facct.*.bak.*"))


def test_cli_leaves_stale_card_intact_on_bad_evidence(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    (run / "facct.json").write_text("STALE-JSON")
    (run / "facct.md").write_text("STALE-MD")
    (run / "summary.json").unlink()  # build fails
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw)])
    assert result.exit_code != 0
    assert (run / "facct.json").read_text() == "STALE-JSON"  # untouched
    assert (run / "facct.md").read_text() == "STALE-MD"


def test_cli_refuses_to_overwrite_run_evidence(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    before = (run / "summary.json").read_bytes()
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw), "--json", "summary.json"])
    assert result.exit_code != 0
    assert (run / "summary.json").read_bytes() == before  # evidence untouched
    assert not (run / "facct.md").exists()


def test_cli_refuses_symlinked_default_onto_evidence(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    before = (run / "scores.jsonl").read_bytes()
    (run / "facct.json").symlink_to(run / "scores.jsonl")  # default path aliases evidence
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw)])
    assert result.exit_code != 0
    assert (run / "scores.jsonl").read_bytes() == before


def test_cli_rejects_directory_target(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    (run / "sub").mkdir()
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw), "--md", "sub"])
    assert result.exit_code != 0


def test_cli_creates_missing_subdirectory(tmp_path):
    raw = _raw_tree(tmp_path)
    run = _make_run(tmp_path)
    result = runner.invoke(app, ["facct", str(run), "--raw-root", str(raw),
                                 "--json", "out/facct.json", "--md", "out/facct.md"])
    assert result.exit_code == 0, result.output
    assert (run / "out" / "facct.json").exists() and (run / "out" / "facct.md").exists()


# --- real committed run ------------------------------------------------------


def test_real_run_census_and_counterfactual():
    run = REPO_ROOT / "runs" / "original-2026-10-21"
    if not run.exists() or not (REPO_ROOT / "texts" / "raw").exists():
        pytest.skip("no committed run / raw tree")
    report = build_facct(run)
    assert report["census"]["n_texts"] == 17
    # zero-question languages are the union of target languages and canonical languages minus the
    # pool: grc (restricted TLG) AND la (encyclicals' canonical language, carried by no target's language)
    assert report["census"]["zero_question_languages"] == ["grc", "la"]
    assert {e["work"] for e in report["census"]["excluded_texts"]} == {"Papal Encyclicals", "Talmud Bavli"}
    # 32 incorrect Bible retrieve_quote cells across the panel (verified count)
    cf = report["edition_counterfactual"]["by_model"]
    assert sum(b["denominator"] for b in cf.values()) == 32
    # the real run has all four tasks; the correctness note must describe each task's own rule,
    # not claim containment across the whole table (cite_passage / verify_source score differently)
    md = report_markdown(report)
    assert "name the one correct citation" in md  # cite_passage
    assert "leading Yes / No" in md  # verify_source
    # containment is explicitly scoped to the two text-retrieval tasks, not asserted for all four
    assert "For the two text-retrieval tasks" in md


def test_post_run_filter_drops_targets_added_after_the_run():
    """A historic run's card must not change when a corpus is added later (Spec 37): a
    non-restricted target its manifest does not list came after the run; restricted
    targets are never listed and always count."""
    from types import SimpleNamespace as T

    from sacredbench.facct import post_run_filter

    old = T(text_key=("W", "V", "en"), license="public-domain")
    excluded = T(text_key=("E", "V", "en"), license="open")
    restricted = T(text_key=("R", "V", "grc"), license="restricted")
    later = T(text_key=("New", "V", "pa"), license="public-domain")
    manifest = {
        "selected_texts": [{"work": "W", "version": "V", "language": "en"}],
        "excluded_texts": [{"work": "E", "version": "V", "language": "en", "reason": "x"}],
    }
    assert post_run_filter([old, excluded, restricted, later], manifest) == [old, excluded, restricted]
