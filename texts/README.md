# texts/ — corpora (two-tier: raw → standardized)

- **`raw/`** — source data exactly as obtained, organised by tradition. Seeded
  from the working group's Box folder ("Phase I / raw JSON", downloaded
  2026-10-10). Two subsets are **held back from this public repo** pending
  licensing and exist only locally (see `.gitignore`):
  - `raw/Roman Catholic/nabre.json` — NABRE is a copyrighted translation
    (Confraternity of Christian Doctrine / USCCB).
  - `raw/Greek Orthodox/` — direct extracts of the licensed TLG corpus
    (and the underlying Rahlfs Septuagint / Nestle-Aland editions are
    themselves copyrighted).
- **`standardized/`** — the working group's standard flat-format documents,
  produced from `raw/` by `sacredbench convert` (see `pipelines/README.md`).
  Rebuilt locally; corpora derived from copyrighted sources are not committed.

## Obtaining the held-back sources

Both held-back sources live in the working group's access-controlled Box folder
— **"Phase I / raw JSON"** (<https://byu.app.box.com/s/pgptf0ntvthlgabpn85m5kn5o73r3sy3>,
BYU Box login + group membership required). After downloading, place them so the
layout matches the committed tree:

- **NABRE** → download `Roman Catholic/nabre.json` from Box and save it as
  `texts/raw/Roman Catholic/nabre.json`. Alternatively rebuild it from
  [`Religion-at-Notre-Dame/catholic_text_json`](https://github.com/Religion-at-Notre-Dame/catholic_text_json)
  (the upstream source of the group's copy).
- **Greek Orthodox (TLG)** → download the whole `Greek Orthodox/` folder from
  Box and save it as `texts/raw/Greek Orthodox/`. These files are extracts of
  the licensed [TLG](https://stephanus.tlg.uci.edu/) corpus — you (or your
  institution) must hold TLG access rights to use them.

Both paths are gitignored, so a local copy never ends up in a commit. The
pipeline treats them as **restricted** sources: they are excluded from
conversion and benchmark generation unless explicitly enabled with
`--include-restricted` (see the catalogue section in `pipelines/README.md`), and
committed benchmark artifacts must never embed their text. Each restricted
source still carries a committed `source.yaml` (with its payload held back) so
the catalogue stays complete and auditable.

`raw/Sikhism/sggs_shabados.json` is a verbatim, filtered extract of the Shabad OS
database (the Sri Guru Granth Sahib's lines only — the full database is 603 MB of
TOML). `raw/Sikhism/build_extract.py` rebuilds it byte for byte from a checkout of
`shabados/shabados` at the commit recorded in the file's `upstream` header.

Per-source provenance metadata lives in each `texts/raw/<tradition>/source.yaml`
(a targets manifest — provenance, converter, and a `license` field per target;
see `pipelines/sacredbench/catalogue.py`).
