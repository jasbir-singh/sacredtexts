"""Task-specific failure kinds for an already-scored answer.

The headline outcome stays ``correct`` / ``incorrect`` / ``refused``. This label
does not change ``correct``. It is the same reading the viewer uses
(``apps/viewer/src/lib/failureKind.ts``):

- retrieve_quote / complete_unit, incorrect: other script, omission, near copy
  (token F1 ≥ 0.85), paraphrase (0.4 ≤ F1 < 0.85), or wrong passage.
- retrieve_quote / complete_unit, correct and contained but not normalized:
  addition, when the answer continues at least eight tokens past the reference.
  Containment still scores that cell correct.
- cite_passage, incorrect: hedge (more than one candidate), wrong locus (one),
  or no citation (zero).
- verify_source, incorrect: wrong verdict.

Refused and missing cells are unlabeled. One text is one (work, version,
language). A tradition may contain several texts; kinds are counted per text,
not pooled into a tradition score.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .score import INDIC_MARKS

PARAPHRASE_F1 = 0.4
# At or above this overlap the answer is a near copy the scorer failed to fold, not a rewrite.
NEAR_COPY_F1 = 0.85
ADDITION_EXTRA_TOKENS = 8

# Everything that is not a Unicode letter/number/space folds to a space. Underscore is NOT a
# letter or number, so it folds too — this matches the viewer's `/[^\p{L}\p{N}\s]/u` exactly
# (Python's `\w` would keep `_`, so a Markdown `_quoted_` would tokenise differently; see the
# shared parity fixture). Keep the two normalizers byte-for-byte aligned.
# Devanagari/Gurmukhi vowel signs (Mn/Mc) are part of the word, so they are exempt — the
# same marks the scorer keeps (``score.INDIC_MARKS``); the viewer adds `\p{M}` for those blocks.
_PUNCT_RE = re.compile(r"[^\w\s" + re.escape(INDIC_MARKS) + r"]|_", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# A minor kind stays on the passage that was asked for. A major kind replaces it:
# another passage, another place, another script, a false yes/no, or no place at all.
MINOR_KINDS = frozenset({"paraphrase", "omission", "addition", "near_copy"})
MAJOR_KINDS = frozenset({
    "wrong_passage",
    "other_script",
    "wrong_locus",
    "hedge",
    "no_citation",
    "wrong_verdict",
})


def severity(kind: str | None) -> str | None:
    """``minor``, ``major``, or None when the cell has no failure kind."""
    if kind in MINOR_KINDS:
        return "minor"
    if kind in MAJOR_KINDS:
        return "major"
    return None


KINDS = (
    "near_copy",
    "paraphrase",
    "wrong_passage",
    "other_script",
    "omission",
    "addition",
    "wrong_locus",
    "hedge",
    "no_citation",
    "wrong_verdict",
)


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text.lower())).strip()


def tokens(text: str) -> list[str]:
    n = _normalize(text)
    return n.split(" ") if n else []


def _script(text: str) -> str | None:
    hebrew = arabic = greek = latin = devanagari = gurmukhi = 0
    for ch in text:
        o = ord(ch)
        if 0x0900 <= o <= 0x097F:
            devanagari += 1
        elif 0x0A00 <= o <= 0x0A7F:
            gurmukhi += 1
        elif 0x0590 <= o <= 0x05FF:
            hebrew += 1
        elif (
            0x0600 <= o <= 0x06FF
            or 0x0750 <= o <= 0x077F
            or 0x08A0 <= o <= 0x08FF
            or 0xFB50 <= o <= 0xFDFF
            or 0xFE70 <= o <= 0xFEFF
        ):
            arabic += 1
        elif (0x0370 <= o <= 0x03FF) or (0x1F00 <= o <= 0x1FFF):
            # Greek and Coptic + Greek Extended. grc is a supported canonical language, so a
            # Greek prompt answered in English must read as other_script, not wrong_passage.
            greek += 1
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            latin += 1
    best = max(hebrew, arabic, greek, latin, devanagari, gurmukhi)
    if best < 4:
        return None
    if hebrew == best:
        return "hebrew"
    if arabic == best:
        return "arabic"
    if greek == best:
        return "greek"
    if devanagari == best:
        return "devanagari"
    if gurmukhi == best:
        return "gurmukhi"
    return "latin"


def _omission(answer: str, expected: str) -> bool:
    a = _normalize(answer)
    e = _normalize(expected)
    a_tokens = a.split(" ") if a else []
    e_tokens = e.split(" ") if e else []
    if len(a_tokens) < 2 or len(a_tokens) >= len(e_tokens):
        return False
    if len(a_tokens) > len(e_tokens) * 0.85:
        return False
    return f" {a} " in f" {e} "


def classify_failure(
    *,
    task: str,
    correct: bool,
    refused: bool,
    answer: str,
    expected: str,
    token_f1: float | None,
    normalized: float | None,
    contains_reference: float | None,
    n_candidates: float | None,
    paraphrase_f1: float = PARAPHRASE_F1,
) -> str | None:
    """Return a failure kind, or None when the outcome is the whole story.

    ``paraphrase_f1`` is the floor above which a miss is a paraphrase rather than a wrong
    passage; it defaults to the taxonomy's :data:`PARAPHRASE_F1` and is only moved by the
    floor-sensitivity sweep in ``splits`` (so that sweep does not re-implement this cascade)."""
    if refused:
        return None
    if task in ("retrieve_quote", "complete_unit"):
        if correct:
            if contains_reference != 1 or normalized == 1:
                return None
            extra = len(tokens(answer)) - len(tokens(expected))
            return "addition" if extra >= ADDITION_EXTRA_TOKENS else None
        if _script(expected) and _script(answer) and _script(expected) != _script(answer):
            return "other_script"
        if _omission(answer, expected):
            return "omission"
        f1 = token_f1 or 0
        if f1 >= NEAR_COPY_F1:
            return "near_copy"
        if f1 >= paraphrase_f1:
            return "paraphrase"
        return "wrong_passage"
    if not correct and task == "cite_passage":
        n = n_candidates or 0
        if n > 1:
            return "hedge"
        if n_candidates == 1:
            return "wrong_locus"
        return "no_citation"
    if not correct and task == "verify_source":
        return "wrong_verdict"
    return None


def expected_text(expected: dict) -> str:
    for key in ("text", "citation", "answer"):
        value = expected.get(key)
        if isinstance(value, str):
            return value
    return ""


def _text_key(source: dict) -> str:
    work = source.get("work") or "?"
    version = source.get("version") or "?"
    language = source.get("language") or "?"
    return f"{work} · {version} · {language}"


# How the catalogue names a text, and the plain label used in a breakdown.
# An encyclical is teaching, not scripture. Hadith is not the Qur'an.
DOC_LABEL = {
    "scripture": "scripture",
    "hadith_collection": "hadith",
    "talmud": "talmud",
    "encyclical": "papal encyclical",
}


def _iter_scored(run_dir: Path):
    """Yield (task, outcome, kind, source) for each joined score."""
    answers: dict[tuple[str, str], dict] = {}
    for line in (run_dir / "answers.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        answers[(row["question_id"], row["model_id"])] = row
    for line in (run_dir / "scores.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        score = json.loads(line)
        metrics = score.get("metrics") or {}
        answer_row = answers.get((score["question_id"], score["model_id"]))
        if answer_row is None:
            continue
        question = answer_row.get("question") or {}
        source = question.get("source") or {}
        expected = expected_text(question.get("expected") or {})
        outcome = metrics.get("outcome")
        if outcome not in ("correct", "incorrect", "refused"):
            outcome = "correct" if metrics.get("correct") == 1 else "incorrect"
        kind = classify_failure(
            task=score["task"],
            correct=metrics.get("correct") == 1,
            refused=outcome == "refused",
            answer=answer_row.get("answer") or "",
            expected=expected,
            token_f1=metrics.get("token_f1"),
            normalized=metrics.get("normalized"),
            contains_reference=metrics.get("contains_reference"),
            n_candidates=metrics.get("n_candidates"),
        )
        yield score["task"], outcome, kind, source


def rates(counts: Counter) -> tuple[float | None, float | None]:
    """Accuracy C/(C+I) and refusal R/N. Accuracy is None when nothing was graded."""
    c = counts["correct"]
    i = counts["incorrect"]
    r = counts["refused"]
    n = c + i + r
    accuracy = c / (c + i) if c + i else None
    refusal = r / n if n else None
    return accuracy, refusal


def breakdown_run(run_dir: Path) -> dict:
    """Outcome counts by document type, by tradition, and by task.

    Papal encyclicals are their own type. A run that did not ask them reports
    that type at zero rather than folding it into scripture.
    """
    by_doc: dict[str, Counter] = {label: Counter() for label in DOC_LABEL.values()}
    by_trad: dict[str, Counter] = {}
    by_pair: dict[str, Counter] = {}
    by_task: dict[str, Counter] = {}
    for task, outcome, kind, source in _iter_scored(run_dir):
        raw = source.get("document_type") or "unknown"
        doc = DOC_LABEL.get(raw, raw)
        trads = source.get("tradition") or ["unknown"]
        if isinstance(trads, str):
            trads = [trads]
        trads = trads or ["unknown"]
        # `tradition` is a LIST (an invariant: traditions share texts). A cell is counted once
        # by document type and by task, but ONCE PER LISTED TRADITION for the tradition and
        # tradition×type rows — the same way score.py counts a shared text under each tradition,
        # so a two-tradition doc appears in both tradition rows.
        buckets = [(by_doc, doc), (by_task, task)]
        for trad in trads:
            buckets.append((by_trad, trad))
            buckets.append((by_pair, f"{trad} · {doc}"))
        for bucket, key in buckets:
            bucket.setdefault(key, Counter())
            bucket[key][outcome] += 1
            if kind:
                bucket[key][f"kind:{kind}"] += 1
    return {"document_type": by_doc, "tradition": by_trad, "tradition_and_type": by_pair, "task": by_task}


def format_breakdown(groups: dict[str, Counter]) -> str:
    """One row per group: n, accuracy, refusal rate."""
    lines = [f"{'group':<42} {'n':>5} {'acc':>6} {'ref':>6}"]
    for key in sorted(groups):
        counts = groups[key]
        n = counts["correct"] + counts["incorrect"] + counts["refused"]
        accuracy, refusal = rates(counts)
        acc_s = "  —  " if accuracy is None else f"{accuracy:6.3f}"
        ref_s = "  —  " if refusal is None else f"{refusal:6.3f}"
        lines.append(f"{key:<42} {n:5d} {acc_s} {ref_s}")
    return "\n".join(lines)


def report_run(run_dir: Path) -> dict:
    """Count outcomes and failure kinds for one run, per text.

    Joins ``scores.jsonl`` to ``answers.jsonl`` on (question_id, model_id).
    The text key is the answer's source ``(work, version, language)``.
    """
    answers: dict[tuple[str, str], dict] = {}
    for line in (run_dir / "answers.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        answers[(row["question_id"], row["model_id"])] = row

    by_text: dict[str, Counter] = {}
    overall: Counter = Counter()
    for line in (run_dir / "scores.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        score = json.loads(line)
        metrics = score.get("metrics") or {}
        answer_row = answers.get((score["question_id"], score["model_id"]))
        if answer_row is None:
            continue
        question = answer_row.get("question") or {}
        source = question.get("source") or {}
        expected = expected_text(question.get("expected") or {})
        outcome = metrics.get("outcome")
        if outcome not in ("correct", "incorrect", "refused"):
            outcome = "correct" if metrics.get("correct") == 1 else "incorrect"
        kind = classify_failure(
            task=score["task"],
            correct=metrics.get("correct") == 1,
            refused=outcome == "refused",
            answer=answer_row.get("answer") or "",
            expected=expected,
            token_f1=metrics.get("token_f1"),
            normalized=metrics.get("normalized"),
            contains_reference=metrics.get("contains_reference"),
            n_candidates=metrics.get("n_candidates"),
        )
        key = _text_key(source)
        bucket = by_text.setdefault(key, Counter())
        bucket[f"outcome:{outcome}"] += 1
        overall[f"outcome:{outcome}"] += 1
        if kind:
            bucket[f"kind:{kind}"] += 1
            overall[f"kind:{kind}"] += 1
            overall[f"severity:{severity(kind)}"] += 1
            bucket[f"severity:{severity(kind)}"] += 1
    return {"by_text": {k: dict(v) for k, v in sorted(by_text.items())}, "overall": dict(overall)}
