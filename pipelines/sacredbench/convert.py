"""Converters from known source-JSON shapes into the standard flat format.

Every converter implements one dispatch contract so the catalogue drives them
uniformly:

    convert_target(paths, target) -> list[Document]

where ``paths`` are the target's resolved payload files and ``target`` is a
``catalogue.Target`` carrying ``work``/``version``/``language``/``document_type``/
``tradition``. Shapes are derived from the REAL reference data (not docs — e.g.
LDS D&C is 2-level ``{section: {verse: text}}`` while the other LDS works are
3-level ``{book: {chapter: {verse: text}}}``, and Pearl of Great Price carries
``last_modified``/``version`` metadata keys).

Registered converters (English corpora land here in Phase 2; Arabic/Talmud in
Phase 3):

- ``bible_flat``: Protestant KJV/ASV/WEB — a flat list
  ``[{book, chapter, verse, text}]`` → one scripture document per version file.
- ``lds_nested``: LDS works — nested ``{book: {[heading], chapter: {verse: text}}}``
  (or 2-level ``{section: {verse: text}}`` for D&C) → one document per file.
- ``encyclicals``: Vatican encyclicals — one ``{title, paragraphs}`` file becomes
  its own document (work = title, version = Vatican edition).
- ``nabre`` (restricted): NABRE book files ``{book, chapters: [...]}`` merge into
  one scripture document.
- ``shabados_sggs`` (Spec 37): the Sri Guru Granth Sahib extract from Shabad OS →
  one document of panktis cited ``Ang N:k``, Shabad OS apparatus removed.

Converters are fail-fast: an unexpected shape raises ``ConvertError`` naming the
file. Adding a source format = one function + one ``CONVERTERS`` registry line.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sacredbench.schema import Document, Entry

if TYPE_CHECKING:
    from sacredbench.catalogue import Target


class ConvertError(Exception):
    """Source data did not match the declared format."""


def _load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConvertError(f"{path}: not valid JSON ({e})") from e


def _doc(target: "Target", entries: list[Entry], source_url: str | None = None) -> Document:
    """Build a Document from a target's catalogue metadata."""
    return Document(
        tradition=list(target.tradition),
        work=target.work,
        version=target.version,
        language=target.language,
        document_type=target.document_type,
        source_url=source_url,
        entries=entries,
    )


def _split_camel_book(name: str) -> str:
    """``1Corinthians`` -> ``1 Corinthians`` (NABRE book names are camel-run)."""
    name = re.sub(r"(?<=\d)(?=[A-Z])", " ", name)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def _require_unique_citations(entries: list[Entry], where: str) -> None:
    """Every citation in a document must identify exactly one unit (benchmark
    ground-truth needs this). Fail-fast on a duplicate, naming the file+citation."""
    seen: set[str] = set()
    for e in entries:
        if e.citation in seen:
            raise ConvertError(f"{where}: duplicate citation {e.citation!r} (citations must be unique)")
        seen.add(e.citation)


#: LDS files carry these scalar top-level keys alongside the scripture books.
_LDS_METADATA_KEYS = {"last_modified", "version"}


# --- Protestant flat-list Bibles (bible_flat) --------------------------------


def convert_bible_flat(paths: list[Path], target: "Target") -> list[Document]:
    """Each flat-list file ``[{book, chapter, verse, text}]`` → one scripture doc."""
    docs: list[Document] = []
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, list) or not data:
            raise ConvertError(f"{path}: expected a non-empty list of verse records (bible_flat)")
        entries: list[Entry] = []
        for i, row in enumerate(data):
            if not isinstance(row, dict):
                raise ConvertError(f"{path}: record {i} is not an object")
            book, chapter, verse, text = row.get("book"), row.get("chapter"), row.get("verse"), row.get("text")
            if not (isinstance(book, str) and isinstance(chapter, int) and isinstance(verse, int) and isinstance(text, str)):
                raise ConvertError(f"{path}: record {i} is not {{book:str, chapter:int, verse:int, text:str}}")
            if not text.strip():
                continue
            entries.append(Entry(unit_type="verse", citation=f"{book} {chapter}:{verse}", text=text.strip()))
        if not entries:
            raise ConvertError(f"{path}: produced no entries")
        _require_unique_citations(entries, str(path))
        docs.append(_doc(target, entries))
    return docs


# --- LDS nested scriptures (lds_nested) --------------------------------------


def _lds_entries(data: dict, target: "Target", path: Path) -> list[Entry]:
    entries: list[Entry] = []
    for book_name, book_val in data.items():
        if book_name in _LDS_METADATA_KEYS:
            continue  # known scalar metadata (last_modified, version)
        if not isinstance(book_val, dict):
            raise ConvertError(f"{path}: unexpected non-object top-level key {book_name!r}")
        # 'heading' is an editorial summary (book- AND chapter-level), never scripture.
        items = [(k, v) for k, v in book_val.items() if k != "heading"]
        if not items:
            continue
        if all(isinstance(v, str) for _, v in items):
            # 2-level: this top key is itself a section -> {verse: text} (D&C). Prefix
            # the work so the citation is self-identifying (e.g. not a bare "1:1").
            for verse, text in items:
                if not text.strip():
                    continue
                entries.append(
                    Entry(unit_type="verse", citation=f"{target.work} {book_name}:{verse}", text=text.strip())
                )
        elif all(isinstance(v, dict) for _, v in items):
            # 3-level: book -> chapter -> {verse: text}
            for chapter, verses in items:
                for verse, text in verses.items():
                    if verse == "heading":
                        continue  # chapter-level editorial summary, not a verse
                    if not isinstance(text, str):
                        raise ConvertError(f"{path}: {book_name} {chapter}:{verse} is not text")
                    if not text.strip():
                        continue
                    entries.append(
                        Entry(unit_type="verse", citation=f"{book_name} {chapter}:{verse}", text=text.strip())
                    )
        else:
            raise ConvertError(
                f"{path}: book {book_name!r} mixes verse-strings and chapter-objects (unexpected LDS shape)"
            )
    return entries


def convert_lds_nested(paths: list[Path], target: "Target") -> list[Document]:
    """Each nested LDS file → one scripture document (handles 2- and 3-level shapes)."""
    docs: list[Document] = []
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ConvertError(f"{path}: expected a nested object (lds_nested)")
        entries = _lds_entries(data, target, path)
        if not entries:
            raise ConvertError(f"{path}: produced no entries")
        _require_unique_citations(entries, str(path))
        docs.append(_doc(target, entries))
    return docs


# --- Papal encyclicals (encyclicals) -----------------------------------------


def convert_encyclicals(paths: list[Path], target: "Target") -> list[Document]:
    """Each ``{title, paragraphs}`` file becomes its own document (work = title)."""
    files = [p for p in paths if p.name != "index.json"]
    if not files:
        raise ConvertError("encyclicals: no encyclical files (only index.json?)")
    docs: list[Document] = []
    for path in files:
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ConvertError(f"{path}: top level must be an object (encyclicals format)")
        title, paragraphs = data.get("title"), data.get("paragraphs")
        if not isinstance(title, str) or not isinstance(paragraphs, list):
            raise ConvertError(f"{path}: expected {{title, paragraphs}} (encyclicals format)")
        pope, date = data.get("pope", ""), data.get("publicationDate", "")
        entries: list[Entry] = []
        # Conversion is LOSSLESS: every non-empty paragraph is kept. A paragraph is
        # cited by its DECLARED number (`para. {n}`); unnumbered paragraphs (front
        # matter) get a non-canonical `unnumbered para. {k}`. The real data has
        # genuine duplicate declared numbers — a trailing bibliographic footnote
        # block whose numbering restarts, plus in-body typos and numbered section
        # headings — so a repeated number is disambiguated with a `(dup N)` suffix
        # rather than being dropped (classifying footnotes is Phase 5's generation
        # concern; truncating here silently loses body prose). Citations stay unique.
        used: set[str] = set()
        unnumbered = 0
        for i, para in enumerate(paragraphs, start=1):
            if not isinstance(para, dict):
                raise ConvertError(f"{path}: paragraphs[{i - 1}] is not an object")
            text = para.get("text")
            if not isinstance(text, str):
                raise ConvertError(f"{path}: paragraphs[{i - 1}] has no text")
            if not text.strip():
                continue
            num = para.get("paragraph")
            if num is None:
                unnumbered += 1
                citation = f"{title}, unnumbered para. {unnumbered}"
            else:
                if not isinstance(num, int):
                    raise ConvertError(f"{path}: paragraphs[{i - 1}].paragraph is not an integer")
                citation = f"{title}, para. {num}"
                if citation in used:
                    dup = 2
                    while f"{citation} (dup {dup})" in used:
                        dup += 1
                    citation = f"{citation} (dup {dup})"
            used.add(citation)
            entries.append(Entry(unit_type="paragraph", citation=citation, text=text.strip()))
        if not entries:
            raise ConvertError(f"{path}: encyclical has no non-empty paragraphs")
        _require_unique_citations(entries, str(path))
        docs.append(
            Document(
                tradition=list(target.tradition),
                work=title,
                version=f"Vatican English text ({pope}, {date})".strip(),
                language=target.language,
                document_type=target.document_type,
                source_url=data.get("vaticanUrl"),
                entries=entries,
            )
        )
    return docs


# --- NABRE Bible books (nabre, restricted) -----------------------------------


def convert_nabre(paths: list[Path], target: "Target") -> list[Document]:
    """Merge NABRE book objects into one document.

    The real ``nabre.json`` is a TOP-LEVEL LIST of book objects
    ``{book, chapters: [{chapter, verses: [{verse, text}]}]}`` (one file, 73 books);
    a single ``{book, chapters}`` object (one file per book) is also accepted. Verse
    text is kept verbatim apart from whitespace — NABRE embeds heading strings inside
    the first verse of a chapter ("Preamble. The Creation of the World Chapter 1 - …"),
    which are part of the source text and are not stripped."""
    entries: list[Entry] = []
    for path in paths:
        data = _load_json(path)
        books = data if isinstance(data, list) else [data]
        for bi, book_obj in enumerate(books):
            if not isinstance(book_obj, dict):
                raise ConvertError(f"{path}: book[{bi}] is not an object (nabre format)")
            book, chapters = book_obj.get("book"), book_obj.get("chapters")
            if not isinstance(book, str) or not isinstance(chapters, list):
                raise ConvertError(f"{path}: book[{bi}] expected {{book, chapters}} (nabre format)")
            book_name = _split_camel_book(book)
            for ch in chapters:
                if not isinstance(ch, dict):
                    raise ConvertError(f"{path}: {book} has a non-object chapter entry")
                ch_num, verses = ch.get("chapter"), ch.get("verses")
                if not isinstance(ch_num, int) or not isinstance(verses, list):
                    raise ConvertError(f"{path}: chapter entry missing 'chapter'/'verses'")
                for v in verses:
                    if not isinstance(v, dict):
                        raise ConvertError(f"{path}: {book} {ch_num} has a non-object verse entry")
                    v_num, text = v.get("verse"), v.get("text")
                    if not isinstance(v_num, int) or not isinstance(text, str):
                        raise ConvertError(f"{path}: {book} {ch_num} has a malformed verse")
                    if not text.strip():
                        continue
                    entries.append(Entry(unit_type="verse", citation=f"{book_name} {ch_num}:{v_num}", text=text.strip()))
    if not entries:
        raise ConvertError("nabre conversion produced no entries")
    _require_unique_citations(entries, f"{target.work} [{target.version}] (merged {len(paths)} payload file(s))")
    return [_doc(target, entries)]


# --- Qur'an (quran_qul) ------------------------------------------------------


def convert_quran_qul(paths: list[Path], target: "Target") -> list[Document]:
    """QUL dict keyed ``"surah:ayah"`` -> ``{verse_key, text, ...}`` → one document."""
    docs: list[Document] = []
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ConvertError(f"{path}: expected an object keyed by 'surah:ayah' (quran_qul)")
        entries: list[Entry] = []
        for key, rec in data.items():
            if not isinstance(rec, dict):
                raise ConvertError(f"{path}: entry {key!r} is not an object")
            verse_key, text = rec.get("verse_key"), rec.get("text")
            if not isinstance(verse_key, str) or not isinstance(text, str):
                raise ConvertError(f"{path}: entry {key!r} missing 'verse_key'/'text'")
            if not text.strip():
                continue
            # Canonical Qur'an citation is the bare "surah:ayah" (universally
            # unambiguous), per the interchange contract.
            entries.append(Entry(unit_type="ayah", citation=verse_key, text=text.strip()))
        if not entries:
            raise ConvertError(f"{path}: produced no ayat")
        _require_unique_citations(entries, str(path))
        docs.append(_doc(target, entries))
    return docs


# --- Hadith collections (hadith_sunnah) --------------------------------------


def convert_hadith_sunnah(paths: list[Path], target: "Target") -> list[Document]:
    """sunnah.com ``{metadata, chapters[], hadiths[{idInBook, arabic}]}`` → one document."""
    docs: list[Document] = []
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ConvertError(f"{path}: top level must be an object (hadith_sunnah)")
        hadiths = data.get("hadiths")
        if not isinstance(hadiths, list):
            raise ConvertError(f"{path}: expected a 'hadiths' list (hadith_sunnah)")
        entries: list[Entry] = []
        for i, h in enumerate(hadiths):
            if not isinstance(h, dict):
                raise ConvertError(f"{path}: hadiths[{i}] is not an object")
            number, text = h.get("idInBook"), h.get("arabic")
            if not isinstance(number, (str, int)) or not str(number).strip() or not isinstance(text, str):
                raise ConvertError(f"{path}: hadiths[{i}] missing or malformed 'idInBook'/'arabic'")
            if not text.strip():
                continue
            entries.append(Entry(unit_type="hadith", citation=f"{target.work} {number}", text=text.strip()))
        if not entries:
            raise ConvertError(f"{path}: produced no hadiths")
        _require_unique_citations(entries, str(path))
        docs.append(_doc(target, entries))
    return docs


# --- Babylonian Talmud (sefaria_talmud) --------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_markup(s: str) -> str:
    """Strip HTML tags and unescape entities so standardized text is exact clean text."""
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub("", s))).strip()


def convert_sefaria_talmud(paths: list[Path], target: "Target") -> list[Document]:
    """Sefaria tractate files (``{title, text: [[line, ...], ...]}``) → one document.

    ``text`` is indexed ``[section][line]`` where section 0/1 are empty (tractates
    begin at daf 2a), so section index ``i`` maps to daf ``(i // 2) + 1`` with side
    ``a`` (even) / ``b`` (odd). HTML markup is stripped so the stored text is exact.
    All given tractate files merge into one ``Talmud Bavli`` document; the tractate
    name prefixes each citation (``<Tractate> <daf><side>:<line>``).
    """
    entries: list[Entry] = []
    seen: dict[str, list] = {}  # tractate -> its text, to dedup redundant copies
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, dict):
            raise ConvertError(f"{path}: top level must be an object (sefaria_talmud)")
        tractate, text = data.get("title"), data.get("text")
        if not isinstance(tractate, str) or not isinstance(text, list):
            raise ConvertError(f"{path}: expected {{title, text: [...]}} (sefaria_talmud)")
        # Cross-check the file's own language against the target: the en/he split is
        # a glob convention, so guard against a widened glob mislabelling a tractate.
        file_lang = data.get("language")
        if file_lang is not None and file_lang != target.language:
            raise ConvertError(
                f"{path}: file language {file_lang!r} != target language {target.language!r}"
            )
        if tractate in seen:
            # the committed tree has a redundant identical copy of one tractate
            # (Shevuot, in the Davidson-English subdir); skip it, but refuse a
            # genuinely conflicting duplicate rather than silently picking one.
            if text != seen[tractate]:
                raise ConvertError(f"{path}: conflicting duplicate tractate {tractate!r}")
            continue
        seen[tractate] = text
        for i, section in enumerate(text):
            if not section:
                continue  # empty leading sections (tractates start at 2a) and gaps
            if not isinstance(section, list):
                raise ConvertError(f"{path}: section {i} is not a list of lines")
            daf = (i // 2) + 1
            side = "a" if i % 2 == 0 else "b"
            for line_no, raw in enumerate(section, start=1):
                if not isinstance(raw, str):
                    raise ConvertError(f"{path}: {tractate} {daf}{side}:{line_no} is not text")
                clean = _clean_markup(raw)
                if not clean:
                    continue
                entries.append(
                    Entry(unit_type="line", citation=f"{tractate} {daf}{side}:{line_no}", text=clean)
                )
    if not entries:
        raise ConvertError("sefaria_talmud produced no entries")
    _require_unique_citations(entries, f"{target.work} [{target.version}] (merged {len(paths)} tractate files)")
    return [_doc(target, entries)]


# --- Sri Guru Granth Sahib (shabados_sggs) ------------------------------------

# Shabad OS apparatus — editorial markup that is not in the printed Granth. Removing it
# never adds, deletes, or changes a word (the Shabad OS licence forbids that).
_SGGS_VISHRAAM_RE = re.compile(r"[;.,]")  # pause marks from a reading pothi
_SGGS_SUBSCRIPT_RE = re.compile(r"[₀-₉]")  # Shabad OS disambiguation tags in raag headings
_SGGS_COUNTER_RE = re.compile(r"(?<=॥)[੦-੯]+(?=॥)")  # verse counters: ॥੧॥, ॥੪॥੯॥੬੦॥
# bindi + ZWJ + sihari-ii is a font workaround; standard Unicode order is ii + bindi
_SGGS_BINDI_II = ("ਂ‍ੀ", "ੀਂ")

# Upstream Ang values that are wrong, keyed by Shabad OS line id: (upstream, correct).
# Both lines break reading order upstream, and BaniDB (api.banidb.com/v2/angs) places
# them on the corrected Ang. A stale erratum (upstream fixed) fails loudly.
_SGGS_ANG_ERRATA = {
    "JJSV": (1337, 1336),  # ਹਰਿ ਹਰਿ ਆਪੁ ਧਰਿਓ ... ਇਕਫਾ ॥੪॥੫॥ — closes the shabad on 1336:19
    "V41B": (1377, 1378),  # ਬੰਨੑਿ ਉਠਾਈ ਪੋਟਲੀ ... ॥੨॥ — 1378:1
}


def clean_sggs_line(data: str) -> str:
    """One Shabad OS primary line -> the pankti's words: vishraam, subscript tags,
    variation selectors and verse counters removed, the bindi/ZWJ order fixed. Dandas are
    dropped too: they are punctuation (``normalize`` folds them to a space), and as
    space-delimited tokens they would count as words against generate's word thresholds.
    ``ਰਹਾਉ`` and the digits of headings (``ਮਹਲਾ ੫``) are words and stay."""
    t = data.replace(*_SGGS_BINDI_II).replace("︀", "")
    t = _SGGS_SUBSCRIPT_RE.sub("", _SGGS_VISHRAAM_RE.sub("", t))
    t = _SGGS_COUNTER_RE.sub("", t).replace("॥", " ").replace("।", " ")
    return " ".join(t.split())


def convert_shabados_sggs(paths: list[Path], target: "Target") -> list[Document]:
    """``sggs_shabados.json`` (``{upstream, sections, lines[{id, ang, line, data}]}``, lines in
    reading order — see ``texts/raw/Sikhism/build_extract.py``) → one document.

    The unit is the pankti; its citation is ``Ang N:k``, k = its 1-based position on Ang N in
    reading order. Shabad OS's ``line`` is the PHYSICAL printed line and repeats (several
    panktis share one), so it is not used. Fail-fast: an Ang that decreases along the
    reading order, a stale erratum, or a ZWJ / variation selector the cleaning missed."""
    if len(paths) != 1:
        raise ConvertError(f"shabados_sggs expects one payload file, got {len(paths)}")
    path = paths[0]
    data = _load_json(path)
    lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(lines, list):
        raise ConvertError(f"{path}: expected an object with a 'lines' list (shabados_sggs)")
    entries: list[Entry] = []
    prev_ang, k = 0, 0
    for i, rec in enumerate(lines):
        if not isinstance(rec, dict) or not isinstance(rec.get("ang"), int) or not isinstance(rec.get("data"), str):
            raise ConvertError(f"{path}: lines[{i}] missing or malformed 'ang'/'data'")
        ang = rec["ang"]
        if rec.get("id") in _SGGS_ANG_ERRATA:
            upstream, correct = _SGGS_ANG_ERRATA[rec["id"]]
            if ang != upstream:
                raise ConvertError(f"{path}: erratum for line {rec['id']} is stale (upstream Ang is now {ang})")
            ang = correct
        if ang < prev_ang:
            raise ConvertError(f"{path}: lines[{i}] ({rec.get('id')}) Ang {ang} after Ang {prev_ang}")
        k = k + 1 if ang == prev_ang else 1
        prev_ang = ang
        text = clean_sggs_line(rec["data"])
        if "‍" in text or "︀" in text:
            raise ConvertError(f"{path}: lines[{i}] ({rec.get('id')}) keeps an unhandled joiner/selector")
        if text:
            entries.append(Entry(unit_type="pankti", citation=f"Ang {ang}:{k}", text=text))
    if not entries:
        raise ConvertError(f"{path}: produced no panktis")
    _require_unique_citations(entries, str(path))
    return [_doc(target, entries)]


CONVERTERS = {
    "bible_flat": convert_bible_flat,
    "lds_nested": convert_lds_nested,
    "encyclicals": convert_encyclicals,
    "nabre": convert_nabre,
    "quran_qul": convert_quran_qul,
    "hadith_sunnah": convert_hadith_sunnah,
    "sefaria_talmud": convert_sefaria_talmud,
    "shabados_sggs": convert_shabados_sggs,
}


def convert_target(paths: list[Path], target: "Target") -> list[Document]:
    """Dispatch a catalogue target to its converter. Fail-fast on an unregistered one."""
    fn = CONVERTERS.get(target.converter)
    if fn is None:
        raise ConvertError(
            f"{target.source_id}: converter {target.converter!r} is not registered "
            "(it lands in a later phase)"
        )
    if not paths:
        raise ConvertError(
            f"{target.source_id}: target {target.work!r} [{target.version}] has no payload files "
            f"(glob {target.payload!r} matched nothing — is the payload present?)"
        )
    return fn(list(paths), target)
