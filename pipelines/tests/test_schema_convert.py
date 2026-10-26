import json
from pathlib import Path

import pytest

from sacredbench import catalogue as cat
from sacredbench.convert import (
    ConvertError,
    convert_bible_flat,
    convert_encyclicals,
    convert_hadith_sunnah,
    convert_lds_nested,
    convert_nabre,
    convert_quran_qul,
    convert_sefaria_talmud,
    convert_shabados_sggs,
    convert_target,
)
from sacredbench.schema import SchemaError, load_document, parse_document, write_document
from tests.conftest import ENCYCLICAL_SHAPE, NABRE_SHAPE, make_doc

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "texts" / "raw"


def _target(**over) -> cat.Target:
    base = dict(
        source_id="X", payload="x.json", converter="nabre", work="The Bible",
        version="TestV", language="en", document_type="scripture",
        tradition=("testfaith",), license="public-domain",
        provenance=cat.Provenance("a", "b", "c"),
        requested_as=("The Bible",), canonical_language="en",
    )
    base.update(over)
    base["tradition"] = tuple(base["tradition"])
    return cat.Target(**base)


def _real_target(source_id: str, **match) -> cat.Target:
    """Pick one real catalogue target by source_id + matching fields."""
    sources = cat.discover_catalogue(RAW)
    for t in cat.all_targets(sources):
        if t.source_id == source_id and all(getattr(t, k) == v for k, v in match.items()):
            return t
    raise AssertionError(f"no catalogue target {source_id} {match}")


# --- schema (unchanged behaviour) --------------------------------------------


def test_document_roundtrip(tmp_path):
    doc = make_doc(n=3)
    path = tmp_path / "doc.json"
    write_document(doc, path)
    assert load_document(path) == doc


def test_parse_normalises_string_tradition():
    data = make_doc(n=2).to_json_dict()
    data["source"]["tradition"] = "solo"
    assert parse_document(data).tradition == ["solo"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("source"),
        lambda d: d["source"].pop("version"),
        lambda d: d.update(entries=[]),
        lambda d: d["entries"][0].pop("citation"),
        lambda d: d["entries"][0].update(text="  "),
        # malformed source metadata must be rejected, not str()-coerced
        lambda d: d["source"].update(work=None),
        lambda d: d["source"].update(language=[]),
        lambda d: d["source"].update(document_type="  "),
        lambda d: d["source"].update(version=3),
        lambda d: d["source"].update(tradition=["ok", "  "]),
        lambda d: d["source"].update(tradition=[]),
    ],
)
def test_parse_fails_fast(mutate):
    data = make_doc(n=2).to_json_dict()
    mutate(data)
    with pytest.raises(SchemaError):
        parse_document(data)


# --- nabre / encyclicals (adapted to the (paths, target) contract) -----------


def test_convert_nabre(tmp_path):
    # the real shape: one file, a top-level LIST of book objects
    p = tmp_path / "nabre.json"
    p.write_text(json.dumps(NABRE_SHAPE))
    [doc] = convert_nabre([p], _target(version="TestV"))
    assert [e.citation for e in doc.entries] == [
        "1 Orchards 1:1", "1 Orchards 1:2", "1 Orchards 2:1", "2 Orchards 1:1",
    ]
    assert doc.entries[0].text.startswith("Preamble.")  # heading kept verbatim, not stripped
    assert doc.document_type == "scripture" and doc.version == "TestV"


def test_convert_nabre_rejects_wrong_shape(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"paragraphs": []}))
    with pytest.raises(ConvertError):
        convert_nabre([p], _target())


def test_convert_encyclicals(tmp_path):
    p = tmp_path / "de-testibus.json"
    p.write_text(json.dumps(ENCYCLICAL_SHAPE))
    [doc] = convert_encyclicals([p], _target(document_type="encyclical"))
    # null paragraph -> non-canonical "unnumbered"; declared number preserved; blank dropped
    assert [e.citation for e in doc.entries] == ["De Testibus, unnumbered para. 1", "De Testibus, para. 2"]
    assert doc.work == "De Testibus"
    assert doc.document_type == "encyclical"
    assert doc.source_url == "https://example.org/de-testibus"


# --- bible_flat (real committed data + malformed) ----------------------------


@pytest.mark.parametrize("version, count", [("KJV", 31102), ("ASV (1901)", 31102), ("WEB", 31098)])
def test_convert_bible_flat_real_three_versions(version, count):
    """All three real Protestant Bibles convert to validate-passing docs of 'The Bible'."""
    t = _real_target("Protestant Christian", version=version)
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert doc.work == "The Bible" and doc.version == version and doc.document_type == "scripture"
    assert len(doc.entries) == count
    assert doc.entries[0].citation == "Genesis 1:1" and doc.entries[0].unit_type == "verse"
    assert doc.entries[-1].citation == "Revelation 22:21"
    parse_document(doc.to_json_dict())  # validate-passing


def test_convert_bible_flat_real_kjv_exact_text():
    t = _real_target("Protestant Christian", version="KJV")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert doc.entries[0].text == "In the beginning God created the heaven and the earth."


def test_convert_bible_flat_rejects_wrong_shape(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ConvertError):
        convert_bible_flat([p], _target(converter="bible_flat"))


def test_convert_encyclicals_real():
    """Phase 2 requires confirming encyclicals against the committed source."""
    t = _real_target("Roman Catholic", converter="encyclicals")
    docs = convert_target(t.payload_paths(RAW), t)
    assert len(docs) == 201
    assert sum(len(d.entries) for d in docs) == 10925  # lossless: every non-empty paragraph kept
    for d in docs:
        assert all(e.unit_type == "paragraph" for e in d.entries)
        cites = [e.citation for e in d.entries]
        assert len(cites) == len(set(cites))  # unique within each document
        parse_document(d.to_json_dict())  # validate-passing


def test_convert_encyclicals_citations_bind_to_declared_numbers():
    """Body paragraphs are cited by their DECLARED number (not position); front
    matter is marked non-canonical; conversion is lossless (no silent truncation);
    genuine duplicate declared numbers are disambiguated, not dropped."""
    t = _real_target("Roman Catholic", converter="encyclicals")
    docs = convert_target(t.payload_paths(RAW), t)
    by_work = {d.work: {e.citation: e.text for e in d.entries} for d in docs}

    # Ad Petri Cathedram: 2 null front-matter paragraphs precede declared #2, so a
    # positional citation would mislabel it. The declared-number binding is correct:
    apc = by_work["Ad Petri Cathedram"]
    assert apc["Ad Petri Cathedram, para. 2"].startswith("For these reflections of Ours")
    assert apc["Ad Petri Cathedram, unnumbered para. 1"].startswith("To the Venerable Brethren")

    # No mid-body truncation: these tails were dropped by the earlier latched
    # footnote heuristic (in-body numbering anomalies) and must be retained.
    assert "Mediator Dei, para. 210" in by_work["Mediator Dei"]
    assert "Ecclesiam Suam, para. 119" in by_work["Ecclesiam Suam"]
    # Genuine in-body duplicate declared number is kept (disambiguated), not dropped.
    assert "Mediator Dei, para. 100 (dup 2)" in by_work["Mediator Dei"]


# --- lds_nested (real committed data: 3-level, 2-level, metadata skip) --------


def test_convert_lds_nested_three_level_book_of_mormon():
    t = _real_target("The Church of Jesus Christ of Latter-Day Saints", work="Book of Mormon")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert len(doc.entries) == 6604  # canonical verse count; editorial chapter headings excluded
    assert doc.entries[0].citation == "1 Nephi 1:1"  # book chapter:verse
    assert doc.entries[-1].citation == "Moroni 10:34"
    # chapter-level 'heading' editorial summaries are NOT emitted as verses
    assert not any(":heading" in e.citation or e.citation.endswith("heading") for e in doc.entries)


def test_convert_lds_nested_two_level_doctrine_and_covenants():
    t = _real_target("The Church of Jesus Christ of Latter-Day Saints", work="Doctrine and Covenants")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert len(doc.entries) == 3654
    # 2-level citation is self-identifying (includes the work), not a bare "1:1"
    assert doc.entries[0].citation == "Doctrine and Covenants 1:1"


def test_convert_lds_nested_skips_metadata_keys():
    t = _real_target("The Church of Jesus Christ of Latter-Day Saints", work="Pearl of Great Price")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert len(doc.entries) == 635
    # last_modified / version metadata keys never become citations
    cites = {e.citation for e in doc.entries}
    assert not any(c.startswith(("last_modified", "version")) for c in cites)
    assert doc.entries[0].citation == "Moses 1:1"


def test_convert_lds_nested_rejects_mixed_shape(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"Book": {"1": "verse-string", "2": {"1": "chapter-object"}}}))
    with pytest.raises(ConvertError):
        convert_lds_nested([p], _target(converter="lds_nested"))


# --- convert_target dispatch -------------------------------------------------


def test_convert_target_unregistered_converter_fails(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    # 'tlg' is named by the Greek Orthodox catalogue entry but ships no converter
    with pytest.raises(ConvertError) as e:
        convert_target([p], _target(converter="tlg"))
    assert "not registered" in str(e.value)


def test_convert_target_empty_paths_fails():
    with pytest.raises(ConvertError) as e:
        convert_target([], _target(converter="bible_flat"))
    assert "no payload files" in str(e.value)


# --- fail-fast / post-conditions ---------------------------------------------


def test_duplicate_citations_rejected(tmp_path):
    # two flat records that would yield the same citation
    p = tmp_path / "dup.json"
    p.write_text(json.dumps([
        {"book": "Genesis", "chapter": 1, "verse": 1, "text": "a"},
        {"book": "Genesis", "chapter": 1, "verse": 1, "text": "b"},
    ]))
    with pytest.raises(ConvertError) as e:
        convert_bible_flat([p], _target(converter="bible_flat"))
    assert "duplicate citation" in str(e.value)


@pytest.mark.parametrize(
    "fn_name, payload",
    [
        ("encyclicals", ["a list, not an object"]),
        ("nabre", ["a list, not an object"]),
        ("lds_nested", "a string, not an object"),
    ],
)
def test_converters_fail_fast_naming_file_on_bad_top_level(tmp_path, fn_name, payload):
    """A wrong top-level JSON type raises ConvertError naming the file, not AttributeError."""
    fn = {"encyclicals": convert_encyclicals, "nabre": convert_nabre, "lds_nested": convert_lds_nested}[fn_name]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(ConvertError) as e:
        fn([p], _target(converter=fn_name))
    assert "bad.json" in str(e.value)


def test_lds_nested_rejects_unexpected_scalar_book(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"Mystery": "scalar instead of a book object"}))
    with pytest.raises(ConvertError) as e:
        convert_lds_nested([p], _target(converter="lds_nested"))
    assert "non-object top-level key" in str(e.value)


# --- Phase 3: Quran / hadith / Talmud (real committed data) ------------------


def test_convert_quran_qul_real():
    t = _real_target("Sunni Islam", converter="quran_qul")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert len(doc.entries) == 6236
    # canonical bare surah:ayah citation (per the plan contract)
    assert doc.entries[0].citation == "1:1" and doc.entries[0].unit_type == "ayah"
    assert doc.entries[-1].citation == "114:6"
    parse_document(doc.to_json_dict())


def test_convert_hadith_sunnah_real_bukhari():
    t = _real_target("Sunni Islam", work="Sahih al-Bukhari")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert len(doc.entries) == 7277
    assert doc.entries[0].citation == "Sahih al-Bukhari 1" and doc.entries[0].unit_type == "hadith"
    parse_document(doc.to_json_dict())


def test_convert_sefaria_talmud_real_en():
    t = _real_target("Judaism", language="en")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert doc.document_type == "talmud"
    assert doc.version == "William Davidson Edition - English"
    assert doc.entries[0].unit_type == "line"
    assert doc.entries[0].citation == "Arakhin 2a:1"  # tractates start at daf 2a
    assert all("<" not in e.text and ">" not in e.text for e in doc.entries)  # HTML stripped
    parse_document(doc.to_json_dict())


def test_convert_sefaria_talmud_real_he_excludes_vocalized():
    """The he target's tightened glob excludes the Vocalized Aramaic Shevuot variant,
    so conversion succeeds (no conflicting-duplicate error) and markup is stripped."""
    t = _real_target("Judaism", language="he")
    [doc] = convert_target(t.payload_paths(RAW), t)
    assert doc.entries[0].citation == "Arakhin 2a:1"
    assert all("<" not in e.text and ">" not in e.text for e in doc.entries)


def test_talmud_en_he_are_distinct_versions():
    en = _real_target("Judaism", language="en")
    he = _real_target("Judaism", language="he")
    assert en.version != he.version  # en/he are separate versions (plan contract)
    assert en.version.endswith("English") and he.version.endswith("Aramaic")


# --- Phase 3: Talmud daf offset / markup / duplicate handling (synthetic) -----


def _talmud(title: str, sections: list) -> dict:
    return {"title": title, "text": sections, "sectionNames": ["Daf", "Line"]}


def test_talmud_daf_offset_and_markup_strip(tmp_path):
    # sections 0,1 empty (start at 2a); section 2 -> 2a, section 3 -> 2b, section 4 -> 3a
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_talmud("TestMasechet", [
        [], [],
        ["<strong>MISHNA:</strong> <b>first</b> line", "second line"],
        ["third &amp; line"],
        ["fourth line"],
    ])))
    [doc] = convert_sefaria_talmud([p], _target(converter="sefaria_talmud", work="Talmud Bavli",
                                                document_type="talmud", language="en"))
    cites = [e.citation for e in doc.entries]
    assert cites == ["TestMasechet 2a:1", "TestMasechet 2a:2", "TestMasechet 2b:1", "TestMasechet 3a:1"]
    assert doc.entries[0].text == "MISHNA: first line"  # tags stripped, whitespace collapsed
    assert doc.entries[2].text == "third & line"  # entity unescaped


def test_talmud_skipped_empty_line_does_not_renumber(tmp_path):
    # a markup-only (empty-after-strip) first line must NOT shift the next line's
    # number — Sefaria refs are positional (load-bearing at 207 real locations).
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_talmud("T", [[], [], ["<b></b>", "real line"]])))
    [doc] = convert_sefaria_talmud([p], _target(converter="sefaria_talmud", document_type="talmud",
                                                language="en"))
    assert [e.citation for e in doc.entries] == ["T 2a:2"]  # line 1 dropped, line 2 keeps its number


def test_talmud_language_mismatch_fails(tmp_path):
    # a file whose own language disagrees with the target is refused (guards a
    # widened glob mislabelling a tractate)
    p = tmp_path / "t.json"
    data = _talmud("T", [[], [], ["line"]])
    data["language"] = "he"
    p.write_text(json.dumps(data))
    with pytest.raises(ConvertError) as e:
        convert_sefaria_talmud([p], _target(converter="sefaria_talmud", document_type="talmud",
                                             language="en"))
    assert "language" in str(e.value)


def test_talmud_identical_duplicate_tractate_deduped(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    payload = _talmud("Dup", [[], [], ["only line"]])
    a.write_text(json.dumps(payload))
    b.write_text(json.dumps(payload))
    [doc] = convert_sefaria_talmud([a, b], _target(converter="sefaria_talmud", document_type="talmud"))
    assert [e.citation for e in doc.entries] == ["Dup 2a:1"]  # redundant copy skipped


def test_talmud_conflicting_duplicate_tractate_fails(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_talmud("Dup", [[], [], ["line A"]])))
    b.write_text(json.dumps(_talmud("Dup", [[], [], ["line B DIFFERENT"]])))
    with pytest.raises(ConvertError) as e:
        convert_sefaria_talmud([a, b], _target(converter="sefaria_talmud", document_type="talmud"))
    assert "conflicting duplicate tractate" in str(e.value)


def test_hadith_malformed_idinbook_fails(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"hadiths": [{"idInBook": {"not": "scalar"}, "arabic": "x"}]}))
    with pytest.raises(ConvertError) as e:
        convert_hadith_sunnah([p], _target(converter="hadith_sunnah"))
    assert "idInBook" in str(e.value)


@pytest.mark.parametrize(
    "fn, payload, converter",
    [
        (convert_quran_qul, ["not a dict"], "quran_qul"),
        (convert_hadith_sunnah, {"no": "hadiths list"}, "hadith_sunnah"),
        (convert_sefaria_talmud, {"title": "X", "text": "not a list"}, "sefaria_talmud"),
    ],
)
def test_phase3_converters_fail_fast(tmp_path, fn, payload, converter):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(ConvertError) as e:
        fn([p], _target(converter=converter))
    assert "bad.json" in str(e.value)


# --- Sri Guru Granth Sahib (shabados_sggs, Spec 37) -----------------------------


def _sggs_payload(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "sggs.json"
    p.write_text(json.dumps({"upstream": {}, "sections": [], "lines": lines}, ensure_ascii=False), encoding="utf-8")
    return p


def _sggs(id, ang, line, data):
    return {"id": id, "section": "S", "line_group": "G", "ang": ang, "line": line, "data": data}


def test_shabados_sggs_cites_ang_and_position_not_physical_line(tmp_path):
    p = _sggs_payload(tmp_path, [
        _sggs("A", 1, 4, "ਆਦਿ ਸਚੁ; ਜੁਗਾਦਿ ਸਚੁ ॥"),
        _sggs("B", 1, 4, "ਹੈ ਭੀ ਸਚੁ; ਨਾਨਕ. ਹੋਸੀ ਭੀ ਸਚੁ ॥੧॥"),  # same physical line
        _sggs("C", 2, 1, "ਸੋਚੈ. ਸੋਚਿ ਨ ਹੋਵਈ; ਜੇ ਸੋਚੀ ਲਖ ਵਾਰ ॥"),
    ])
    [doc] = convert_shabados_sggs([p], _target(converter="shabados_sggs", language="pa"))
    assert [(e.unit_type, e.citation, e.text) for e in doc.entries] == [
        ("pankti", "Ang 1:1", "ਆਦਿ ਸਚੁ ਜੁਗਾਦਿ ਸਚੁ"),
        ("pankti", "Ang 1:2", "ਹੈ ਭੀ ਸਚੁ ਨਾਨਕ ਹੋਸੀ ਭੀ ਸਚੁ"),
        ("pankti", "Ang 2:1", "ਸੋਚੈ ਸੋਚਿ ਨ ਹੋਵਈ ਜੇ ਸੋਚੀ ਲਖ ਵਾਰ"),
    ]


@pytest.mark.parametrize("raw,clean", [
    ("ਸਗਲਂ‍ੀ ਸਉਦਂ‍ੀ; ਤੋਟਾ ਆਵੈ ॥", "ਸਗਲੀਂ ਸਉਦੀਂ ਤੋਟਾ ਆਵੈ"),  # bindi/ZWJ order
    ("ਜੇ ਭੁਲੀ ਜੇ ਚੁਕੀ ਸਾਈਂ︀; ਭੀ ਤਹਿੰਜੀ ਕਾਢੀਆ ॥", "ਜੇ ਭੁਲੀ ਜੇ ਚੁਕੀ ਸਾਈਂ ਭੀ ਤਹਿੰਜੀ ਕਾਢੀਆ"),  # U+FE00
    ("ਰਾਗੁ ਗਉੜੀ₁ ਪੂਰਬੀ ਮਹਲਾ ੫ ॥", "ਰਾਗੁ ਗਉੜੀ ਪੂਰਬੀ ਮਹਲਾ ੫"),  # subscript tag; heading digit kept
    ("ਤੁਮੑਰੀ ਕ੍ਰਿਪਾ ਤੇ; ਤ੍ਰਿਪਤਿ ਅਘਾਈਂ︀ ॥੧॥ ਰਹਾਉ ॥", "ਤੁਮੑਰੀ ਕ੍ਰਿਪਾ ਤੇ ਤ੍ਰਿਪਤਿ ਅਘਾਈਂ ਰਹਾਉ"),  # ਰਹਾਉ kept
    ("ਗਤਿ ਹੋਵੈ; ਸੰਤਹ ਲਗਿ ਪਾਈਂ︀ ॥੪॥੯॥੬੦॥", "ਗਤਿ ਹੋਵੈ ਸੰਤਹ ਲਗਿ ਪਾਈਂ"),  # counter chain
    ("॥ ਜਪੁ ॥", "ਜਪੁ"),
])
def test_shabados_sggs_removes_apparatus_only(tmp_path, raw, clean):
    [doc] = convert_shabados_sggs([_sggs_payload(tmp_path, [_sggs("A", 1, 1, raw)])], _target(converter="shabados_sggs"))
    assert doc.entries[0].text == clean


def test_shabados_sggs_fails_on_a_decreasing_ang(tmp_path):
    p = _sggs_payload(tmp_path, [_sggs("A", 2, 1, "ਸਚੁ ॥"), _sggs("B", 1, 1, "ਸਚੁ ॥")])
    with pytest.raises(ConvertError, match="Ang 1 after Ang 2"):
        convert_shabados_sggs([p], _target(converter="shabados_sggs"))


def test_shabados_sggs_fails_on_a_stale_erratum(tmp_path):
    p = _sggs_payload(tmp_path, [_sggs("JJSV", 1336, 19, "ਸਚੁ ॥")])  # upstream already fixed
    with pytest.raises(ConvertError, match="stale"):
        convert_shabados_sggs([p], _target(converter="shabados_sggs"))


def _gurmukhi_letters(s: str) -> str:
    """Letters and marks only — the words' substance, independent of the converter."""
    import unicodedata
    return "".join(c for c in s if "਀" <= c <= "੿" and unicodedata.category(c)[0] in "LM")


def test_real_sggs_converts_every_line_and_removes_only_apparatus():
    """The whole Granth: 60,555 panktis on Angs 1-1430, unique citations, the two Ang errata
    applied, and for EVERY line the Gurmukhi letters/marks and the word count are unchanged
    (the only reordering is the declared bindi/ZWJ fix) — no word added, deleted, or altered."""
    import re

    t = _real_target("Sikhism")
    [doc] = convert_target(t.payload_paths(RAW), t)
    raw = json.loads(t.payload_paths(RAW)[0].read_text("utf-8"))["lines"]
    assert len(doc.entries) == len(raw) == 60555
    assert {e.citation.split(":")[0] for e in doc.entries} == {f"Ang {n}" for n in range(1, 1431)}
    by_citation = {e.citation: e.text for e in doc.entries}
    assert by_citation["Ang 1336:31"].startswith("ਹਰਿ ਹਰਿ ਆਪੁ ਧਰਿਓ")
    assert by_citation["Ang 1378:1"].startswith("ਬੰਨੑਿ ਉਠਾਈ ਪੋਟਲੀ")
    for r, e in zip(raw, doc.entries):
        fixed = r["data"].replace("ਂ‍ੀ", "ੀਂ")
        assert _gurmukhi_letters(fixed) == _gurmukhi_letters(e.text), r["id"]
        words = [w for w in fixed.split() if _gurmukhi_letters(w)]
        assert len(words) == len([w for w in e.text.split() if _gurmukhi_letters(w)]), r["id"]
        assert not re.search(r"[;.,॥।₀-₉‍︀]", e.text), r["id"]
