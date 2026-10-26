"""Build ``sggs_shabados.json``: every Sri Guru Granth Sahib line from Shabad OS, verbatim.

Shabad OS keeps its database as one TOML file per line (603 MB, many works), so the
committed payload is a filtered extract: the Guru Granth Sahib's lines only, each with
its upstream text EXACTLY as stored. Nothing is cleaned here; the converter
(``sacredbench.convert.convert_shabados_sggs``) owns that.

Usage, from a checkout of github.com/shabados/shabados (a sparse checkout of
``database/collections/{lines,line-groups,sections}`` is enough):

    python3 -I texts/raw/Sikhism/build_extract.py <shabados-checkout> texts/raw/Sikhism/sggs_shabados.json

Shape of the real data (derived from it, commit 7e36a29, 2026-10-22):

- A Guru Granth Sahib line is a ``type = "primary"`` content item tagged with asset
  ``SSA2`` (Shabadaarth, SGPC). It carries ``page`` (the Ang) and ``line`` (the
  PHYSICAL printed line; several panktis can share one, so it is not unique).
- Order is ``sections -> lineGroups -> lines``. 51 sections hold every Guru Granth
  Sahib line group (Jap, So Dar, ... Raagmala). Upstream records no order for the
  sections themselves, so they are sorted by their first line's ``(page, line)``;
  their Ang ranges do not overlap, which this script asserts.

Fail-fast: a line in no section, a line group in two sections, or overlapping
section ranges raises.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ASSET = "SSA2"
EXPECTED_SECTIONS = 51


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text("utf-8"))


def build(checkout: Path) -> dict:
    root = checkout / "database" / "collections"
    lines: dict[str, dict] = {}
    for p in sorted((root / "lines").rglob("*.toml")):
        for item in _load(p).get("content", []):
            if item.get("type") == "primary" and ASSET in item.get("assets", []):
                if p.stem in lines:
                    raise SystemExit(f"{p}: two {ASSET} primary items")
                lines[p.stem] = item

    groups: dict[str, list[str]] = {}
    for p in sorted((root / "line-groups").rglob("*.toml")):
        ids = _load(p)["lines"]
        mine = [i for i in ids if i in lines]
        if mine and len(mine) != len(ids):
            raise SystemExit(f"{p}: line group mixes {ASSET} and other lines")
        if mine:
            groups[p.stem] = mine

    sections = []
    seen_groups: set[str] = set()
    for p in sorted((root / "sections").glob("*.toml")):
        s = _load(p)
        gs = [g for g in s.get("lineGroups", []) if g in groups]
        if not gs:
            continue
        if len(gs) != len(s["lineGroups"]):
            raise SystemExit(f"{p}: section mixes {ASSET} and other line groups")
        if seen_groups & set(gs):
            raise SystemExit(f"{p}: line group in two sections")
        seen_groups |= set(gs)
        sections.append({"id": p.stem, "name": s.get("name", {}).get("Latn"), "line_groups": gs})

    if seen_groups != set(groups):
        raise SystemExit(f"{len(set(groups) - seen_groups)} {ASSET} line groups are in no section")
    if len(sections) != EXPECTED_SECTIONS:
        raise SystemExit(f"expected {EXPECTED_SECTIONS} sections, found {len(sections)}")

    def pos(line_id: str) -> tuple[int, int]:
        return (lines[line_id]["page"], lines[line_id]["line"])

    sections.sort(key=lambda s: (pos(groups[s["line_groups"][0]][0]), s["id"]))
    for a, b in zip(sections, sections[1:]):
        if pos(groups[a["line_groups"][-1]][-1]) > pos(groups[b["line_groups"][0]][0]):
            raise SystemExit(f"sections {a['id']} and {b['id']} overlap")

    out_lines = []
    for s in sections:
        for g in s["line_groups"]:
            for line_id in groups[g]:
                item = lines[line_id]
                out_lines.append({
                    "id": line_id, "section": s["id"], "line_group": g,
                    "ang": item["page"], "line": item["line"], "data": item["data"],
                })
    if len(out_lines) != len(lines):
        raise SystemExit(f"{len(lines) - len(out_lines)} {ASSET} lines are in no line group")

    commit = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "upstream": {
            "repo": "https://github.com/shabados/shabados",
            "commit": commit,
            "path": "database/collections",
            "asset": ASSET,
            "note": "verbatim primary text; filtered to the Guru Granth Sahib; ordered sections -> lineGroups -> lines",
        },
        "sections": [{"id": s["id"], "name": s["name"]} for s in sections],
        "lines": out_lines,
    }


def dump(extract: dict) -> str:
    """One line per record, so a diff shows exactly which lines changed."""
    head = {k: v for k, v in extract.items() if k != "lines"}
    body = ",\n".join("    " + json.dumps(r, ensure_ascii=False) for r in extract["lines"])
    head_json = json.dumps(head, ensure_ascii=False, indent=2)
    return head_json[:-2] + ',\n  "lines": [\n' + body + "\n  ]\n}\n"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    extract = build(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(dump(extract), encoding="utf-8")
    print(f"{len(extract['lines'])} lines, {len(extract['sections'])} sections, commit {extract['upstream']['commit']}")
