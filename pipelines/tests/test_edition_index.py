"""The shared edition index (Spec 32, Phase 1).

Schema, ordering, single-wording omission, the restricted-license filter (NABRE never
appears even when its payload is present), and byte-stable / hash-sensitive export.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from sacredbench import catalogue as cat
from sacredbench import generate as gen
from sacredbench.cli import app
from sacredbench.edition_index import (
    EditionIndexError,
    atomic_write_texts,
    export_rows,
    index_documents,
    is_verse_citation,
    load_edition_documents,
    lookup_key,
    write_export,
)
from sacredbench.schema import Document, Entry

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]

PROV = (
    "provenance:\n"
    "  retrieved_from: example.org/repo\n"
    "  fetch_method: downloaded\n"
    '  fetch_date: "2026-01-01"\n'
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")
    return path


def _bible(book: str, verses: list[tuple[int, int, str]]) -> str:
    return json.dumps([{"book": book, "chapter": c, "verse": v, "text": t} for c, v, t in verses])


def _doc(work: str, version: str, entries: list[tuple[str, str]], language: str = "en") -> Document:
    return Document(
        tradition=["T"],
        work=work,
        version=version,
        language=language,
        document_type="scripture",
        entries=[Entry(unit_type="verse", citation=c, text=t) for c, t in entries],
    )


# --- is_verse_citation: the non-Bible guard ---------------------------------


def test_is_verse_citation_accepts_bible_rejects_non_bible():
    assert is_verse_citation("Romans 3:23")
    assert is_verse_citation("Song of Solomon 1:1")
    # Arabic surah:ayah (no book token), hadith numbers, Talmud daf:line are not verse citations
    assert not is_verse_citation("2:255")
    assert not is_verse_citation("Sahih al-Bukhari 1")
    assert not is_verse_citation("Berakhot 2a:1")
    # lookup_key is (work, language, citation) for a verse, None otherwise
    assert lookup_key("The Bible", "en", "Romans 3:23") == ("The Bible", "en", "Romans 3:23")
    assert lookup_key("The Qur'an", "ar", "2:255") is None


# --- export rows: schema, ordering, omission --------------------------------


def test_export_rows_schema_ordering_and_single_wording_omitted():
    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "In the beginning God"), ("John 3:16", "For God so loved")]),
        _doc("The Bible", "ASV (1901)", [("Genesis 1:1", "In the beginning God"), ("John 3:16", "For God so loved it")]),
        _doc("The Bible", "WEB", [("Genesis 1:1", "In the beginning, God")]),
        _doc("Book of Mormon", "2013 edition", [("Helaman 5:21", "they were encircled about")]),
    ]
    rows = export_rows(docs)
    # Genesis 1:1 has 3 editions, John 3:16 has 2 -> both are rows; the single-edition
    # Book of Mormon verse is omitted.
    keys = [(r["work"], r["citation"], r["language"]) for r in rows]
    assert keys == [("The Bible", "Genesis 1:1", "en"), ("The Bible", "John 3:16", "en")]  # sorted
    gen_row = rows[0]
    assert [w["version"] for w in gen_row["wordings"]] == ["ASV (1901)", "KJV", "WEB"]  # sorted by version
    assert gen_row["wordings"][1] == {"version": "KJV", "text": "In the beginning God"}
    john = rows[1]
    assert [w["version"] for w in john["wordings"]] == ["ASV (1901)", "KJV"]


def test_index_documents_buckets_by_work_language_citation():
    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "In the beginning God")]),
        _doc("The Bible", "WEB", [("Genesis 1:1", "In the beginning, God")]),
    ]
    idx = index_documents(docs)
    assert len(idx.by_cite[("The Bible", "en", "Genesis 1:1")]) == 2  # keyed on (work, language, citation)
    assert {p.language for p in idx.passages} == {"en"}


def test_in_process_siblings_equal_exported_rows():
    # the two consumers of the frozen schema (card in-process, #21 via the file) group identically —
    # for a NON-Bible work with sibling editions too (its citation isn't Bible-style), so the index
    # is not silently narrower than the export.
    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "a b c d"), ("John 3:16", "e f g h")]),
        _doc("The Bible", "ASV (1901)", [("Genesis 1:1", "a b c d"), ("John 3:16", "i j k l")]),
        _doc("The Bible", "WEB", [("Genesis 1:1", "m n o p")]),  # single-wording John 3:16 omitted
        _doc("The Qur'an", "Ed A", [("2:255", "alif lam mim")], language="ar"),
        _doc("The Qur'an", "Ed B", [("2:255", "qaf nun sad")], language="ar"),  # non-Bible siblings
    ]
    idx = index_documents(docs)
    in_process = {
        (w, lg, c): sorted(p.version for p in ps)
        for (w, lg, c), ps in idx.by_cite.items()
        if len(ps) >= 2
    }
    exported = {
        (r["work"], r["language"], r["citation"]): [wd["version"] for wd in r["wordings"]]
        for r in export_rows(docs)
    }
    assert in_process == exported


# --- determinism + hash sensitivity -----------------------------------------


def test_export_is_byte_stable_and_hash_sensitive(tmp_path):
    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "In the beginning God")]),
        _doc("The Bible", "ASV (1901)", [("Genesis 1:1", "In the beginning God")]),
    ]
    m1 = write_export(docs, docs, [], tmp_path / "a.jsonl")  # indexed == all_docs in this unit fixture
    bytes1 = (tmp_path / "a.jsonl").read_bytes()
    m2 = write_export(docs, docs, [], tmp_path / "b.jsonl")
    bytes2 = (tmp_path / "b.jsonl").read_bytes()
    assert bytes1 == bytes2  # byte-stable on identical input
    assert m1["digest"] == m2["digest"] == hashlib.sha256(bytes1).hexdigest()[:16]
    assert m1["corpus_hash"] == gen.corpus_hash(docs)
    assert m1["row_count"] == 1

    # mutate one wording -> both hashes move
    docs2 = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "In the beginning God")]),
        _doc("The Bible", "ASV (1901)", [("Genesis 1:1", "In the beginning, God.")]),
    ]
    m3 = write_export(docs2, docs2, [], tmp_path / "c.jsonl")
    assert m3["digest"] != m1["digest"]
    assert m3["corpus_hash"] != m1["corpus_hash"]


def test_corpus_hash_is_over_the_full_nonrestricted_set_not_the_indexed_subset(tmp_path):
    # the export's corpus_hash is generate's hash over ALL non-restricted docs (translations
    # included), so adding a translation (not indexed) still moves corpus_hash — that is what makes
    # it comparable to a run manifest's corpus_hash.
    indexed = [_doc("The Bible", "KJV", [("Genesis 1:1", "a b c d")])]
    translation = _doc("The Bible", "Translation", [("Genesis 1:1", "w x y z")], language="xx")
    m_no = write_export(indexed, indexed, [], tmp_path / "a.jsonl")
    m_yes = write_export(indexed, indexed + [translation], [], tmp_path / "b.jsonl")
    assert m_no["corpus_hash"] != m_yes["corpus_hash"]  # full-set hash moved
    assert m_no["digest"] == m_yes["digest"]  # the rows (from indexed only) did not


def test_manifest_shape(tmp_path):
    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "a b c d e")]),
        _doc("The Bible", "WEB", [("Genesis 1:1", "a b c d e")]),
    ]
    m = write_export(docs, docs, ["NABRE", "TLG"], tmp_path / "idx.jsonl")
    assert set(m) == {"corpus_hash", "row_count", "digest", "excluded_restricted"}
    assert m["excluded_restricted"] == ["NABRE", "TLG"]
    manifest_on_disk = json.loads((tmp_path / "idx.jsonl.manifest.json").read_text())
    assert manifest_on_disk == m


def test_write_export_atomic_rollback_on_second_swap_failure(tmp_path, monkeypatch):
    from sacredbench import edition_index as ei_mod

    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "a b c d")]),
        _doc("The Bible", "WEB", [("Genesis 1:1", "e f g h")]),
    ]
    out = tmp_path / "idx.jsonl"
    manifest_path = tmp_path / "idx.jsonl.manifest.json"
    out.write_text("OLD-INDEX")
    manifest_path.write_text("OLD-MANIFEST")
    real_replace = ei_mod.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # fail swapping the manifest
            raise OSError("boom")
        return real_replace(src, dst)

    monkeypatch.setattr(ei_mod.os, "replace", flaky)
    with pytest.raises(OSError):
        write_export(docs, docs, [], out)
    # neither file is left half-updated (the index swap was rolled back)
    assert out.read_text() == "OLD-INDEX"
    assert manifest_path.read_text() == "OLD-MANIFEST"
    assert not list(tmp_path.glob("idx.jsonl*.tmp")) and not list(tmp_path.glob("idx.jsonl*.bak.*"))


# --- the restricted-license filter (a present payload is still excluded) -----


def _fixture_raw_with_present_restricted(root: Path) -> Path:
    """A raw tree with two public Bible editions AND a restricted edition whose payload
    is PRESENT locally, all sharing a citation."""
    raw = root / "texts" / "raw"
    _write(
        raw / "Protestant Christian" / "source.yaml",
        PROV
        + "targets:\n"
        "  - payload: kjv.json\n"
        "    converter: bible_flat\n"
        "    work: The Bible\n"
        "    version: KJV\n"
        "    language: en\n"
        "    document_type: scripture\n"
        "    tradition: [Protestant Christian]\n"
        "    license: public-domain\n"
        "    requested_as: [the KJV]\n"
        "    canonical_language: en\n"
        "  - payload: asv.json\n"
        "    converter: bible_flat\n"
        "    work: The Bible\n"
        "    version: ASV (1901)\n"
        "    language: en\n"
        "    document_type: scripture\n"
        "    tradition: [Protestant Christian]\n"
        "    license: public-domain\n"
        "    requested_as: [the ASV]\n"
        "    canonical_language: en\n",
    )
    _write(raw / "Protestant Christian" / "kjv.json", _bible("Genesis", [(1, 1, "In the beginning God")]))
    _write(raw / "Protestant Christian" / "asv.json", _bible("Genesis", [(1, 1, "In the beginning God")]))
    # A restricted fourth edition of the SAME work/citation, payload PRESENT.
    _write(
        raw / "Restricted" / "source.yaml",
        PROV
        + "targets:\n"
        "  - payload: nabre.json\n"
        "    converter: bible_flat\n"
        "    work: The Bible\n"
        "    version: NABRE\n"
        "    language: en\n"
        "    document_type: scripture\n"
        "    tradition: [Roman Catholic]\n"
        "    license: restricted\n"
        "    requested_as: [the NABRE]\n"
        "    canonical_language: en\n",
    )
    _write(raw / "Restricted" / "nabre.json", _bible("Genesis", [(1, 1, "SECRET restricted NABRE wording")]))
    # A non-canonical-language edition (English rendering of a Hebrew-canonical work):
    # language en != canonical_language he, so the pool rule must keep it OUT of the index.
    _write(
        raw / "Translation" / "source.yaml",
        PROV
        + "targets:\n"
        "  - payload: talmud_en.json\n"
        "    converter: bible_flat\n"
        "    work: Talmud Bavli\n"
        "    version: Davidson English\n"
        "    language: en\n"
        "    document_type: scripture\n"
        "    tradition: [Jewish]\n"
        "    license: public-domain\n"
        "    requested_as: [the Talmud]\n"
        "    canonical_language: he\n",
    )
    _write(raw / "Translation" / "talmud_en.json", _bible("Genesis", [(1, 1, "an english rendering")]))
    return raw


def test_cli_edition_index_writes_both_files(tmp_path):
    raw = _fixture_raw_with_present_restricted(tmp_path)
    out = tmp_path / "idx.jsonl"
    result = runner.invoke(app, ["edition-index", "--out", str(out), "--raw-root", str(raw)])
    assert result.exit_code == 0, result.output
    assert out.exists() and (tmp_path / "idx.jsonl.manifest.json").exists()
    manifest = json.loads((tmp_path / "idx.jsonl.manifest.json").read_text())
    assert manifest["excluded_restricted"] == ["NABRE"]
    assert "NABRE" in result.output  # the echo surfaces the exclusions
    # the restricted + non-canonical editions never reach the exported file
    body = out.read_text()
    assert "SECRET" not in body and "english rendering" not in body


def test_restricted_edition_never_indexed_even_when_payload_present(tmp_path):
    raw = _fixture_raw_with_present_restricted(tmp_path)
    indexed, all_docs, excluded = load_edition_documents(raw)
    versions = {d.version for d in indexed}
    assert "NABRE" not in versions  # license filter, not payload-absence, excludes it
    assert excluded == ["NABRE"]  # named in the manifest exclusions
    # the non-canonical-language English Talmud edition is kept out of the INDEX by the pool rule,
    # but is in all_docs (it is a non-restricted converted doc that generate would hash)
    assert "Davidson English" not in versions
    assert "Davidson English" in {d.version for d in all_docs}
    rows = export_rows(indexed)
    serialized = json.dumps(rows, ensure_ascii=False)
    assert "NABRE" not in serialized and "SECRET" not in serialized
    assert "english rendering" not in serialized
    # the two public editions still form a sibling row
    assert rows and [w["version"] for w in rows[0]["wordings"]] == ["ASV (1901)", "KJV"]


def test_conflicting_duplicate_wording_fails_fast():
    docs = [
        _doc("The Bible", "KJV", [("Genesis 1:1", "wording one")]),
        _doc("The Bible", "KJV", [("Genesis 1:1", "a DIFFERENT wording")]),  # same version, conflicts
    ]
    with pytest.raises(EditionIndexError):
        export_rows(docs)


# --- against the real committed catalogue -----------------------------------


def test_real_catalogue_indexes_bibles_and_excludes_restricted():
    raw = REPO_ROOT / "texts" / "raw"
    if not raw.exists():
        pytest.skip("no raw texts tree")
    indexed, _all, excluded = load_edition_documents(raw)
    versions = {(d.work, d.version) for d in indexed}
    # the three public English Bibles are indexed
    assert ("The Bible", "KJV") in versions
    assert ("The Bible", "ASV (1901)") in versions
    assert ("The Bible", "WEB") in versions
    # NABRE (restricted) is not
    assert ("The Bible", "NABRE") not in versions
    assert excluded == ["NABRE", "TLG"]  # both restricted same-canonical-language editions, pinned
    # the canonical-language guard keeps non-canonical editions OUT of the index:
    # the English Talmud (en / canonical he) and the Papal Encyclicals (en / canonical la)
    assert ("Talmud Bavli", "William Davidson Edition - English") not in versions
    assert all(d.work != "Papal Encyclicals" for d in indexed)


def test_real_catalogue_export_corpus_hash_equals_run_manifest():
    # BLOCKING 1: the export manifest's corpus_hash must equal the run manifest's, so #21's consumer
    # (fail unless index corpus_hash == run corpus_hash) passes when the corpus is the same.
    raw = REPO_ROOT / "texts" / "raw"
    run_manifest = REPO_ROOT / "runs" / "original-2026-10-21" / "questions.jsonl.manifest.json"
    if not raw.exists() or not run_manifest.exists():
        pytest.skip("no raw tree / committed run")
    indexed, all_docs, excluded = load_edition_documents(raw)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in export_rows(indexed))
    from sacredbench import catalogue as cat
    from sacredbench.edition_index import build_manifest
    from sacredbench.facct import post_run_filter

    # the run's corpus is the catalogue as of the run: drop texts added after it (Spec 37)
    run = json.loads(run_manifest.read_text())
    targets = cat.all_targets(cat.discover_catalogue(raw))
    later = {t.text_key for t in targets} - {t.text_key for t in post_run_filter(targets, run)}
    all_docs = [d for d in all_docs if (d.work, d.version, d.language) not in later]
    manifest = build_manifest(all_docs, body, excluded)
    run_corpus_hash = run["corpus_hash"]
    assert manifest["corpus_hash"] == run_corpus_hash
