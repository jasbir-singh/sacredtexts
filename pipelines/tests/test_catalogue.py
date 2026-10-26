"""Tests for the source catalogue: schema/loader (incl. provenance), discovery,
license gating, path->license recovery, the CLI gate (convert/generate), and a
git check-ignore guard for the reachability rules."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from sacredbench import catalogue as cat
from sacredbench.cli import app

REPO_ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()

# Column-0 YAML fragments so concatenation stays valid (no dedent games).
PROV = (
    'provenance:\n'
    '  retrieved_from: example.org/repo\n'
    '  fetch_method: downloaded\n'
    '  fetch_date: "2026-01-01"\n'
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")
    return path


def _fixture_tree(root: Path) -> Path:
    """A miniature texts/raw with one open target and one restricted target."""
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
        "    license_detail: public domain\n"
        "    requested_as: [King James Version, KJV]\n"
        "    canonical_language: en\n",
    )
    _write(
        raw / "Protestant Christian" / "kjv.json",
        json.dumps([
            {"book": "Genesis", "chapter": 1, "verse": 1, "text": "In the beginning."},
            {"book": "Genesis", "chapter": 1, "verse": 2, "text": "And the earth was without form."},
        ]),
    )
    _write(
        raw / "Roman Catholic" / "source.yaml",
        PROV
        + "targets:\n"
        "  - payload: encyclicals/en/*.json\n"
        "    converter: encyclicals\n"
        "    work: Papal Encyclicals\n"
        "    version: Vatican English\n"
        "    language: en\n"
        "    document_type: encyclical\n"
        "    tradition: [Roman Catholic]\n"
        "    license: open\n"
        "    requested_as: [papal encyclicals, the encyclicals]\n"
        "    canonical_language: la\n"
        "  - payload: nabre.json\n"
        "    converter: nabre\n"
        "    work: The Bible\n"
        "    version: NABRE\n"
        "    language: en\n"
        "    document_type: scripture\n"
        "    tradition: [Roman Catholic]\n"
        "    license: restricted\n"
        "    requested_as: [NABRE, New American Bible]\n"
        "    canonical_language: en\n",
    )
    _write(raw / "Roman Catholic" / "encyclicals" / "en" / "a.json", "{}")
    _write(raw / "Roman Catholic" / "nabre.json", "{}")
    return raw


def _std_doc(path: Path, work: str = "W") -> Path:
    """Write a minimal schema-valid standardized document."""
    _write(
        path,
        json.dumps(
            {
                "source": {
                    "tradition": ["T"],
                    "work": work,
                    "version": "V",
                    "language": "en",
                    "document_type": "scripture",
                },
                "entries": [{"unit_type": "verse", "citation": f"{work} 1:1", "text": "hello"}],
            }
        ),
    )
    return path


# --- loader / schema ---------------------------------------------------------


def test_load_valid_source(tmp_path):
    raw = _fixture_tree(tmp_path)
    src = cat.load_source(raw / "Roman Catholic" / "source.yaml", raw)
    assert src.source_id == "Roman Catholic"
    assert [t.license for t in src.targets] == ["open", "restricted"]
    assert src.targets[0].tradition == ("Roman Catholic",)
    assert src.provenance.fetch_date == "2026-01-01"
    assert src.targets[0].provenance.retrieved_from == "example.org/repo"


def test_bare_string_tradition_normalized(tmp_path):
    y = _write(
        tmp_path / "texts" / "raw" / "X" / "source.yaml",
        PROV + _TARGET.replace("tradition: [X]", "tradition: X"),
    )
    src = cat.load_source(y, tmp_path / "texts" / "raw")
    assert src.targets[0].tradition == ("X",)


def test_per_target_provenance_override(tmp_path):
    y = _write(
        tmp_path / "texts" / "raw" / "X" / "source.yaml",
        PROV
        + _TARGET
        + "\n    provenance:\n"
        "      retrieved_from: other.example/held-back\n"
        "      fetch_method: licensed\n"
        "      fetch_date: unknown\n",
    )
    src = cat.load_source(y, tmp_path / "texts" / "raw")
    assert src.targets[0].provenance.retrieved_from == "other.example/held-back"
    assert src.provenance.retrieved_from == "example.org/repo"  # source default unchanged


_TARGET = (
    "targets:\n  - payload: a.json\n    converter: c\n    work: W\n    version: V\n"
    "    language: en\n    document_type: scripture\n    tradition: [X]\n    license: open\n"
    "    requested_as: [Wname, W]\n    canonical_language: en"
)


@pytest.mark.parametrize(
    "body, needle",
    [
        (PROV + "targets: []", "non-empty list"),
        (PROV + "foo: bar", "non-empty list"),
        ("targets:\n  - {}", "missing required 'provenance'"),  # no provenance block
        (
            "provenance:\n  retrieved_from: x\n  fetch_method: y\n" + _TARGET,
            "provenance.fetch_date",  # provenance missing a key
        ),
        (PROV + _TARGET.replace("    license: open", "    tradition: [X]"), "missing required field 'license'"),
        (PROV + _TARGET.replace("license: open", "license: bogus"), "unknown license"),
        (PROV + _TARGET.replace("tradition: [X]", "tradition: []"), "tradition must be"),
        (PROV + _TARGET.replace("payload: a.json", "payload: '   '"), "payload"),
    ],
)
def test_malformed_fails_naming_file_and_target(tmp_path, body, needle):
    y = _write(tmp_path / "texts" / "raw" / "X" / "source.yaml", body)
    with pytest.raises(cat.CatalogueError) as e:
        cat.load_source(y, tmp_path / "texts" / "raw")
    assert needle in str(e.value)
    assert "source.yaml" in str(e.value)  # names the file


# --- discovery / selection ---------------------------------------------------


def test_discovery_and_selection(tmp_path):
    raw = _fixture_tree(tmp_path)
    sources = cat.discover_catalogue(raw)
    assert len(sources) == 2
    assert len(cat.all_targets(sources)) == 3
    default = cat.select_targets(sources)
    assert all(t.license != "restricted" for t in default)
    assert len(default) == 2
    with_restricted = cat.select_targets(sources, include_restricted=True)
    assert len(with_restricted) == 3
    assert any(t.license == "restricted" for t in with_restricted)


def test_discovery_missing_raises_catalogue_missing(tmp_path):
    (tmp_path / "texts" / "raw").mkdir(parents=True)
    with pytest.raises(cat.CatalogueMissing):
        cat.discover_catalogue(tmp_path / "texts" / "raw")
    with pytest.raises(cat.CatalogueMissing):
        cat.discover_catalogue(tmp_path / "nope")


# --- path -> license recovery ------------------------------------------------


def test_license_for_raw_path_and_index(tmp_path):
    raw = _fixture_tree(tmp_path)
    sources = cat.discover_catalogue(raw)
    idx = cat.build_raw_license_index(sources, raw)
    assert cat.license_for_raw_path(raw / "Roman Catholic" / "nabre.json", sources, raw, idx) == "restricted"
    assert cat.license_for_raw_path(raw / "Protestant Christian" / "kjv.json", sources, raw, idx) == "public-domain"
    assert cat.license_for_raw_path(raw / "Roman Catholic" / "encyclicals" / "en" / "a.json", sources, raw) == "open"
    assert cat.license_for_raw_path(raw / "nope.json", sources, raw) is None


def test_slug_and_standardized_dir():
    t = cat.Target(
        source_id="Roman Catholic", payload="nabre.json", converter="nabre",
        work="The Bible", version="NABRE", language="en", document_type="scripture",
        tradition=("Roman Catholic",), license="restricted",
        provenance=cat.Provenance("x", "y", "z"),
        requested_as=("NABRE",), canonical_language="en",
    )
    assert t.slug == "the-bible-nabre-en"
    assert t.standardized_dir(Path("texts/standardized")) == Path(
        "texts/standardized/Roman Catholic/the-bible-nabre-en"
    )


def test_standardized_filter_drops_restricted_and_fails_closed(tmp_path):
    raw = _fixture_tree(tmp_path)
    sources = cat.discover_catalogue(raw)
    std = tmp_path / "texts" / "standardized"
    open_t = next(t for t in cat.all_targets(sources) if t.license == "open")
    restricted_t = next(t for t in cat.all_targets(sources) if t.license == "restricted")
    open_doc = _std_doc(open_t.standardized_dir(std) / "doc.json")
    restricted_doc = _std_doc(restricted_t.standardized_dir(std) / "doc.json")

    assert cat.license_for_standardized_path(open_doc, sources, std) == "open"
    assert cat.license_for_standardized_path(restricted_doc, sources, std) == "restricted"

    kept = cat.filter_standardized_paths([std], sources, include_restricted=False, standardized_root=std)
    assert kept == [open_doc]  # restricted dropped
    kept_all = cat.filter_standardized_paths([std], sources, include_restricted=True, standardized_root=std)
    assert set(kept_all) == {open_doc, restricted_doc}

    # fail-closed: a standardized file outside every target dir cannot be verified
    stray = _std_doc(std / "stray.json")
    with pytest.raises(cat.CatalogueError):
        cat.filter_standardized_paths([stray], sources, standardized_root=std)


# --- CLI gate ----------------------------------------------------------------


def test_cli_convert_writes_standardized(tmp_path):
    raw = _fixture_tree(tmp_path)
    std = tmp_path / "std"
    r = runner.invoke(
        app,
        ["convert", "--source", "Protestant Christian", "--raw-root", str(raw),
         "--standardized-root", str(std)],
    )
    assert r.exit_code == 0, r.output
    out = std / "Protestant Christian" / "the-bible-kjv-en" / "kjv.json"
    assert out.exists()
    # output lands under the standardized-path convention, so its license is recoverable
    assert cat.license_for_standardized_path(out, cat.discover_catalogue(raw), std) == "public-domain"


def test_cli_convert_excludes_restricted_by_default(tmp_path):
    raw = _fixture_tree(tmp_path)
    std = tmp_path / "std"
    # nabre is restricted -> default selects nothing under --converter nabre
    r = runner.invoke(
        app,
        ["convert", "--converter", "nabre", "--raw-root", str(raw), "--standardized-root", str(std)],
    )
    assert r.exit_code != 0
    assert "no targets selected" in r.output
    # opt-in selects it (then fails on the fixture's empty payload — but it WAS selected)
    r2 = runner.invoke(
        app,
        ["convert", "--converter", "nabre", "--raw-root", str(raw), "--standardized-root", str(std),
         "--include-restricted"],
    )
    assert "no targets selected" not in r2.output


def test_cli_generate_filters_restricted(tmp_path):
    raw = _fixture_tree(tmp_path)
    sources = cat.discover_catalogue(raw)
    std = tmp_path / "texts" / "standardized"
    restricted_t = next(t for t in cat.all_targets(sources) if t.license == "restricted")
    _std_doc(restricted_t.standardized_dir(std) / "doc.json")

    # default: the only doc is restricted -> filtered out -> nothing to generate
    r = runner.invoke(
        app,
        ["generate", str(std), "--raw-root", str(raw), "--standardized-root", str(std)],
    )
    assert r.exit_code != 0
    assert "restricted and excluded" in r.output

    # opt-in: the restricted doc is included (so the "all excluded" guard does NOT
    # trigger; generation may still fail later on the tiny pool)
    r2 = runner.invoke(
        app,
        ["generate", str(std), "--raw-root", str(raw), "--standardized-root", str(std),
         "--include-restricted"],
    )
    assert "restricted and excluded" not in r2.output


def test_cli_generate_fail_closed_on_unmapped(tmp_path):
    raw = _fixture_tree(tmp_path)
    std = tmp_path / "texts" / "standardized"
    stray = _std_doc(std / "stray.json")
    r = runner.invoke(
        app,
        ["generate", str(stray), "--raw-root", str(raw), "--standardized-root", str(std)],
    )
    assert r.exit_code != 0
    # fail-closed raises CatalogueError (the main() wrapper renders it in real use;
    # CliRunner surfaces it as the raised exception)
    assert isinstance(r.exception, cat.CatalogueError)
    assert "fail-closed" in str(r.exception)


def test_cli_generate_tasks_and_per_text(tmp_path):
    """The CLI exposes the --tasks subset and --per-text quota (per-text split over the
    active tasks). The doc's own (work, version, language) differs from the target's, so
    metadata must resolve by PATH (the encyclicals-style case) for the text to be in-pool."""
    raw = _fixture_tree(tmp_path)
    sources = cat.discover_catalogue(raw)
    std = tmp_path / "texts" / "standardized"
    open_t = next(t for t in cat.all_targets(sources) if t.license != "restricted")
    long = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu"
    doc = {
        "source": {"tradition": ["T"], "work": "W", "version": "V", "language": "en",
                   "document_type": "scripture"},
        "entries": [{"unit_type": "verse", "citation": f"W 1:{i}", "text": f"{long} {i}"} for i in range(20)],
    }
    _write(open_t.standardized_dir(std) / "doc.json", json.dumps(doc))
    out = tmp_path / "q.jsonl"
    r = runner.invoke(
        app,
        ["generate", str(std), "--raw-root", str(raw), "--standardized-root", str(std),
         "--tasks", "retrieve_quote", "--per-text", "3", "--out", str(out)],
    )
    assert r.exit_code == 0, r.output
    qs = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(qs) == 3 and {q["task"] for q in qs} == {"retrieve_quote"}
    assert (out.parent / "q.jsonl.manifest.json").exists()


def test_cli_gate_requires_catalogue(tmp_path):
    r = runner.invoke(
        app,
        ["generate", str(tmp_path), "--raw-root", str(tmp_path / "nope")],
    )
    assert r.exit_code != 0
    assert "catalogue" in r.output.lower()


# --- iter-2 review fixes -----------------------------------------------------


def test_slugify_collapses_runs():
    t = cat.Target(
        source_id="x", payload="p", converter="c", work="The Bible",
        version="ASV (1901)", language="en", document_type="scripture",
        tradition=("x",), license="public-domain", provenance=cat.Provenance("a", "b", "c"),
        requested_as=("ASV",), canonical_language="en",
    )
    assert t.slug == "the-bible-asv-1901-en"  # no doubled hyphens


def test_same_slug_license_disagreement_fails(tmp_path):
    item = _TARGET[len("targets:\n"):]  # one list item, same (work, version, language)
    body = PROV + "targets:\n" + item + "\n" + item.replace("license: open", "license: restricted") + "\n"
    y = _write(tmp_path / "texts" / "raw" / "X" / "source.yaml", body)
    with pytest.raises(cat.CatalogueError) as e:
        cat.load_source(y, tmp_path / "texts" / "raw")
    assert "disagree on license" in str(e.value)


def test_malformed_yaml_wrapped(tmp_path):
    y = _write(tmp_path / "texts" / "raw" / "X" / "source.yaml", "targets: [unclosed\n")
    with pytest.raises(cat.CatalogueError) as e:
        cat.load_source(y, tmp_path / "texts" / "raw")
    assert "invalid YAML" in str(e.value)


def test_standardized_tie_prefers_restricted(tmp_path):
    std = tmp_path / "std"
    common = dict(
        source_id="x", payload="p", converter="c", work="W", version="V",
        language="en", document_type="scripture", tradition=("x",),
        provenance=cat.Provenance("a", "b", "c"),
        requested_as=("W",), canonical_language="en",
    )
    open_t = cat.Target(license="open", **common)
    restricted_t = cat.Target(license="restricted", **common)
    doc = _std_doc(open_t.standardized_dir(std) / "d.json")  # same dir for both
    # most-conservative wins the depth tie, regardless of target order
    assert cat.license_for_standardized_path(doc, [_src(open_t, restricted_t)], std) == "restricted"
    assert cat.license_for_standardized_path(doc, [_src(restricted_t, open_t)], std) == "restricted"


def _src(*targets: cat.Target) -> cat.Source:
    return cat.Source(
        source_id=targets[0].source_id, yaml_path=Path("x/source.yaml"),
        targets=tuple(targets), provenance=cat.Provenance("a", "b", "c"),
    )


def test_cli_generate_reports_missing_path_distinctly(tmp_path):
    raw = _fixture_tree(tmp_path)
    r = runner.invoke(
        app,
        ["generate", str(tmp_path / "texts" / "standardized"),
         "--raw-root", str(raw), "--standardized-root", str(tmp_path / "texts" / "standardized")],
    )
    assert r.exit_code != 0
    assert "input path not found" in r.output  # not a misleading license error


# --- Spec 26: requested_as / canonical_language + text_metadata --------------


@pytest.mark.parametrize(
    "body, needle",
    [
        (PROV + _TARGET.replace("    requested_as: [Wname, W]\n", ""), "missing required field 'requested_as'"),
        (PROV + _TARGET.replace("\n    canonical_language: en", ""), "missing required field 'canonical_language'"),
        (PROV + _TARGET.replace("requested_as: [Wname, W]", "requested_as: KJV"), "requested_as must be"),
        (PROV + _TARGET.replace("requested_as: [Wname, W]", "requested_as: []"), "requested_as must be"),
        (PROV + _TARGET.replace("requested_as: [Wname, W]", "requested_as: ['  ']"), "requested_as must be"),
        (PROV + _TARGET.replace("canonical_language: en", "canonical_language: '  '"), "canonical_language"),
    ],
)
def test_requested_as_and_canonical_language_validation(tmp_path, body, needle):
    y = _write(tmp_path / "texts" / "raw" / "X" / "source.yaml", body)
    with pytest.raises(cat.CatalogueError) as e:
        cat.load_source(y, tmp_path / "texts" / "raw")
    assert needle in str(e.value)
    assert "source.yaml" in str(e.value)  # names the file


def test_target_exposes_requested_as_and_canonical_language(tmp_path):
    raw = _fixture_tree(tmp_path)
    kjv = cat.load_source(raw / "Protestant Christian" / "source.yaml", raw).targets[0]
    assert kjv.requested_as == ("King James Version", "KJV")
    assert kjv.canonical_language == "en"
    assert kjv.text_key == ("The Bible", "KJV", "en")


def test_text_metadata_nominal_view(tmp_path):
    raw = _fixture_tree(tmp_path)
    meta = cat.text_metadata(cat.discover_catalogue(raw))
    assert meta[("The Bible", "KJV", "en")].canonical_language == "en"
    enc = meta[("Papal Encyclicals", "Vatican English", "en")]
    assert enc.requested_as == ("papal encyclicals", "the encyclicals")
    assert enc.canonical_language == "la"


def test_text_metadata_conflicting_tuple_across_sources_fails(tmp_path):
    """Two source.yaml files declaring the same (work, version, language) with different
    metadata is a global conflict — the per-file slug-agreement check cannot catch it."""
    raw = tmp_path / "texts" / "raw"
    _write(raw / "A" / "source.yaml", PROV + _TARGET)
    _write(
        raw / "B" / "source.yaml",
        PROV + _TARGET.replace("requested_as: [Wname, W]", "requested_as: [Different]"),
    )
    sources = cat.discover_catalogue(raw)
    with pytest.raises(cat.CatalogueError) as e:
        cat.text_metadata(sources)
    assert "ambiguous metadata" in str(e.value)


def test_metadata_for_standardized_path_resolves_by_path(tmp_path):
    """The generation channel recovers metadata by PATH, so it works even for a document
    whose (work, version, language) differs from its target's — the encyclicals case
    (convert_encyclicals re-stamps work=title/version)."""
    raw = _fixture_tree(tmp_path)
    sources = cat.discover_catalogue(raw)
    std = tmp_path / "texts" / "standardized"
    enc_t = next(t for t in cat.all_targets(sources) if t.work == "Papal Encyclicals")
    # a document whose work is a specific encyclical title (NOT the target's nominal work)
    doc = _std_doc(enc_t.standardized_dir(std) / "humanae-vitae.json", work="Humanae Vitae")
    tm = cat.metadata_for_standardized_path(doc, sources, std)
    assert tm is not None
    assert tm.requested_as == ("papal encyclicals", "the encyclicals")
    assert tm.canonical_language == "la"
    # a path under no target directory is unresolved (callers fail closed on None)
    assert cat.metadata_for_standardized_path(_std_doc(std / "stray.json"), sources, std) is None


def test_slug_agreement_covers_canonical_language(tmp_path):
    item = _TARGET[len("targets:\n"):]  # one item, same (work, version, language) -> same slug
    body = (
        PROV + "targets:\n" + item + "\n"
        + item.replace("canonical_language: en", "canonical_language: ar") + "\n"
    )
    y = _write(tmp_path / "texts" / "raw" / "X" / "source.yaml", body)
    with pytest.raises(cat.CatalogueError) as e:
        cat.load_source(y, tmp_path / "texts" / "raw")
    # the message names the field that actually differs, not all three
    assert "disagree on canonical_language" in str(e.value)


def test_real_catalogue_default_pool_is_eighteen():
    """The committed corpus: 22 targets, default pool (language == canonical_language,
    non-restricted) is exactly these 18 texts (Spec 37 added the Guru Granth Sahib); every target carries both new fields; the two
    LDS KJV targets are gone (issue #27 Q3). Pins membership, not just the count, so a
    canonical_language typo that silently drops/adds a text fails loudly."""
    sources = cat.discover_catalogue(REPO_ROOT / "texts" / "raw")
    targets = cat.all_targets(sources)
    assert len(targets) == 22
    for t in targets:
        assert t.requested_as and all(isinstance(n, str) and n for n in t.requested_as)
        assert isinstance(t.canonical_language, str) and t.canonical_language
    # no LDS KJV targets remain
    assert not [t for t in targets if t.version == "KJV (LDS 2013 edition)"]
    # cross-source conflict guard is live on the real catalogue
    cat.text_metadata(sources)
    pool = {t.text_key for t in targets if t.language == t.canonical_language and t.license != "restricted"}
    assert pool == {
        ("The Qur'an", "Uthmani (QUL)", "ar"),
        ("Sahih al-Bukhari", "sunnah.com Arabic", "ar"),
        ("Sahih Muslim", "sunnah.com Arabic", "ar"),
        ("Sunan Abi Dawud", "sunnah.com Arabic", "ar"),
        ("Jami` at-Tirmidhi", "sunnah.com Arabic", "ar"),
        ("Sunan an-Nasa'i", "sunnah.com Arabic", "ar"),
        ("Sunan Ibn Majah", "sunnah.com Arabic", "ar"),
        ("Muwatta Malik", "sunnah.com Arabic", "ar"),
        ("Musnad Ahmad", "sunnah.com Arabic", "ar"),
        ("Sunan al-Darimi", "sunnah.com Arabic", "ar"),
        ("Talmud Bavli", "William Davidson Edition - Aramaic", "he"),
        ("Book of Mormon", "2013 edition", "en"),
        ("Doctrine and Covenants", "2013 edition", "en"),
        ("Pearl of Great Price", "2013 edition", "en"),
        ("The Bible", "KJV", "en"),
        ("The Bible", "ASV (1901)", "en"),
        ("The Bible", "WEB", "en"),
        ("Sri Guru Granth Sahib", "Shabad OS (SGPC Shabadaarth)", "pa"),
    }


# --- gitignore reachability (regression guard for the real repo) -------------


def _check_ignored(rel: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO_ROOT, capture_output=True)
    return r.returncode == 0


def test_real_source_yaml_are_trackable_and_payloads_ignored():
    for rel in [
        "texts/raw/Protestant Christian/source.yaml",
        "texts/raw/Sunni Islam/source.yaml",
        "texts/raw/Judaism/source.yaml",
        "texts/raw/Roman Catholic/source.yaml",
        "texts/raw/Greek Orthodox/source.yaml",
        "texts/raw/The Church of Jesus Christ of Latter-Day Saints/source.yaml",
        "texts/raw/Sikhism/source.yaml",
        "texts/raw/Sikhism/sggs_shabados.json",
    ]:
        assert (REPO_ROOT / rel).exists(), f"missing committed catalogue file: {rel}"
        assert not _check_ignored(rel), f"source.yaml must be trackable: {rel}"
    for rel in [
        "texts/raw/Roman Catholic/nabre.json",
        "texts/raw/Greek Orthodox/septuagint.json",
        "texts/standardized/Judaism/anything.json",
    ]:
        assert _check_ignored(rel), f"restricted/standardized path must be ignored: {rel}"
