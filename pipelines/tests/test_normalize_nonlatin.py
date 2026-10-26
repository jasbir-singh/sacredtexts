"""Arabic/Hebrew normalisation (Spec 8, Phase 1).

`normalize()` must score Qur'an (Arabic) and Talmud (Hebrew/Aramaic) quotes fairly:
combining marks (harakat / niqqud / cantillation), tatweel, and the Qur'anic annotation
symbols are removed and letter variants folded, so a vocalised and an unvocalised spelling
of the same text are equal — in BOTH directions (a vocalised answer vs. an unvocalised
expected, and the reverse). Latin output must be byte-for-byte unchanged, and the scoring
contract (`_SUBMETRICS`, the `retrieve_quote` headline rule) must not move.

Real fixtures are read from the committed, open-licensed corpora (the QUL Uthmani Qur'an and
the Davidson VOCALISED Aramaic Shevuot file — the latter is deliberately excluded from the
conversion catalogue and is used here only as a mark fixture, never converted into the
corpus). Both files are public-domain / open and already tracked in the repo.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from sacredbench.score import normalize, score_answer, strip_script_marks, token_f1

REPO_ROOT = Path(__file__).resolve().parents[2]
QUL = REPO_ROOT / "texts" / "raw" / "Sunni Islam" / "quran_uthmani_from_qul.json.json"
SHEVUOT_VOCALIZED = (
    REPO_ROOT / "texts" / "raw" / "Judaism" / "Talmud Bavli"
    / "Shevuot - he - William Davidson Edition - Vocalized Aramaic.json"
)

def _strip_combining(s: str) -> str:
    """An INDEPENDENT 'unvocalised' form (stdlib only, not the implementation's block
    logic): NFKD then drop every category-Mn codepoint. Used to compare the real
    vocalised text against its bare-consonant spelling without reusing the code under
    test. The maqaf is mapped to a space to match the implementation's word-boundary
    rule (fixtures contain none today, but this keeps the helper honest if one appears)."""
    s = unicodedata.normalize("NFKD", s).replace("־", " ")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _has_surviving_mark(s: str) -> bool:
    """True if any combining mark or Arabic/Hebrew-block editorial code point remains."""
    editorial = frozenset("ـ") | frozenset(chr(c) for c in range(0x06D6, 0x06EE))
    return any(unicodedata.category(c).startswith("M") or c in editorial for c in s)


# --- Arabic ------------------------------------------------------------------


def test_arabic_vocalized_equals_plain_basmala():
    vocal = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
    plain = "بسم الله الرحمن الرحيم"
    assert normalize(vocal) == normalize(plain)
    assert token_f1(vocal, plain) == 1.0


def test_arabic_folds_alef_variants_and_tatweel():
    # alef-madda/hamza-above/hamza-below/wasla all fold to a bare alef; tatweel vanishes
    assert normalize("أإآاٱ") == normalize("ااااا")
    assert normalize("مـحـمـد") == normalize("محمد")


@pytest.mark.parametrize("verse_key", ["2:2", "7:206"])  # 2:2 has U+06DB; 7:206 has sajdah U+06E9
def test_real_qul_ayah_marks_removed_without_splitting(verse_key):
    data = json.loads(QUL.read_text(encoding="utf-8"))
    text = data[verse_key]["text"]
    assert _has_surviving_mark(text)  # the raw ayah really carries marks (guards the fixture)
    norm = normalize(text)
    assert not _has_surviving_mark(norm)  # nothing mark-like survives
    # the stripped form scores equal AND is not split into extra tokens (the real bug:
    # a mark turned into a space would make the vocalised form gain word tokens)
    assert normalize(text) == normalize(_strip_combining(text))
    assert token_f1(text, _strip_combining(text)) == 1.0
    assert len(normalize(text).split()) == len(normalize(_strip_combining(text)).split())


@pytest.mark.parametrize(
    "mark",
    ["ؗ", "ؘ", "ؙ", "ؚ",  # Arabic small high marks (non-QUL Uthmani)
     "ٖ", "ٗ", "٘", "ٟ",  # subscript alef etc. (U+0656–U+065F)
     "ࣰ", "ࣱ", "ࣲ"],            # Arabic Extended-A open tanwin
)
def test_extended_arabic_marks_folded_not_split(mark):
    # marks OUTSIDE the QUL set (a search-on answer may carry them) must still fold, not
    # split the word mid-token — the generic Mn-in-block rule, verified per codepoint.
    base = "الرحمن"
    vocal = base[:3] + mark + base[3:]
    assert normalize(vocal) == normalize(base)
    assert len(normalize(vocal).split()) == 1


# --- Hebrew ------------------------------------------------------------------


def test_real_vocalized_talmud_line_equals_plain():
    data = json.loads(SHEVUOT_VOCALIZED.read_text(encoding="utf-8"))
    line = None
    for section in data["text"]:
        for raw in section or []:
            clean = re.sub(r"<[^>]+>", "", raw).strip()
            if clean and any(0x0591 <= ord(c) <= 0x05C7 for c in clean):
                line = clean
                break
        if line:
            break
    assert line is not None, "expected a vocalised line in the Shevuot fixture"
    assert normalize(line) == normalize(_strip_combining(line))
    assert token_f1(line, _strip_combining(line)) == 1.0


def test_hebrew_maqaf_becomes_word_boundary():
    # the maqaf (U+05BE) joins words like a hyphen; it must become a SPACE so adjacent
    # words don't concatenate (and niqqud is stripped around it)
    assert normalize("עַל־כֵּן") == "על כן"
    assert normalize("עַל־כֵּן").count(" ") == 1


# --- asymmetric direction (the contrast-preserving property) -----------------


def test_retrieve_quote_scores_equal_regardless_of_vocalisation_direction():
    # Qur'an: expected is vocalised (QUL), a model answers in plain Arabic -> still correct
    ayah_vocal = json.loads(QUL.read_text(encoding="utf-8"))["1:2"]["text"]
    ayah_plain = _strip_combining(ayah_vocal)
    r = score_answer("retrieve_quote", ayah_plain, {"text": ayah_vocal})
    assert r["normalized"] == 1 and r["correct"] == 1 and r["token_f1"] == 1.0
    # Talmud: expected is unvocalised (catalogued Aramaic), a search-on model answers in
    # VOCALISED text -> must NOT be penalised (this is the direction that would otherwise
    # invert the web-search contrast)
    data = json.loads(SHEVUOT_VOCALIZED.read_text(encoding="utf-8"))
    vocal = next(
        re.sub(r"<[^>]+>", "", raw).strip()
        for section in data["text"] for raw in (section or [])
        if re.sub(r"<[^>]+>", "", raw).strip()
        and any(0x0591 <= ord(c) <= 0x05C7 for c in re.sub(r"<[^>]+>", "", raw))
    )
    plain = _strip_combining(vocal)
    r = score_answer("retrieve_quote", vocal, {"text": plain})
    assert r["normalized"] == 1 and r["correct"] == 1 and r["token_f1"] == 1.0


# --- Latin invariance --------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The keeper planted twelve trees.", "the keeper planted twelve trees"),
        ("“Love one’s neighbour!”", "love one s neighbour"),
        ("A  B\n C", "a b c"),
        # pre-existing behaviour: NFKD splits Latin diacritics at the punctuation pass;
        # the Arabic/Hebrew change must NOT alter this (strip_script_marks is a no-op here)
        ("naïve café résumé", "nai ve cafe re sume"),
    ],
)
def test_latin_output_unchanged(text, expected):
    assert normalize(text) == expected


def test_strip_script_marks_is_a_noop_on_latin():
    for s in ["Hello, world!", "café", "coöperate", "John 3:16"]:
        assert strip_script_marks(unicodedata.normalize("NFKD", s)) == unicodedata.normalize("NFKD", s)


# --- Devanagari / Gurmukhi (Spec 37) -------------------------------------------
# Indic vowel signs are spelling, not optional pointing, so they are KEPT in the word — the
# opposite of the Arabic/Hebrew rule above. Before Spec 37 every one became a word split:
# "ਸਤਿ ਨਾਮੁ" -> "ਸਤ ਨ ਮ".

MOOL_MANTAR = "ੴ ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ ਨਿਰਭਉ ਨਿਰਵੈਰੁ ॥"
GITA_1_1 = "धर्मक्षेत्रे कुरुक्षेत्रे समवेता युयुत्सवः । मामकाः पाण्डवाश्चैव किमकुर्वत सञ्जय ॥"


@pytest.mark.parametrize("text", [MOOL_MANTAR, GITA_1_1])
def test_indic_words_stay_whole(text):
    words = [w for w in text.split() if w not in ("।", "॥")]
    assert normalize(text).split() == words


def test_indic_marks_are_kept_not_deleted():
    # Deleting the marks (the Arabic rule) would merge distinct words: naam vs nam.
    assert normalize("ਨਾਮ") != normalize("ਨਮ")
    assert normalize("कर्म") != normalize("करम")


@pytest.mark.parametrize("base,lo,hi", [("क", 0x0900, 0x097F), ("ਕ", 0x0A00, 0x0A7F)])
def test_every_indic_mark_stays_inside_its_word(base, lo, hi):
    marks = [chr(c) for c in range(lo, hi + 1) if unicodedata.category(chr(c)).startswith("M")]
    assert marks
    for m in marks:
        assert len(normalize(base + m + base).split()) == 1, f"U+{ord(m):04X} split the word"


def test_danda_is_a_word_separator():
    assert normalize("ਸਤਿ॥ਨਾਮੁ") == "ਸਤਿ ਨਾਮੁ"
    assert normalize("कर्म।धर्म") == "कर्म धर्म"


def test_indic_digits_fold_to_ascii():
    assert normalize("੧੨੩") == normalize("१२३") == "123"
    assert normalize("Ang ੧੨:੩") == normalize("Ang 12:3")


def test_joiner_after_indic_is_dropped_but_latin_joiner_unchanged():
    assert normalize("र्‍क") == normalize("र्क")
    assert normalize("a‍b") == "a b"  # pre-existing Latin behaviour


def test_indic_containment_respects_word_boundaries():
    # Before Spec 37 "ਕਰਤਾ" normalized to "ਕਰਤ", so the reference "ਕਰਤ" was "contained".
    r = score_answer("retrieve_quote", "ਕਰਤਾ ਪੁਰਖੁ", {"text": "ਕਰਤ"})
    assert r["contains_reference"] == 0


def test_indic_recital_with_verse_counter_is_contained():
    r = score_answer("retrieve_quote", "ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ ॥੧॥", {"text": "ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ"})
    assert r["contains_reference"] == 1 and r["correct"] == 1
    assert token_f1("ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ", "ਸਤਿ ਨਾਮੁ ਕਰਤਾ ਪੁਰਖੁ") == 1.0


@pytest.mark.parametrize("text", [MOOL_MANTAR, GITA_1_1])
def test_scorer_and_failure_kind_tokenize_indic_alike(text):
    from sacredbench.failure_kind import tokens

    assert normalize(text).split() == tokens(text)
