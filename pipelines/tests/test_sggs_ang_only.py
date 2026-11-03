"""Issue #135: a Guru Granth Sahib citation is asked for and expected at the Ang only.

Jasbir Singh (working-group chat, 2026-11-03): the Sri Guru Granth Sahib has no standard line
numbering within an Ang, so asking for ``Ang N:k`` and comparing ``k`` is meaningless. The Sikh
cite_passage rows now ask for the "page (Ang)", with an ``Ang 306`` form example, and expect
``Ang N``. retrieve_quote names no line either: it asks for the first or last pankti of the Ang.

Scoring a bare Ang (``citations._score_at_ang``): ``Ang 315``, ``ਅੰਗ ੩੧੫``, ``Ang 315:9`` (a line
the model volunteers) and ``Page 315`` are all Ang 315; a different Ang is not, and a second
citation is still a hedge. ``segment_match`` is None: there is no line to match.

The oracle at the bottom re-scores every committed cite_passage cell in ``runs/facct-2026-11-03``.
No cell moves: not one of the non-Sikh cells, and not one Sikh cell either, scored against its
committed ``Ang N:k`` expected or against the new ``Ang N``. Read-only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sacredbench import citations
from sacredbench.score import score_answer, score_file

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "runs" / "facct-2026-11-03"
SIKH = REPO / "items" / "for-test" / "sikhism"
PROMPT = (
    'Where in the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib can I find this quote? "…" '
    "Answer with the page (Ang) only, in the same form as: Ang 306."
)


def _cite(answer: str, citation: str = "Ang 315", prompt: str | None = PROMPT) -> dict:
    return score_answer("cite_passage", answer, {"citation": citation}, prompt=prompt)


@pytest.mark.parametrize(
    "answer",
    ["Ang 315", "ਅੰਗ ੩੧੫", "Ang 315:9", "ਅੰਗ ੩੧੫:੯", "Page 315", "page 315.", "ਪੰਨਾ ੩੧੫", "Ang 315, Ang 315:9"],
)
def test_the_ang_is_the_citation(answer):
    assert _cite(answer) == {"correct": 1, "n_candidates": 1, "segment_match": None, "outcome": "correct"}


@pytest.mark.parametrize("answer", ["Ang 316", "ਅੰਗ ੩੧੬", "Ang 3150", "Ang 31:5", "Page 316", "webpage 315", "315"])
def test_a_different_ang_is_wrong(answer):
    assert _cite(answer)["outcome"] == "incorrect"


@pytest.mark.parametrize(
    "answer",
    ["Ang 315:9 or Ang 316:2", "Ang 315:9 or John 1:1", "Ang 315 or John 1:1", "ਅੰਗ ੩੧੫ ਜਾਂ ਅੰਗ ੩੧੬", "Page 315 or Ang 316"],
)
def test_a_second_citation_is_still_a_hedge(answer):
    # Before #135 the first two scored correct: the no-colon extractor skips "Ang N:k", so the answer had
    # no candidates and the containment fallback credited it.
    scored = _cite(answer)
    assert (scored["outcome"], scored["n_candidates"]) == ("incorrect", 2)


@pytest.mark.parametrize(
    "answer",
    [
        "Ang 315, line 9", "Ang 315 line 9", "Ang 315 (line 9)", "Ang 315, pankti 9", "Ang 315, Mehl 5",
        "Ang 315, Mehla 5", "Ang 315 (Raag Gauri, Mehl 3)", "The quote is found on Ang 315, line 9.",
        "ਅੰਗ ੩੧੫, ਮਹਲਾ ੫", "ਅੰਗ ੩੧੫, ਪੰਕਤੀ ੯", "ਅੰਗ ੩੧੫ (ਰਾਗੁ ਗਉੜੀ, ਮਹਲਾ ੩)", "page 315 of 1430",
    ],
)
def test_a_qualifier_beside_the_ang_is_not_a_second_citation(answer):
    # Architect decision on PR #136: only another Ang or a colon citation of another work is a rival.
    # Before it, a Latin "line 9" / "Mehl 5" was read as a second citation and a Gurmukhi "ਮਹਲਾ ੫" was not.
    assert _cite(answer) == {"correct": 1, "n_candidates": 1, "segment_match": None, "outcome": "correct"}


@pytest.mark.parametrize(
    "answer",
    [
        "Ang 315, line 9 or Ang 316", "Ang 315 line 9, or perhaps Ang 316 line 2", "Ang 315 (Mehl 5) or John 1:1",
        "ਅੰਗ ੩੧੫, ਮਹਲਾ ੫ ਜਾਂ ਅੰਗ ੩੧੬", "ਅੰਗ ੩੧੫, ਪੰਕਤੀ ੯ ਜਾਂ John 1:1",
    ],
)
def test_a_qualified_ang_beside_another_citation_is_still_a_hedge(answer):
    scored = _cite(answer)
    assert (scored["outcome"], scored["n_candidates"]) == ("incorrect", 2)


@pytest.mark.parametrize(
    ("english", "gurmukhi"),
    [
        ("Ang 315, Mehl 5", "ਅੰਗ ੩੧੫, ਮਹਲਾ ੫"),
        ("Ang 315, line 9", "ਅੰਗ ੩੧੫, ਪੰਕਤੀ ੯"),
        ("Ang 316, Mehl 5", "ਅੰਗ ੩੧੬, ਮਹਲਾ ੫"),
        ("Ang 315, Mehl 5 or Ang 316", "ਅੰਗ ੩੧੫, ਮਹਲਾ ੫ ਜਾਂ ਅੰਗ ੩੧੬"),
    ],
)
def test_english_and_gurmukhi_score_alike(english, gurmukhi):
    assert _cite(english) == _cite(gurmukhi)


def test_echoing_the_form_example_is_not_a_hedge():
    assert _cite("Ang 315 (not Ang 306)")["outcome"] == "correct"
    assert _cite("Ang 306")["outcome"] == "incorrect"  # the example alone is a wrong locus


def test_the_granularity_switch_does_not_apply_to_a_bare_ang(monkeypatch):
    monkeypatch.setattr(citations, "HEADLINE_DROPS_SEGMENT", False)
    assert _cite("Ang 315:9")["outcome"] == "correct"  # no line in the expected to hold it to
    assert _cite("Ang 1297:15", "Ang 1297:28")["outcome"] == "incorrect"  # an Ang:k expected still is


def test_an_ang_k_expected_is_scored_as_before():
    assert _cite("Ang 1297:15", "Ang 1297:28") == {"correct": 1, "n_candidates": 1, "segment_match": 0, "outcome": "correct"}


def test_summary_leaves_a_bare_ang_out_of_segment_match(tmp_path):
    source = {"work": "Sri Guru Granth Sahib", "version": "Shabad OS (SGPC Shabadaarth)", "language": "pa"}
    cells = [("ਅੰਗ ੩੧੫:੯", "Ang 315"), ("Ang 1297:15", "Ang 1297:28")]
    answers = tmp_path / "answers.jsonl"
    answers.write_text("".join(
        json.dumps({
            "question_id": f"q{i}", "model_id": "m1", "task": "cite_passage", "question_set_digest": "d",
            "answer": answer, "question": {"expected": {"citation": citation}, "source": source, "prompt": PROMPT},
        }) + "\n"
        for i, (answer, citation) in enumerate(cells)
    ), encoding="utf-8")
    summary = score_file(answers, tmp_path / "scores.jsonl")
    assert summary["models"]["m1"]["cite_passage"]["correct"] == 2
    assert summary["segment_match"] == {"m1": {"\u0000".join(source.values()): {"correct": 1, "segment_match": 0}}}


# --- the committed Sikh question files ----------------------------------------------------------


def _sikh_rows() -> list[dict]:
    paths = sorted(SIKH.rglob("questions.jsonl"))
    assert len(paths) == 4
    return [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines()]


def test_sikh_cite_rows_ask_for_and_expect_the_ang():
    cite = [q for q in _sikh_rows() if q["task"] == "cite_passage"]
    assert len(cite) == 66  # 30 population + 3 familiarity passages, two prompt arms each
    for q in cite:
        ang = q["expected"]["citation"]
        assert re.fullmatch(r"Ang \d+", ang), q["id"]
        assert q["source"]["citation"].partition(":")[0] == ang  # the passage keeps its pankti
        example = re.search(r": (Ang \S+?)\.(?:\n|$)", q["prompt"])[1]
        assert re.fullmatch(r"Ang \d+", example) and example != ang, q["id"]
        assert "page (Ang)" in q["prompt"] or "ਅੰਗ (ਪੰਨਾ)" in q["prompt"], q["id"]


def _ang_lines() -> dict[str, list[tuple[str, str]]]:
    """Each Ang's ``(cleaned text, raw data)`` in reading order, read straight from the raw payload."""
    from sacredbench.convert import _SGGS_ANG_ERRATA, clean_sggs_line

    raw = json.loads((REPO / "texts" / "raw" / "Sikhism" / "sggs_shabados.json").read_text(encoding="utf-8"))
    by_ang: dict[str, list[tuple[str, str]]] = {}
    for rec in raw["lines"]:
        ang = _SGGS_ANG_ERRATA[rec["id"]][1] if rec["id"] in _SGGS_ANG_ERRATA else rec["ang"]
        text = clean_sggs_line(rec["data"])
        if text:
            by_ang.setdefault(f"Ang {ang}", []).append((text, rec["data"]))
    return by_ang


EDGE = re.compile(r"(?:the (first|last) pankti of (Ang \d+) in )|(?:ਦੇ (Ang \d+) ਦੀ (ਪਹਿਲੀ|ਆਖ਼ਰੀ) ਪੰਕਤੀ)")


def test_sikh_retrieval_rows_ask_for_an_edge_pankti_of_the_ang():
    """The line index k is this corpus's own record count, so a retrieve row names no line. It asks
    for the first or last pankti of the drawn passage's Ang, and expects exactly that pankti."""
    by_ang = _ang_lines()
    rows = _sikh_rows()
    retrieve = [q for q in rows if q["task"] == "retrieve_quote" and q["source"]["sample"] == "population"]
    # Two edges per Ang: a population Ang that holds more drawn passages asks only two of them, and
    # Ang 315 asks none (a heading first, a record crossing into Ang 316 last).
    assert len(retrieve) == 50
    edges = {"first": 0, "last": 0}
    for q in retrieve:
        assert not re.search(r"\d+:\d+", q["prompt"]), q["id"]
        m = EDGE.search(q["prompt"])
        assert m, q["id"]
        edge = m[1] or {"ਪਹਿਲੀ": "first", "ਆਖ਼ਰੀ": "last"}[m[4]]
        ang = m[2] or m[3]
        text, data = by_ang[ang][0 if edge == "first" else -1]
        assert q["expected"] == {"text": text}, q["id"]
        assert re.search(r"[;.,]", data), q["id"]  # a pankti (vishraam marks), never a heading
        assert not re.sub(r"[\s॥੦-੯]", "", data.partition("॥")[2].replace("ਰਹਾਉ", "")), q["id"]  # one tuk
        assert q["source"]["citation"].partition(":")[0] == ang, q["id"]
        edges[edge] += 1
    assert edges["first"] and edges["last"]
    # Each retrieve row asks about the Ang of a passage a cite row quotes, and no file asks twice.
    for path in sorted(SIKH.rglob("questions.jsonl")):
        file_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        asked = [q["prompt"] for q in file_rows if q["task"] == "retrieve_quote"]
        assert len(asked) == len(set(asked)), path
        cited = {q["expected"]["citation"] for q in file_rows if q["task"] == "cite_passage"}
        if "familiarity" in path.parts:
            continue  # asked by name: test_sikh_familiarity_rows_ask_for_the_famous_line_by_name
        retrieved = {q["source"]["citation"].partition(":")[0] for q in file_rows if q["task"] == "retrieve_quote"}
        assert retrieved <= cited and cited - retrieved <= {"Ang 315"}, path  # Ang 315: no askable edge


NAMES = {
    "Ang 1:1": ("the Mool Mantar", "ਮੂਲ ਮੰਤਰ"),
    "Ang 8:33": ("the first line of the closing salok of Japji Sahib", "ਜਪੁਜੀ ਸਾਹਿਬ ਦੇ ਅੰਤਲੇ ਸਲੋਕ ਦੀ ਪਹਿਲੀ ਪੰਕਤੀ"),
    "Ang 262:31": ("the rahao line of Sukhmani Sahib", "ਸੁਖਮਨੀ ਸਾਹਿਬ ਦੀ ਰਹਾਉ ਵਾਲੀ ਪੰਕਤੀ"),
}


def test_sikh_familiarity_rows_ask_for_the_famous_line_by_name():
    """A famous line has a name, so its retrieve row asks by name and expects the line itself, the
    passage its other three tasks quote. Edge panktis are for the population draw only."""
    rows = [q for q in _sikh_rows() if q["source"]["sample"] == "familiarity"]
    retrieve = [q for q in rows if q["task"] == "retrieve_quote"]
    assert len(retrieve) == 6
    for q in retrieve:
        citation = q["source"]["citation"]
        english, native = NAMES[citation]
        assert (english if q["source"]["condition"] == "ask_english" else native) in q["prompt"], q["id"]
        assert not re.search(r"\d+:\d+|Ang \d+", q["prompt"]), q["id"]
        cite = next(
            c for c in rows
            if c["task"] == "cite_passage" and c["source"]["citation"] == citation
            and c["source"]["condition"] == q["source"]["condition"]
        )
        assert f'"{q["expected"]["text"]}"' in cite["prompt"], q["id"]  # the line the cite row quotes


def test_an_edge_heading_is_never_asked_for():
    import importlib.util
    import sys

    review = REPO / "items" / "for-test" / "review"
    sys.path.insert(0, str(review))
    spec = importlib.util.spec_from_file_location("build_questions", review / "build_questions.py")
    bq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bq)
    for heading in ("ਗਉੜੀ ਮਹਲਾ ੫ ॥", "ਪਉੜੀ ॥", "ੴ ਸਤਿਗੁਰ ਪ੍ਰਸਾਦਿ ॥", "ਸਲੋਕ ਮਃ ੪ ॥"):
        assert not bq.sggs_is_pankti(heading)
    assert bq.sggs_is_pankti("ਪੇਡੁ ਮੁੰਢਾਹੂੰ ਕਟਿਆ; ਤਿਸੁ ਡਾਲ ਸੁਕੰਦੇ ॥੧੨॥")
    # Ang 315's last record holds three tuks; BaniDB prints the third on Ang 316. Never an edge.
    crossing = "ਬਾਹਰਿ ਬਹੈ ਪੰਚਾ ਵਿਚਿ; ਤਪਾ ਸਦਾਏ ॥ ਅੰਦਰਿ ਬਹੈ ਤਪਾ ਪਾਪ ਕਮਾਏ ॥ ਹਰਿ ਅੰਦਰਲਾ ਪਾਪੁ; ਪੰਚਾ ਨੋ ਉਘਾ ਕਰਿ ਵੇਖਾਲਿਆ ॥"
    assert not bq.sggs_is_one_tuk(crossing)
    assert bq.sggs_is_one_tuk("ਹਰਿ ਹੋ; ਹੋ ਕਿਰਪਾਨ ॥੧॥ ਰਹਾਉ ॥") and bq.sggs_is_one_tuk("ਪੇਡੁ ਮੁੰਢਾਹੂੰ ਕਟਿਆ; ਤਿਸੁ ਡਾਲ ਸੁਕੰਦੇ ॥੧੨॥")
    assert bq.sggs_edge_pankti([("Ang 315:1", "a", "ਸਲੋਕ ਮਃ ੫ ॥"), ("Ang 315:45", "b", crossing)], "last") is None
    lines = [("Ang 306:1", "a", "ਸਲੋਕ ਮਃ ੪ ॥"), ("Ang 306:2", "b", "x; y ॥"), ("Ang 306:3", "c", "ਪਉੜੀ ॥")]
    assert bq.sggs_edge_pankti(lines[1:], "last") == ("first", "Ang 306:2", "b")
    assert bq.sggs_edge_pankti(lines[:2], "first") == ("last", "Ang 306:2", "b")
    assert bq.sggs_edge_pankti([lines[0], lines[2]], "first") is None  # a heading at both edges
    # An Ang asks each edge once: a second passage on it gets the other edge, a third gets none.
    both = [("Ang 9:1", "a", "x; y ॥"), ("Ang 9:2", "b", "z; w ॥")]
    assert bq.sggs_edge_pankti(both, "first", {"first"}) == ("last", "Ang 9:2", "b")
    assert bq.sggs_edge_pankti(both, "first", {"first", "last"}) is None


# --- oracle over the committed facct-2026-11-03 run ---------------------------------------------


def test_no_committed_cite_cell_moves():
    score_files = sorted(RUN.glob("*/base/**/scores.jsonl"))
    if not score_files:
        pytest.skip("runs/ evidence not present")
    n = {"other": 0, "sikh": 0}
    for scores in score_files:
        answers = [json.loads(l) for l in scores.with_name("answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        committed = [json.loads(l) for l in scores.read_text(encoding="utf-8").splitlines() if l.strip()]
        for row, score in zip(answers, committed, strict=True):
            if row["task"] != "cite_passage":
                continue
            question, key = row["question"], (scores.relative_to(RUN).as_posix(), row["question_id"])
            expected = question["expected"]["citation"]
            assert score_answer("cite_passage", row["answer"], {"citation": expected}, prompt=question["prompt"]) == score["metrics"], key
            if "sikhism" not in scores.parts:
                n["other"] += 1
                continue
            n["sikh"] += 1
            at_ang = score_answer("cite_passage", row["answer"], {"citation": expected.partition(":")[0]}, prompt=question["prompt"])
            assert at_ang["outcome"] == score["metrics"]["outcome"], key  # the #112 Ang credit already held
    assert n == {"other": 7200, "sikh": 960}
