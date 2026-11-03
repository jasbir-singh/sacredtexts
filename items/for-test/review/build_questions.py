"""Rebuild the review question files from texts/raw.

Each file has a uniform population sample of 30 and a separate familiarity
panel (every citation in well_known.yaml). Sikh citations are Ang N:k in
reading order; a Sikh cite_passage row asks for and expects the Ang only, because
line numbering within an Ang is not standardised (issue #135). Within each sample, half of the verify_source rows quote a
different work and expect "no". An Arabic passage's "no" quotes the matn of a
hadith that shares no text with the Qur'an (issue #75).

Run with the pipelines environment from the repo root:
``uv --project pipelines run python items/for-test/review/build_questions.py``.
"""

from __future__ import annotations

import functools
import hashlib
import html
import json
import random
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from sacredbench.catalogue import load_source
from sacredbench.convert import _SGGS_ANG_ERRATA, clean_sggs_line
from sacredbench.generate import split_quote
from sacredbench.item_sample import Passage, draw_passages, load_well_known
from sacredbench.score import fold_aware_contains, parse_yes_no

REVIEW = Path(__file__).resolve().parent
RAW = Path(__file__).resolve().parents[3] / "texts" / "raw"
TAG = re.compile(r"<[^>]+>")
TASKS = ("retrieve_quote", "complete_unit", "cite_passage", "verify_source")
MIN_WORDS = 16

QURAN_FILE = RAW / "Sunni Islam" / "quran_uthmani_from_qul.json.json"
QURAN_EN_FILE = RAW / "Sunni Islam" / "quran_saheeh_international_from_qul.json"
QURAN_VERSION = "Uthmani (QUL)"
QURAN_EN_VERSION = "Saheeh International (QUL)"
# Owner-signed Arabic templates (Waleed, native Arabic speaker, 2026-11-01). "رسم" is
# orthography not a print run ("طبعة"), "النص" for revelation, "رقم السورة والآية" for the
# reference, and a closing "فقط" because Arabic-prompted models tend to open with a preamble
# before the verdict (see METHODOLOGY.md). build_review.py renders the review page from these.
QURAN_AR = {
    "retrieve_quote": "ما نص الموضع {citation} في القرآن الكريم بالرسم العثماني؟ أجب بالنص المطابق لهذه النسخة فقط، دون أي زيادة.",
    "complete_unit": 'أكمل هذا النص من القرآن الكريم بالرسم العثماني: "{head}" أجب بالكلمات المتبقية فقط.',
    "cite_passage": 'أين ورد هذا النص في القرآن الكريم بالرسم العثماني؟ "{text}" أجب برقم السورة والآية فقط، بالصيغة نفسها: {example}.',
    "verify_source": 'هل النص التالي من القرآن الكريم بالرسم العثماني؟ "{text}" أجب بـ«نعم» أو «لا» فقط.',
}

# The six canonical hadith collections (Kutub al-Sittah) are the Qur'an's same-script "no"
# donors (issue #75; the set is the owner's choice, #74). Payload, work and version are read
# from texts/raw/Sunni Islam/source.yaml, so true_version / true_citation cannot drift from it.
KUTUB_AL_SITTAH = (
    "Sahih al-Bukhari", "Sahih Muslim", "Sunan Abi Dawud",
    "Jami` at-Tirmidhi", "Sunan an-Nasa'i", "Sunan Ibn Majah",
)
HADITH_SEED = 20261030
QURAN_SHARED_WORDS = 6  # a donor sharing this many consecutive words with an ayah is rejected

EN = {
    "retrieve_quote": "What is the text of {citation} in {version}? Reply with the exact text of that edition and nothing else.",
    "complete_unit": 'Complete this quotation from {version}: "{head}" Reply with only the remaining words.',
    "cite_passage": 'Where in {version} can I find this quote? "{text}" Answer with the citation only, in the same form as: {example}.',
    "verify_source": 'Is the following text from {version}? "{text}" Answer Yes or No.',
}

# Issue #135 (Jasbir Singh): the Sri Guru Granth Sahib has no standard line numbering within an Ang,
# so cite_passage asks for and expects the Ang (page) only. retrieve_quote cannot name a pankti by
# "Ang N:k" either: k is this corpus's record count, which no model can know (279 of the 426 Sikh
# retrieve refusals in facct-2026-11-03 said so). It asks for the first or the last pankti of the
# Ang instead (``sggs_edge_pankti``), the two panktis an Ang names without a line number. Each
# row's source citation is the pankti it expects.
SGGS_EN = {
    **EN,
    "retrieve_quote": "What is the {edge} pankti of {ang} in {version}? Reply with the exact text of that edition and nothing else.",
    "cite_passage": 'Where in {version} can I find this quote? "{text}" Answer with the page (Ang) only, in the same form as: {example}.',
}
# A familiarity passage is famous by name, so its retrieve row asks by that name (well_known.yaml).
SGGS_NAMED_EN = "What is {name} in {version}? Reply with the exact text of that edition and nothing else."
SGGS_NAMED_PA = "ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ ਵਿਚੋਂ {name} ਦਾ ਪਾਠ ਦੱਸੋ। ਸਿਰਫ਼ ਉਸੇ ਅਡੀਸ਼ਨ ਦਾ ਪਾਠ ਲਿਖੋ।"
SGGS_EDGE_WORDS = {"first": ("first", "ਪਹਿਲੀ"), "last": ("last", "ਆਖ਼ਰੀ")}
_SGGS_VISHRAAM = re.compile(r"[;.,]")  # convert._SGGS_VISHRAAM_RE: Shabad OS marks every pankti's pauses


def sggs_is_pankti(data: str) -> bool:
    """A verse line, not a heading. Shabad OS puts vishraam marks in panktis and none in a heading
    (``ਗਉੜੀ ਮਹਲਾ ੫ ॥``, ``ਪਉੜੀ ॥``, ``ੴ ਸਤਿਗੁਰ ਪ੍ਰਸਾਦਿ ॥``). A few short panktis have none either,
    so this errs toward calling a line a heading: an edge question is only ever asked of a line
    that is certainly a pankti."""
    return bool(_SGGS_VISHRAAM.search(data))


def sggs_is_one_tuk(data: str) -> bool:
    """One tuk: nothing but verse counters and ``ਰਹਾਉ`` after its first ``॥``. Shabad OS sometimes
    stores several tuks as one record, and such a record can cross a page break: its last record
    on Ang 315 holds three tuks, and BaniDB prints the third on Ang 316. An edge question asks only
    of a one-tuk record, so its expected text is on the Ang it names."""
    rest = data.partition("॥")[2].replace("ਰਹਾਉ", "")
    return not re.sub(r"[\s॥੦-੯]", "", rest)


def sggs_edge_pankti(
    ang_lines: list[tuple[str, str, str]], prefer: str, taken: set[str] = frozenset(),
) -> tuple[str, str, str] | None:
    """``(edge, citation, text)``: the Ang's ``prefer`` edge ("first" or "last"), else the other one,
    skipping an edge that is a heading or already in ``taken``. ``ang_lines`` is the Ang's
    ``(citation, text, raw data)`` in reading order. An edge that is a heading, or several tuks
    in one record, is skipped too. None when neither edge is left: an Ang asks
    at most two retrieve questions, and a third passage drawn from it gets none."""
    edges = {"first": ang_lines[0], "last": ang_lines[-1]}
    for edge in (prefer, "last" if prefer == "first" else "first"):
        citation, text, data = edges[edge]
        if edge not in taken and sggs_is_pankti(data) and sggs_is_one_tuk(data):
            return edge, citation, text
    return None


def sggs_ang(citation: str) -> str:
    """``Ang 306`` for the pankti ``Ang 306:13``."""
    return citation.partition(":")[0]


# English display names the model sees in a prompt. Each names the work as well as
# the edition: a bare catalogue version ("Is the following text from 2013 edition?")
# never says which work's edition (issue #90). The catalogue `version` string is
# unchanged in each question's source metadata; only the prompt wording changes. The
# Qur'an is named "the Uthmani Qur'an" (no "QUL"), owner-signed 2026-11-01 (issue #75).
_EDITION_DISPLAY = {
    "Uthmani (QUL)": "the Uthmani Qur'an",
    "Saheeh International (QUL)": "the Saheeh International translation",
    "William Davidson Edition - Aramaic": "the William Davidson Aramaic edition of the Babylonian Talmud",
    "William Davidson Edition - English": "the William Davidson English edition of the Babylonian Talmud",
    "Shabad OS (SGPC Shabadaarth)": "the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib",
    "Stotra Samhita (Gita Press text)": "the Stotra Samhita (Gita Press text) edition of the Bhagavad Gita",
    "Annie Besant (1922)": "the Annie Besant (1922) translation of the Bhagavad Gita",
    "Chaṭṭha Saṅgāyana (VRI)": "the Chaṭṭha Saṅgāyana (VRI) edition of the Dhammapada",
    "2013 edition": "the 2013 edition of the Book of Mormon",
    "NRSV": "the New Revised Standard Version (NRSV)",
}
# Each encyclical is its own work, with the version "Vatican English text (<pope>, <date>)".
_ENCYCLICAL_VERSION = re.compile(r"Vatican English text \((.+)\)")


def prompt_text(text: str) -> str:
    """The passage as it appears inside a prompt's quotation marks.

    Saheeh International writes dialogue with straight quotes. Leaving those in
    the prompt ends the quotation at the first one, so a ``no`` item keeps the
    real ayah in the question."""
    return text.replace('"', "'").replace("“", "'").replace("”", "'")


def prompt_for(template: str, fields: dict, suffix: str = "") -> dict:
    """A row's prompt, the passage it quotes, and how to quote a different passage instead.

    ``payload`` is the passage that fills the template's ``"{text}"``, and ``render`` rebuilds the
    whole prompt around any passage. That is how a verify "no" row quotes its donor
    (``add_verify_negatives``). Nothing searches a prompt for its quotation marks, because a passage
    can contain them (PR #98: five encyclical "no" rows came out with a Book of Mormon donor spliced
    onto the tail of the encyclical). A passage or an opening with a straight double quote fails here,
    so every prompt quotes exactly one passage; English builders pass their text through ``prompt_text``.
    """
    def render(payload: str) -> str:
        if '"' in payload:
            raise SystemExit(f"a quoted passage contains a straight double quote: {payload[:80]!r}")
        return template.format(**{**fields, "text": payload}) + suffix

    if '"' in fields.get("head", ""):
        raise SystemExit(f"a quoted opening contains a straight double quote: {fields['head'][:80]!r}")
    return {"prompt": render(fields["text"]), "payload": fields["text"], "render": render}


def edition_name(version: str, work: str | None = None) -> str:
    """The edition as a prompt names it: the work and the edition, never a bare catalogue version.

    ``work`` is needed only for an encyclical. An edition with no display name fails, so a new
    edition cannot fall back to a name that leaves out the work (issue #90)."""
    if version in _EDITION_DISPLAY:
        return _EDITION_DISPLAY[version]
    encyclical = _ENCYCLICAL_VERSION.fullmatch(version)
    if encyclical and work:
        return f"the Vatican English text of the encyclical {work} ({encyclical[1]})"
    raise SystemExit(f"no prompt name for edition {version!r} of {work!r}: add one to _EDITION_DISPLAY")


def asked_as(work: str, version: str) -> dict[str, tuple[str, str]]:
    """``{citation: (English name, native name)}`` for the well-known passages asked for by name."""
    import yaml

    items = yaml.safe_load((REVIEW.parents[0] / "well_known.yaml").read_text(encoding="utf-8"))["items"]
    return {
        str(i["citation"]): (i["asked_as"], i["asked_as_native"])
        for i in items if i["work"] == work and i["version"] == version and "asked_as" in i
    }


def famous_passages(work: str, version: str) -> list[Passage]:
    path = REVIEW.parents[0] / "well_known.yaml"
    return [p for p in load_well_known(path) if p.work == work and p.version == version]


def population_draw(pool: list[Passage], famous: list[Passage], *, seed: int) -> list[Passage]:
    """Thirty passages, uniform, with the pre-registered familiar citations removed.

    The familiar list is reported as its own panel. Leaving it inside this draw,
    or reserving a quarter of the draw for it, would bias the population estimate
    toward lines models have memorized, and that bias is larger for some traditions
    than others.
    """
    famous_ids = {p.citation for p in famous}
    eligible = [p for p in pool if p.citation not in famous_ids]
    return [p for p, _ in draw_passages(eligible, [], n=30, famous_share=0, seed=seed)]


def clean_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub("", s))).strip()


def split_words(text: str) -> tuple[str, str]:
    return split_quote(text)


def rows_for(
    items, *, tradition, version, native_tmpl, english_version=None, english_native_tmpl=None,
    english_tmpl=EN, cited_as=None,
):
    """``cited_as`` maps a passage's citation to the one its cite_passage row asks for and expects
    (the Guru Granth Sahib's Ang, #135). The form example is a different cited citation, never the
    answer, even where two passages share an Ang."""
    cited_as = cited_as or (lambda citation: citation)
    citations = [passage.citation for passage, _, _, _ in items]
    out = []
    for passage, sample, native, english in items:
        head, rest = split_words(native)
        cited = cited_as(passage.citation)
        example = next(cited_as(c) for c in citations if cited_as(c) != cited)
        fields = {
            "citation": passage.citation, "version": edition_name(version),
            "head": prompt_text(head), "text": prompt_text(native), "example": example,
        }
        expected = {
            "retrieve_quote": {"text": native},
            "complete_unit": {"text": rest, "full_text": native},
            "cite_passage": {"citation": cited},
            "verify_source": {
                "answer": "yes", "true_tradition": tradition,
                "true_version": version, "true_citation": passage.citation,
            },
        }
        base = {
            "tradition": tradition,
            "citation": passage.citation,
            "sample": sample,
            "stratum": "famous" if sample == "familiarity" else "ordinary",
            "version": version,
        }
        for task in TASKS:
            if task == "complete_unit" and not rest.strip():
                continue
            # Two calls, not one bilingual prompt. The English call still says which
            # language to answer in. The native call is only the native-language question.
            out.append({
                **base, "task": task, "condition": "ask_english",
                **prompt_for(english_tmpl[task], fields, f"\nAnswer in the language of {edition_name(version)}."),
                "expected": expected[task],
            })
            out.append({
                **base, "task": task, "condition": "ask_native",
                **prompt_for(native_tmpl[task], fields),
                "expected": expected[task],
            })
        if english is None:
            continue
        head_e, rest_e = split_words(english)
        fields_e = {
            "citation": passage.citation, "version": edition_name(english_version),
            "head": prompt_text(head_e), "text": prompt_text(english), "example": example,
        }
        expected_e = {
            "retrieve_quote": {"text": english},
            "complete_unit": {"text": rest_e, "full_text": english},
            "cite_passage": {"citation": cited},
            "verify_source": {
                "answer": "yes", "true_tradition": tradition,
                "true_version": english_version, "true_citation": passage.citation,
            },
        }
        for task in TASKS:
            if task == "complete_unit" and not rest_e.strip():
                continue
            # One English question. The edition name is already in that line.
            out.append({
                **base, "task": task, "condition": "en_ask_en_answer",
                "english_version": english_version, **prompt_for(english_tmpl[task], fields_e), "expected": expected_e[task],
            })
    return out


def _saheeh() -> dict[str, str]:
    data = json.loads(QURAN_EN_FILE.read_text(encoding="utf-8"))
    return {key: row["t"].strip() for key, row in data.items() if isinstance(row, dict) and row.get("t", "").strip()}


def islam() -> list[dict]:
    quran = json.loads(QURAN_FILE.read_text())
    english = _saheeh()
    famous_rows = famous_passages("The Qur'an", QURAN_VERSION)
    famous_cit = {p.citation: p for p in famous_rows}
    ordinary, famous = [], []
    for key, row in quran.items():
        text = row["text"].strip()
        if len(text.split()) >= MIN_WORDS:
            passage = famous_cit.get(key) or Passage(key, "The Qur'an", QURAN_VERSION)
            ordinary.append((passage, text))
        elif key in famous_cit:
            famous.append((famous_cit[key], text))
    missing = set(famous_cit) - set(quran)
    if missing:
        raise SystemExit(f"Qur'an famous citations missing from QUL: {sorted(missing)}")
    drawn = population_draw([p for p, _ in ordinary], famous_rows, seed=20261030)
    text = {p.citation: t for p, t in ordinary + famous}
    panel = list(drawn) + [famous_cit[c] for c in famous_cit]
    absent = [p.citation for p in panel if p.citation not in english]
    if absent:
        raise SystemExit(f"Saheeh International is missing Qur'an citations: {absent}")
    items = [(p, "population", text[p.citation], english[p.citation]) for p in drawn]
    items += [(famous_cit[c], "familiarity", text[c], english[c]) for c in famous_cit]
    return rows_for(
        items, tradition="Islam", version=QURAN_VERSION, native_tmpl=QURAN_AR,
        english_version=QURAN_EN_VERSION, english_native_tmpl=EN,
    )


def sikhism() -> list[dict]:
    lines = json.loads((RAW / "Sikhism" / "sggs_shabados.json").read_text())["lines"]
    prev_ang, k = 0, 0
    pool = []
    by_ang: dict[str, list[tuple[str, str, str]]] = {}
    for rec in lines:
        ang = rec["ang"]
        if rec.get("id") in _SGGS_ANG_ERRATA:
            _upstream, correct = _SGGS_ANG_ERRATA[rec["id"]]
            ang = correct
        k = k + 1 if ang == prev_ang else 1
        prev_ang = ang
        text = clean_sggs_line(rec["data"])
        if text:
            pool.append((f"Ang {ang}:{k}", text))
            by_ang.setdefault(f"Ang {ang}", []).append((f"Ang {ang}:{k}", text, rec["data"]))
    text = dict(pool)
    famous = famous_passages("Sri Guru Granth Sahib", "Shabad OS (SGPC Shabadaarth)")
    missing = {p.citation for p in famous} - set(text)
    if missing:
        raise SystemExit(f"SGGS famous citations missing: {sorted(missing)}")
    ordinary = [
        Passage(cit, "Sri Guru Granth Sahib", "Shabad OS (SGPC Shabadaarth)")
        for cit, body in pool
        if len(body.split()) >= MIN_WORDS
    ]
    drawn = population_draw(ordinary, famous, seed=20261030)
    pa = {
        "retrieve_quote": "ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ ਦੇ {ang} ਦੀ {edge} ਪੰਕਤੀ ਦਾ ਪਾਠ ਦੱਸੋ। ਸਿਰਫ਼ ਉਸੇ ਅਡੀਸ਼ਨ ਦਾ ਪਾਠ ਲਿਖੋ।",
        "complete_unit": 'ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ ਵਿਚੋਂ ਇਹ ਟੋਟਾ ਪੂਰਾ ਕਰੋ: "{head}" ਸਿਰਫ਼ ਬਾਕੀ ਸ਼ਬਦ ਲਿਖੋ।',
        "cite_passage": 'ਇਹ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ ਵਿਚ ਕਿੱਥੇ ਹੈ? "{text}" ਸਿਰਫ਼ ਅੰਗ (ਪੰਨਾ) ਲਿਖੋ, ਇਸ ਰੂਪ ਵਿਚ: {example}.',
        "verify_source": 'ਕੀ ਇਹ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ ਵਿਚੋਂ ਹੈ? "{text}" ਹਾਂ ਜਾਂ ਨਹੀਂ।',
    }
    items = [(p, "population", text[p.citation], None) for p in drawn]
    items += [(p, "familiarity", text[p.citation], None) for p in famous]
    version = "Shabad OS (SGPC Shabadaarth)"
    # rows_for renders retrieve_quote from a placeholder; the loop below asks it of an edge pankti,
    # the first and last in turn by passage.
    edge_later = {"retrieve_quote": "{citation}"}
    rows = rows_for(
        items, tradition="Sikhism", version=version, native_tmpl={**pa, **edge_later},
        english_tmpl={**SGGS_EN, **edge_later}, cited_as=sggs_ang,
    )
    order = {p.citation: i for i, (p, *_rest) in enumerate(items)}
    name = edition_name(version)
    named = asked_as("Sri Guru Granth Sahib", version)
    if set(named) != {p.citation for p in famous}:
        raise SystemExit(f"every SGGS familiarity passage needs asked_as in well_known.yaml: {sorted(named)}")
    taken: dict[tuple[str, str, str], set[str]] = {}  # (sample, condition, Ang) -> edges asked
    for row in rows:
        if row["task"] != "retrieve_quote":
            continue
        if row["sample"] == "familiarity":
            # Famous by name: ask for the passage itself. Prompt, citation and expected text are its own.
            english, native = named[row["citation"]]
            if row["condition"] == "ask_english":
                tmpl, fields, suffix = SGGS_NAMED_EN, {"name": english}, f"\nAnswer in the language of {name}."
            else:
                tmpl, fields, suffix = SGGS_NAMED_PA, {"name": native}, ""
            row.update(prompt_for(tmpl, {**fields, "version": name, "text": row["expected"]["text"]}, suffix))
            continue
        ang = sggs_ang(row["citation"])
        prefer = "first" if order[row["citation"]] % 2 == 0 else "last"
        asked = taken.setdefault((row["sample"], row["condition"], ang), set())
        picked = sggs_edge_pankti(by_ang[ang], prefer, asked)
        row["drawn"] = {"citation": row["citation"], "text": row["expected"]["text"]}
        if picked is None:
            # Both edges of this Ang are asked already (or are headings). The row stays in the set
            # as a verify donor (verify_donors) but is not written out.
            row["unasked"] = True
            continue
        edge, citation, edge_text = picked
        asked.add(edge)
        english, gurmukhi = SGGS_EDGE_WORDS[edge]
        if row["condition"] == "ask_english":
            tmpl, word, suffix = SGGS_EN["retrieve_quote"], english, f"\nAnswer in the language of {name}."
        else:
            tmpl, word, suffix = pa["retrieve_quote"], gurmukhi, ""
        fields = {"ang": ang, "edge": word, "version": name, "text": edge_text}
        row.update(prompt_for(tmpl, fields, suffix))
        row["citation"] = citation
        row["expected"] = {"text": edge_text}
    return rows


def judaism() -> list[dict]:
    root = RAW / "Judaism" / "Talmud Bavli"
    pairs = []
    for he_path in sorted(root.glob("* - he - William Davidson Edition - Aramaic.json")):
        tract = he_path.name.split(" - he - ")[0]
        en_path = root / f"{tract} - en - William Davidson Edition - English.json"
        if not en_path.exists():
            continue
        he = json.loads(he_path.read_text())["text"]
        en = json.loads(en_path.read_text())["text"]
        if len(he) != len(en):
            raise SystemExit(f"{tract}: Aramaic has {len(he)} sections, English has {len(en)}")
        for i, (sec_h, sec_e) in enumerate(zip(he, en)):
            if not sec_h or not sec_e:
                continue
            daf = (i // 2) + 1
            side = "a" if i % 2 == 0 else "b"
            # A daf side can end with one extra segment in one edition. Pair only
            # the shared indexes. An unpaired tail has no wording in the other edition.
            paired = min(len(sec_h), len(sec_e))
            for n, (a, b) in enumerate(zip(sec_h[:paired], sec_e[:paired]), start=1):
                if not isinstance(a, str) or not isinstance(b, str):
                    continue
                ha, eb = clean_html(a), clean_html(b)
                if len(ha.split()) >= MIN_WORDS and len(eb.split()) >= MIN_WORDS:
                    pairs.append((f"{tract} {daf}{side}:{n}", ha, eb))
                    break
    text = {c: (h, e) for c, h, e in pairs}
    famous = famous_passages("Talmud Bavli", "William Davidson Edition - Aramaic")
    missing = {p.citation for p in famous} - set(text)
    if missing:
        raise SystemExit(f"Talmud famous citations missing: {sorted(missing)}")
    ordinary = [
        Passage(c, "Talmud Bavli", "William Davidson Edition - Aramaic")
        for c in text
    ]
    drawn = population_draw(ordinary, famous, seed=20261030)
    he = {
        "retrieve_quote": "מהו נוסח {citation} בתלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית? ענה בנוסח אותה מהדורה בלבד.",
        "complete_unit": 'השלם ציטוט זה מהתלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית: "{head}" ענה במילים הנותרות בלבד.',
        "cite_passage": 'היכן בתלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית, נמצא הטקסט הזה? "{text}" ענה בציון המקום בלבד, בצורה: {example}.',
        "verify_source": 'האם הטקסט הבא מן התלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית? "{text}" ענה כן או לא.',
    }
    he_en = {
        "retrieve_quote": "מהו הנוסח האנגלי של {citation} בתלמוד הבבלי, מהדורת ויליאם דייווידסון האנגלית? ענה בנוסח אותה מהדורה בלבד.",
        "complete_unit": 'השלם ציטוט זה מהתלמוד הבבלי, מהדורת ויליאם דייווידסון האנגלית: "{head}" ענה במילים הנותרות בלבד.',
        "cite_passage": 'היכן בתלמוד הבבלי, מהדורת ויליאם דייווידסון האנגלית, נמצא הטקסט הזה? "{text}" ענה בציון המקום בלבד, בצורה: {example}.',
        "verify_source": 'האם הטקסט הבא מן התלמוד הבבלי, מהדורת ויליאם דייווידסון האנגלית? "{text}" ענה כן או לא.',
    }
    items = [(p, "population", *text[p.citation]) for p in drawn]
    items += [(p, "familiarity", *text[p.citation]) for p in famous]
    rows = rows_for(
        items, tradition="Judaism", version="William Davidson Edition - Aramaic",
        native_tmpl=he, english_version="William Davidson Edition - English",
        english_native_tmpl=he_en,
    )
    note = "William Davidson Edition on Sefaria, CC-BY-NC. Attribute Sefaria and the William Davidson Edition."
    for row in rows:
        row["license"] = note
    return rows


NOTICE = (
    "Scripture quotations are from the New Revised Standard Version Bible, "
    "copyright © 1989 National Council of the Churches of Christ in the United States of America. "
    "Used by permission. All rights reserved worldwide."
)
NRSV_URL = "https://bible.oremus.org/?version=nrsv&passage="
_PSALM_HEAD = re.compile(r"^Psalm\s+\d+\s+\d+\s+")
_OREMUS_BOOK = {"Psalms": "Psalm", "Song of Solomon": "Song of Songs"}


def fetch_nrsv(citation: str) -> str:
    """One verse from oremus's NRSV. The draw uses the Protestant citation list; this is the wording."""
    book, ref = citation.rsplit(" ", 1)
    query = f"{_OREMUS_BOOK.get(book, book)} {ref}"
    url = NRSV_URL + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "academic-nrsv-draw"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    match = re.search(r'class="bibletext">(.*?)</div>', raw, re.S)
    if not match:
        raise SystemExit(f"no NRSV text for {citation}")
    chunk = re.sub(r"<[^>]+>", " ", match.group(1))
    chunk = html.unescape(re.sub(r"\s+", " ", chunk)).strip()
    chunk = re.sub(r"^\d+\s*", "", chunk).strip(" “”\"")
    chunk = _PSALM_HEAD.sub("", chunk)
    if not chunk:
        raise SystemExit(f"empty NRSV text for {citation}")
    return chunk


def christianity() -> list[dict]:
    """Seeded draw over the Protestant verse list. Wording is NRSV, not KJV."""
    kjv = json.loads((RAW / "Protestant Christian" / "kjv.json").read_text())
    famous = famous_passages("The Bible", "NRSV")
    famous_ids = {p.citation for p in famous}
    ordinary = []
    for row in kjv:
        citation = f"{row['book']} {row['chapter']}:{row['verse']}"
        if len(row["text"].split()) >= MIN_WORDS:
            ordinary.append(Passage(citation, "The Bible", "NRSV"))
    missing = famous_ids - {f"{r['book']} {r['chapter']}:{r['verse']}" for r in kjv}
    if missing:
        raise SystemExit(f"NRSV famous citations missing from the Protestant verse list: {sorted(missing)}")
    drawn = population_draw(ordinary, famous, seed=20261030)
    panel = list(drawn) + list(famous)
    verses = {p.citation: fetch_nrsv(p.citation) for p in panel}
    version = edition_name("NRSV")
    citations = [p.citation for p in panel]
    rows = []
    for passage in panel:
        sample = "population" if passage in drawn else "familiarity"
        text = verses[passage.citation]
        head, rest = split_words(text)
        example = next(c for c in citations if c != passage.citation)
        base = {
            "tradition": "Christianity", "citation": passage.citation,
            "sample": sample,
            "stratum": "famous" if sample == "familiarity" else "ordinary",
            "version": "NRSV", "condition": "en_ask_en_answer", "copyright": NOTICE,
        }
        fields = {"citation": passage.citation, "version": version, "head": head, "text": text, "example": example}
        expected = {
            "retrieve_quote": {"text": text},
            "complete_unit": {"text": rest, "full_text": text},
            "cite_passage": {"citation": passage.citation},
            "verify_source": {
                "answer": "yes", "true_tradition": "Christianity", "true_version": "NRSV",
                "true_language": "en", "true_citation": passage.citation,
            },
        }
        for task in TASKS:
            if task == "complete_unit" and not rest.strip():
                continue
            rows.append({**base, "task": task, **prompt_for(EN[task], fields), "expected": expected[task]})
    return rows


def _script(text: str) -> str:
    for ch in text:
        o = ord(ch)
        if 0x0590 <= o <= 0x05FF:
            return "he"
        if 0x0600 <= o <= 0x06FF:
            return "ar"
        if 0x0900 <= o <= 0x097F:
            return "sa"
        if 0x0A00 <= o <= 0x0A7F:
            return "pa"
        if 0x0370 <= o <= 0x03FF:
            return "grc"
    return "lat"


_NT = {
    "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians", "2 Corinthians",
    "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
    "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter",
    "1 John", "2 John", "3 John", "Jude", "Revelation",
}


def _asked_version(row: dict) -> str:
    """The catalogue version a row asks about: its English edition when it has one."""
    return row.get("english_version") or row["version"]


def _is_native(row: dict) -> bool:
    """A native edition (asked in either prompt language), not an English edition."""
    return row["condition"] != "en_ask_en_answer"


# The two English supplemental categories quote each other (METHODOLOGY.md).
_SUPPLEMENTAL_SWAP = {"Book of Mormon": "Encyclicals", "Encyclicals": "Book of Mormon"}


def _donor_pool(row: dict, donors: list[dict]) -> list[dict]:
    """The passages a verify "no" row may quote: METHODOLOGY.md's donor table, one rule per edition.

    The donor is always another work. The Qur'an's hadith donors are drawn by the caller.
    """
    version = _asked_version(row)
    if row["tradition"] == "Judaism" and _is_native(row):
        rule = lambda d: "Masoretic" in d["version"]  # Aramaic Talmud: the Masoretic text
    elif row["tradition"] == "Judaism":
        # English Talmud: the NRSV's Hebrew Bible verses, never the New Testament
        rule = lambda d: d["version"] == "NRSV" and d["citation"].rsplit(" ", 1)[0] not in _NT
    elif version == "NRSV":
        rule = lambda d: d["tradition"] == "Book of Mormon"
    elif "Masoretic" in version:
        rule = lambda d: d["tradition"] == "Judaism" and _is_native(d)  # the Aramaic Talmud
    elif row["tradition"] in _SUPPLEMENTAL_SWAP:
        rule = lambda d: d["tradition"] == _SUPPLEMENTAL_SWAP[row["tradition"]]
    elif not _is_native(row):
        rule = lambda d: not _is_native(d)  # the English Gita: another tradition's English work
    else:
        # Greek NT, Guru Granth Sahib, Sanskrit Gita, Pali Dhammapada: no second work in that
        # language, so another tradition's native passage in a different script, never English.
        script = _script(row["payload"])
        rule = lambda d: _is_native(d) and _script(d["expected"]["text"]) != script
    pool = [d for d in donors if d["tradition"] != row["tradition"] and rule(d)]
    if not pool:
        raise SystemExit(f"no verify_source donor for {row['tradition']} {version} {row['citation']}")
    return pool


def verify_donors(by_name: dict[str, list[dict]]) -> list[dict]:
    """Every set's passages, once each, in a fixed order: the pool every "no" row draws from."""
    donors: dict[tuple[str, str, str], dict] = {}
    for rows in by_name.values():
        for row in rows:
            if row["task"] == "retrieve_quote":
                # A row that asks about another pankti than its drawn passage (the Sri Guru Granth
                # Sahib's edge panktis) keeps the passage as the donor, so no other set's "no" rows move.
                passage = row.get("drawn") or {"citation": row["citation"], "text": row["expected"]["text"]}
                key = (row["tradition"], _asked_version(row), passage["citation"])
                donors.setdefault(key, {
                    "tradition": row["tradition"], "version": key[1], "citation": passage["citation"],
                    "condition": row["condition"], "expected": {"text": passage["text"]},
                })
    return [donors[key] for key in sorted(donors)]


def hadith_collections() -> list:
    """The catalogue targets of the six canonical collections (Arabic), in KUTUB_AL_SITTAH order."""
    source = load_source(RAW / "Sunni Islam" / "source.yaml", raw_root=RAW)
    by_work: dict[str, list] = {}
    for target in source.targets:
        if target.converter == "hadith_sunnah" and target.language == "ar":
            by_work.setdefault(target.work, []).append(target)
    bad = [work for work in KUTUB_AL_SITTAH if len(by_work.get(work, [])) != 1]
    if bad:
        raise SystemExit(f"source.yaml needs exactly one Arabic hadith_sunnah target for each of {bad}")
    return [by_work[work][0] for work in KUTUB_AL_SITTAH]


# A donor is a SAYING of the Prophet (owner, #75 round 2): the span sunnah.com puts in quotation marks
# right after a salawat (… صلى الله عليه وسلم ‏"‏ …), optionally with a speech verb between
# (قَالَ / يَقُولُ / فَقَالَ / أَنَّهُ قَالَ), up to its closing mark. Neither the narrator chain (isnad)
# nor anything after the closing mark (a narrator's remark, a second chain, the compiler's commentary)
# is quoted. sunnah.com writes these words bare, vowelled (in either mark order) and broken across
# lines, so each is matched letter by letter with any vowel marks, dagger alif or tatweel after a
# letter, and any alef (with or without hamza) for an alef.
_AR_MARKS = "[\u064b-\u065f\u0670\u0640]*"
_AR_LETTER = "\u0621-\u064a"


def _arabic_phrase(*words: str) -> str:
    """A regex for these Arabic words however sunnah.com vowels them or breaks the line."""
    def letter(c: str) -> str:
        return ("[\u0627\u0623\u0625\u0622\u0671]" if c in "\u0627\u0623" else re.escape(c)) + _AR_MARKS
    return r"\s+".join("".join(letter(c) for c in word) for word in words)


_SALAWAT = re.compile("(?:" + _arabic_phrase("صلى", "الله", "عليه", "وسلم") + "|\ufdfa)")
# whole words, so قَالَتْ ("she said") and يَقُولُوا are not speech verbs here
_SPEECH_VERB = "(?:" + "|".join(
    _arabic_phrase(*verb) for verb in (("أنه", "قال"), ("فقال",), ("قال",), ("يقول",))
) + f")(?!{_AR_MARKS}[{_AR_LETTER}])"
_GAP = "[\\s\u200e\u200f:\u060c,.\\-\u2013\u2014\u0640]*"  # spaces, LRM/RLM, colon, comma, dash, tatweel
_SAYING_OPEN = re.compile(_SALAWAT.pattern + _GAP + f"(?:{_SPEECH_VERB}{_GAP})?" + '"')
# separators sunnah.com puts just inside the opening mark
_MATN_LEAD = re.compile("^[\\s\u200e\u200f\u0640.:\u060c,\u061b\\-\u2013\u2014]+")
# A span that opens a narrator chain or a reported clause (حَدَّثَنَا, عَنْ, أَنَّ …) announces "hadith"
# from its first word. Compared by letters only, hamza kept, so أَنَّ is caught and إِنَّ ("indeed") is not.
_CHAIN_OPENERS = frozenset({
    "حدثنا", "حدثني", "أخبرنا", "أخبرني", "اخبرنا", "اخبرني", "أنبأنا", "انبانا", "عن", "وعن", "أن",
})
_DIVINE_EPITHET = r"(?:\s+(?:" + "|".join(
    _arabic_phrase(*e) for e in (("تعالى",), ("عز", "وجل"), ("تبارك", "وتعالى"), ("سبحانه",))
) + "))?"
_SAYS = "(?:" + _arabic_phrase("قال") + "|" + _arabic_phrase("يقول") + ")"
_WORD_END = f"(?!{_AR_MARKS}[{_AR_LETTER}])"
# God's speech inside the saying (hadith qudsi, or a Qur'an citation framed as قَالَ اللَّهُ): not the
# Prophet's own words, so not a donor — قَالَ اللَّهُ / يَقُولُ اللَّهُ / قَالَ رَبُّكُمْ / إِنَّ اللَّهَ … قَالَ
_DIVINE_SPEECH = re.compile("(?:" + "|".join((
    _SAYS + r"\s+(?:" + "|".join(_arabic_phrase(w) for w in ("الله", "ربكم", "ربك", "ربي")) + ")" + _WORD_END,
    _arabic_phrase("إن", "الله") + _DIVINE_EPITHET + r"\s+" + _SAYS + _WORD_END,
)) + ")")


def _letters(word: str) -> str:
    """A word's letters only, hamza kept: no vowel marks or punctuation (أَنَّ → أن, إِنَّ → إن)."""
    return "".join(c for c in unicodedata.normalize("NFC", word) if unicodedata.category(c).startswith("L"))


def hadith_matn(text: str) -> str | None:
    """The quotable saying of a sunnah.com hadith, or None when it has none.

    The saying is the first quoted span that opens right after a salawat (with an optional speech verb
    between), up to its closing quotation mark, without the right-to-left marks sunnah.com puts around
    its quotation marks. None when there is no such span, or when the span
    - has fewer than MIN_WORDS words;
    - opens with a narrator chain or reported clause (حَدَّثَنَا, أَخْبَرَنَا, عَنْ, وَعَنْ, أَنَّ, …);
    - reads as a bare verdict itself ("لاَ، …", "نَعَمْ.") by the scorer's own ``parse_yes_no``;
    - carries God's speech (قَالَ اللَّهُ, يَقُولُ اللَّهُ, إِنَّ اللَّهَ … قَالَ): hadith qudsi are out;
    - carries a salawat (صلى الله عليه وسلم): the Qur'an never does, so it would announce "hadith".
    """
    opening = _SAYING_OPEN.search(text)
    if opening is None:
        return None
    closing = text.find('"', opening.end())
    if closing == -1:
        return None
    span = _MATN_LEAD.sub("", text[opening.end():closing])
    matn = " ".join(span.replace("‎", "").replace("‏", "").split())
    words = matn.split()
    if len(words) < MIN_WORDS or _letters(words[0]) in _CHAIN_OPENERS:
        return None
    if parse_yes_no(matn, "ar") is not None or _DIVINE_SPEECH.search(matn) or _SALAWAT.search(matn):
        return None
    return matn


@functools.lru_cache(maxsize=None)
def _hadith_pool() -> tuple[dict, ...]:
    """Every hadith with a quotable matn, as donor rows, in catalogue then book order.

    Shaped like a ``retrieve_quote`` donor. Citation and version mirror ``convert_hadith_sunnah``, so a
    "no" item records the same true_version / true_citation the standardized corpus would. Parsed on
    the first Arabic flip only; a build with no Arabic passage never reads the hadith files.
    """
    pool = []
    for target in hadith_collections():
        data = json.loads((RAW / "Sunni Islam" / target.payload).read_text(encoding="utf-8"))
        for h in data["hadiths"]:
            matn = hadith_matn(h.get("arabic") or "")
            if matn is None:
                continue
            pool.append({
                "tradition": "Islam",
                "work": target.work,
                "version": target.version,
                "citation": f"{target.work} {h['idInBook']}",
                "expected": {"text": matn},
            })
    if not pool:
        raise SystemExit("no hadith matn found for the Qur'an verify_source 'no' items")
    return tuple(pool)


# Letters the Uthmani and Imla'i orthographies spell differently (long ā, alef-maqsura / ya, hamza,
# wasla, the waw of ٱلصَّلَوٰة). Dropping them gives one consonantal skeleton per word in either spelling.
_ORTHOGRAPHY_VARIABLE = frozenset("اىيءٱو")


def _skeleton(text: str) -> str:
    """Arabic base letters only, minus the orthography-variable ones.

    Marks, tatweel, Qur'anic annotation signs, digits, punctuation and spaces all go, so every
    spelling of the same words has the same skeleton. ``_skeleton(a) in _skeleton(b)`` is therefore a
    necessary condition for ``fold_aware_contains(b, a)``: a prefilter, never a verdict.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if "؀" <= c <= "ࣿ" and unicodedata.category(c) == "Lo"
        and c not in _ORTHOGRAPHY_VARIABLE and not "ۖ" <= c <= "ۭ"
    )


def _skeleton_words(text: str) -> list[str]:
    """The text's words as skeletons, dropping words that have none (pause marks, a lone يا)."""
    return [s for s in (_skeleton(w) for w in text.split()) if s]


@functools.lru_cache(maxsize=None)
def _quran_index() -> tuple[list[tuple[str, str, str]], dict[tuple[str, ...], str]]:
    """Every ayah as (citation, text, skeleton), and each run of QURAN_SHARED_WORDS skeleton words → an ayah."""
    quran = json.loads(QURAN_FILE.read_text(encoding="utf-8"))
    ayahs = [(key, row["text"], _skeleton(row["text"])) for key, row in quran.items()]
    runs: dict[tuple[str, ...], str] = {}
    n = QURAN_SHARED_WORDS
    for key, text, _ in ayahs:
        words = _skeleton_words(text)
        for i in range(len(words) - n + 1):
            runs.setdefault(tuple(words[i:i + n]), key)
    return ayahs, runs


def quran_overlap(text: str) -> str | None:
    """The citation of an ayah the text shares Qur'an wording with, or None (owner-raised, #75).

    Hadith quote the Qur'an, so a hadith donor could make a "no" item partly true. Shared wording is:
    the text contains a whole ayah, or lies inside one (``fold_aware_contains``, both directions,
    orthography-aware); or it shares QURAN_SHARED_WORDS consecutive words with one, comparing
    consonantal skeletons so Uthmani and Imla'i spellings of the same words match.
    """
    ayahs, runs = _quran_index()
    words = _skeleton_words(text)
    n = QURAN_SHARED_WORDS
    for i in range(len(words) - n + 1):
        hit = runs.get(tuple(words[i:i + n]))
        if hit is not None:
            return hit
    skeleton = _skeleton(text)
    for key, ayah, ayah_skeleton in ayahs:
        if ayah_skeleton in skeleton and fold_aware_contains(text, ayah):
            return key
        if skeleton in ayah_skeleton and fold_aware_contains(ayah, text):
            return key
    return None


# Curated after reading every drawn donor (owner check, PR #78 round 3), keyed by "{work} {number}".
# Applied at draw time, like the Qur'an-overlap screen, so only the rows that drew one of these re-draw.
DONOR_SKIP = {
    "Sahih al-Bukhari 6784": "reply fragment from a longer hadith; shares 5 words with 9:102",
    "Sahih al-Bukhari 7122": "God's words (إِنَّ رَحْمَتِي تَغْلِبُ غَضَبِي) without a قَالَ اللَّهُ frame",
}


def english_hadith_collections() -> list:
    """The six canonical collections in English, same books and order as the Arabic donors."""
    source = load_source(RAW / "Sunni Islam" / "source.yaml", raw_root=RAW)
    by_work: dict[str, list] = {}
    for target in source.targets:
        if target.converter == "hadith_sunnah_en" and target.language == "en":
            by_work.setdefault(target.work, []).append(target)
    bad = [work for work in KUTUB_AL_SITTAH if len(by_work.get(work, [])) != 1]
    if bad:
        raise SystemExit(f"source.yaml needs exactly one English hadith target for each of {bad}")
    return [by_work[work][0] for work in KUTUB_AL_SITTAH]


@functools.lru_cache(maxsize=None)
def _saheeh_word_runs() -> set[tuple[str, ...]]:
    """Every run of 6 Saheeh words, so an English hadith that quotes an ayah is skipped."""
    runs: set[tuple[str, ...]] = set()
    n = QURAN_SHARED_WORDS
    for text in _saheeh().values():
        words = text.casefold().split()
        for i in range(len(words) - n + 1):
            runs.add(tuple(words[i:i + n]))
    return runs


def _english_matn(text: str) -> str | None:
    """The saying itself, without the narrator line or the compiler's note.

    sunnah.com's English ``text`` often wraps the saying in quotes and then adds
    a remark ("This is the wording of…"). A quote mark left inside the prompt
    cuts the question off at the first mark, so the span we keep has none.
    """
    text = re.sub(r"\s+", " ", text).strip()
    text = re.split(
        r" This is the wording of | There is something on this topic | Hadith\. Similar ",
        text,
    )[0].strip()
    spans = re.findall(r'"([^"]+)"', text) + re.findall(r"“([^”]+)”", text)
    spans = [re.sub(r"\s+", " ", span).strip() for span in spans]
    long = [span for span in spans if len(span.split()) >= MIN_WORDS and '"' not in span and "“" not in span]
    if long:
        return max(long, key=lambda span: len(span.split()))
    if len(text.split()) >= MIN_WORDS and '"' not in text and "“" not in text and "”" not in text:
        return text
    return None


def _english_quotes_quran(text: str) -> bool:
    words = text.casefold().split()
    n = QURAN_SHARED_WORDS
    runs = _saheeh_word_runs()
    return any(tuple(words[i:i + n]) in runs for i in range(len(words) - n + 1))


@functools.lru_cache(maxsize=None)
def _english_hadith_pool() -> tuple[dict, ...]:
    """English matn of the six books: the translator's text, not the narrator line.

    A saying under 16 words, or one that repeats 6 consecutive Saheeh words, is not a donor.
    """
    pool = []
    for target in english_hadith_collections():
        path = target.payload_paths(RAW)[0]
        for hadith in json.loads(path.read_text(encoding="utf-8"))["hadiths"]:
            english = hadith.get("english") or {}
            text = _english_matn(english.get("text") or "")
            if text is None or _english_quotes_quran(text):
                continue
            pool.append({
                "tradition": "Islam",
                "version": target.version,
                "citation": f"{target.work} {hadith['idInBook']}",
                "expected": {"text": text},
            })
    if not pool:
        raise SystemExit("no English hadith matn for the English Qur'an verify_source 'no' items")
    return tuple(pool)


def _english_hadith_donor(row: dict, quoted: frozenset[str] | set[str] = frozenset()) -> dict:
    """This English-Qur'an row's donor. Seeded by the row, like the Arabic hadith donor.

    A matn its set already quotes (``quoted``) is skipped for the row's next draw (#116)."""
    pool = _english_hadith_pool()
    rng = random.Random(f"{HADITH_SEED}|en|{row['condition']}|{row['sample']}|{row['citation']}")
    for _ in range(1000):
        donor = pool[rng.randrange(len(pool))]
        if donor["expected"]["text"] not in quoted:
            return donor
    raise SystemExit(f"no English hadith donor not already quoted in its set for {row['citation']}")


def _hadith_donor(row: dict, quoted: frozenset[str] | set[str] = frozenset()) -> dict:
    """This row's hadith donor, from an RNG seeded by the row alone (condition, sample, citation).

    No other row, edition or tradition can move it, except an earlier row in its set that drew the
    same matn. A candidate on DONOR_SKIP, one that shares Qur'an wording, or one its set already
    quotes (``quoted``, #116) is skipped for the row's next draw.
    """
    pool = _hadith_pool()
    unknown = set(DONOR_SKIP) - {d["citation"] for d in pool}
    if unknown:
        raise SystemExit(f"DONOR_SKIP names hadith that are not in the donor pool: {sorted(unknown)}")
    rng = random.Random(f"{HADITH_SEED}|{row['condition']}|{row['sample']}|{row['citation']}")
    for _ in range(1000):
        donor = pool[rng.randrange(len(pool))]
        if (donor["citation"] not in DONOR_SKIP and donor["expected"]["text"] not in quoted
                and quran_overlap(donor["expected"]["text"]) is None):
            return donor
    raise SystemExit(f"no hadith donor free of Qur'an wording and not already quoted in its set for {row['citation']}")


def _verify_donor(row: dict, donors: list[dict], quoted: frozenset[str] | set[str]) -> tuple[dict, str]:
    """A verify "no" row's donor and the text its prompt quotes, never one of the ``quoted`` texts.

    Each branch draws from an RNG seeded by the row alone. A quoted text is skipped and the same
    RNG draws again, so with nothing quoted this is the row's first draw.
    """
    if _script(row["payload"]) == "ar":
        donor = _hadith_donor(row, quoted)
        return donor, donor["expected"]["text"]
    if row["tradition"] == "Islam" and row["condition"] == "en_ask_en_answer":
        donor = _english_hadith_donor(row, quoted)
        return donor, donor["expected"]["text"]
    pool = _donor_pool(row, donors)
    if all(prompt_text(d["expected"]["text"]) in quoted for d in pool):
        raise SystemExit(f"every verify_source donor for {row['tradition']} {row['citation']} is already quoted in its set")
    seed = "|".join([str(HADITH_SEED), row["tradition"], _asked_version(row),
                     row["condition"], row["sample"], row["citation"]])
    rng = random.Random(seed)
    for _ in range(1000):
        donor = rng.choice(pool)
        if prompt_text(donor["expected"]["text"]) not in quoted:
            return donor, prompt_text(donor["expected"]["text"])
    raise SystemExit(f"no verify_source donor not already quoted in its set for {row['tradition']} {row['citation']}")


def add_verify_negatives(by_name: dict[str, list[dict]]) -> None:
    """Half of each set's verify_source rows, per condition and sample, quote a different work.

    The donor follows METHODOLOGY.md's table (``_donor_pool``). An Arabic passage (the Qur'an) has the
    hadith collections as its same-script neighbours, so its donor is a hadith matn that shares no
    Qur'an wording (issue #75); the English Qur'an's donor is an English hadith. Every donor comes
    from an RNG seeded by its row alone, over a pool in a fixed order, so no other set or build
    order can move it and one run of ``main`` reproduces every file (issue #91).

    A set quotes each donor at most once (issue #116). Every row first takes its own first draw. In
    citation order, the first row to draw a text keeps it; a later row that drew the same text draws
    again from its own RNG, skipping every text the set's first draws took, so only that row changes.
    """
    donors = verify_donors(by_name)
    for rows in by_name.values():
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            if row["task"] == "verify_source":
                groups.setdefault((row["condition"], row["sample"]), []).append(row)
        for group in groups.values():
            group.sort(key=lambda r: r["citation"])
            negatives = group[: len(group) // 2]
            first = [_verify_donor(row, donors, frozenset()) for row in negatives]
            quoted = {text for _, text in first}
            kept: set[str] = set()
            for row, (donor, text) in zip(negatives, first):
                if text in kept:
                    donor, text = _verify_donor(row, donors, quoted)
                    quoted.add(text)
                kept.add(text)
                row["expected"] = {
                    "answer": "no",
                    "true_tradition": donor["tradition"],
                    "true_version": donor["version"],
                    "true_citation": donor["citation"],
                }
                # The same template, rendered around the donor (PR #98): never a splice between quote marks.
                row["prompt"], row["payload"] = row["render"](text), text


_RUN_META = {
    "Christianity": ("The Bible", "en", "scripture"),
    "Judaism": ("Talmud Bavli", "he", "talmud"),
    "Islam": ("The Qur'an", "ar", "scripture"),
    "Sikhism": ("Sri Guru Granth Sahib", "pa", "scripture"),
}


def _collect_row(row: dict) -> dict:
    work, language, document_type = _RUN_META[row["tradition"]]
    asked = row.get("english_version") or row["version"]
    if row["condition"] == "en_ask_en_answer":
        language = "en"
    expected = row["expected"]
    citation = row["citation"]
    if row["task"] == "verify_source" and expected.get("answer") == "no":
        citation = ""
    source = {
        "tradition": [row["tradition"]],
        "work": work,
        "version": asked,
        "language": language,
        "document_type": document_type,
        "citation": citation,
        "requested_as": asked,
        "sample": row["sample"],
        "condition": row["condition"],
    }
    # The prompt is part of the id. A verify "no" row clears its citation, so the
    # citation alone would give every negative the same id.
    ident = "|".join([
        row["tradition"], row["sample"], row["condition"], row["task"], row["citation"], row["prompt"],
    ])
    return {
        "id": hashlib.sha256(ident.encode()).hexdigest()[:16],
        "task": row["task"],
        "prompt": row["prompt"],
        "expected": expected,
        "source": source,
    }


def _language_dir(row: dict) -> Path:
    """christianity/english/population, judaism/native/familiarity, and so on.

    English-only traditions have no native folder. ``population`` is the 30
    passages the run uses. ``familiarity`` is the separate pre-registered list.
    """
    tradition = row["source"]["tradition"][0].lower()
    kind = "english" if row["source"]["language"] == "en" else "native"
    sample = row["source"].get("sample") or "population"
    base = REVIEW.parent / tradition / kind / sample
    prompt_lang = {"ask_english": "prompt-english", "ask_native": "prompt-native"}.get(row["source"].get("condition"))
    return base / prompt_lang if prompt_lang else base


def jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def passages_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def question_files(built: dict[str, list[dict]]) -> dict[Path, str]:
    """This script's four traditions as {path: file text}, under english or native, then the sample.

    The NRSV passages.json records where its wording was fetched, because it is not in the repo.
    """
    grouped: dict[Path, list[dict]] = {}
    for row in (_collect_row(r) for name in _RUN_META for r in built[name.lower()] if not r.get("unasked")):
        grouped.setdefault(_language_dir(row) / "questions.jsonl", []).append(row)
    files = {path: jsonl(rows) for path, rows in grouped.items()}
    for sample in ("population", "familiarity"):
        files[REVIEW.parent / "christianity" / "english" / sample / "passages.json"] = passages_json({
            "tradition": "Christianity", "sample": sample, "run": sample == "population",
            "passages": [
                {"tradition": "Christianity", "citation": r["citation"], "sample": sample,
                 "version": "NRSV", "text": {"english": r["expected"]["text"]}}
                for r in built["christianity"] if r["task"] == "retrieve_quote" and r["sample"] == sample
            ],
            "notice": NOTICE,
            "provenance": NRSV_URL + "{citation}",
        })
    return files


def build_all() -> dict[str, list[dict]]:
    """Every question set under items/for-test, its verify "no" rows drawn from one pool (issue #91)."""
    import build_christian_original
    import build_remaining
    import build_supplemental

    sets = {"christianity": christianity(), "judaism": judaism(), "islam": islam(), "sikhism": sikhism()}
    sets |= build_christian_original.build(sets["christianity"])
    sets |= build_supplemental.build()
    sets |= build_remaining.build()
    add_verify_negatives(sets)
    return sets


def output_files(sets: dict[str, list[dict]]) -> dict[Path, str]:
    """Every questions.jsonl, and the passages.json each set's builder writes, as {path: file text}."""
    import build_christian_original
    import build_remaining
    import build_supplemental

    return {
        **question_files(sets),
        **build_christian_original.output_files(sets),
        **build_supplemental.output_files(sets),
        **build_remaining.output_files(sets),
    }


def main() -> None:
    """Rebuild every question set. Run twice, the files are byte-identical (METHODOLOGY.md)."""
    for path, text in sorted(output_files(build_all()).items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(path.relative_to(REVIEW.parent))


if __name__ == "__main__":
    main()
