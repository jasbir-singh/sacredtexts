"""Write the six review pages from the question files.

The pages list the citations actually drawn. They do not keep a second,
hand-picked list. The Islam page prints the prompt templates build_questions.py
uses, so the page cannot drift from the questions (PR #78). It writes only the
review pages: every questions.jsonl and passages.json (with its notice and
provenance) is written by build_questions.py, the one rebuild command (PR #98).

Run with the pipelines environment from the repo root:
``uv --project pipelines run python items/for-test/review/build_review.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from build_questions import EN, QURAN_AR, QURAN_FILE, QURAN_VERSION, RAW, SGGS_EN, edition_name

OUT = Path(__file__).resolve().parent

TASKS = (
    "retrieve_quote",
    "complete_unit",
    "cite_passage",
    "verify_source",
)


def load_questions(tradition: str, kind: str) -> list[dict]:
    """Questions for one tradition and language, population file then familiarity file."""
    rows = []
    for sample in ("population", "familiarity"):
        folder = OUT.parent / tradition / kind / sample
        files = [folder / "questions.jsonl"]
        files += sorted(folder.glob("prompt-*/questions.jsonl"))
        for path in files:
            if not path.exists():
                continue
            rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return rows


def passage_lines(rows: list[dict]) -> tuple[list[str], str]:
    """One line per passage, population first. Size is the question-file row count."""
    picked: dict[tuple[str, str], None] = {}
    for row in rows:
        # cite_passage, not retrieve_quote: a Sri Guru Granth Sahib retrieve row asks for its Ang's
        # edge pankti, not the drawn passage. Every passage has a cite row with its own citation.
        if row["task"] != "cite_passage":
            continue
        source = row.get("source") or row
        condition = source.get("condition") or row.get("condition")
        if condition not in {"native_answer", "en_ask_en_answer", "ask_english", "ask_native"}:
            continue
        sample = source.get("sample") or row.get("sample")
        citation = source.get("citation") or row.get("citation")
        picked.setdefault((sample, citation), None)
    order = {"population": 0, "familiarity": 1}
    lines = [
        f"- `{cit}` ({sample})"
        for sample, cit in sorted(picked, key=lambda key: (order.get(key[0], 9), key[1]))
    ]
    n_pop = sum(1 for sample, _ in picked if sample == "population")
    n_fam = sum(1 for sample, _ in picked if sample == "familiarity")
    size = (
        f"{len(rows)} questions. Population sample: {n_pop} passages. "
        f"Familiarity panel: {n_fam} passages. Report those two separately."
    )
    return lines or ["- question file not built yet"], size


def main() -> None:
    religions = [
        christianity(),
        judaism(),
        islam(),
        sikhism(),
    ]
    write_index(religions)
    for folder, body in religions:
        path = OUT / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / "README.md").write_text(body, encoding="utf-8")
        print(folder)


def write_index(religions: list[tuple[str, str]]) -> None:
    lines = [
        "# Review pack",
        "",
        "Each tradition has two samples. Report them separately.",
        "The population sample is 30 passages, drawn uniformly (seed 20261030),",
        "with the pre-registered familiar citations removed first.",
        "The familiarity panel is every citation in `well_known.yaml` for that edition.",
        "Christianity is one set of 30. The NRSV is the English edition. Hebrew Bible",
        "verses of that set are the Masoretic text, and New Testament verses are the",
        "Greek New Testament (Scrivener 1894). Each native passage is an English prompt",
        "and a native-language prompt. Judaism is the same 30 in Aramaic (both prompts)",
        "and in English. Islam is the Uthmani Qur'an in both prompt languages, plus the",
        "Saheeh International English edition. Sikhism and Buddhism are the native edition",
        "only, and Buddhism's Pali is asked with the English prompt only (#113). Hinduism is",
        "Sanskrit and Besant's English. Christianity, Judaism, Islam, and Hinduism are 360",
        "population questions. Sikhism is 240 and Buddhism is 120.",
        "The familiarity panels are different lengths on purpose (Islam 8, Christianity 4,",
        "Hinduism 4, Buddhism 4, Sikhism 3, Judaism 1). Compare traditions on the population sample of 30.",
        "Do not pad or cut the familiar lists to make those counts match.",
        "The English edition can differ from the native edition.",
        "This folder is for a person to check the edition, the citation, and the",
        "wording of the prompts before a run.",
        "",
        "Checked against `texts/raw`: the Bhagavad Gita, the Dhammapada, and Sikhism",
        "(`sggs_shabados.json`) are in the corpus. The Gita and the Dhammapada review",
        "pages were written by `build_remaining.py` and are left in place.",
        "",
        "Christianity is the NRSV. The full `nrsv.json` is gitignored. The drawn verses",
        "are in `christianity/english/`. The Protestant folder's KJV list chose the",
        "citations; the scored wording is NRSV. Other Christian payloads are not",
        "separate religions here.",
        "",
        "Native-language lines are drafts. A speaker of that language should correct them",
        "before they are used as the scored prompt.",
        "",
        "| Folder | In raw data? | Edition in the question | English edition, if different |",
        "|---|---|---|---|",
        "| `01-christianity` | questions in `christianity/english/`; full `nrsv.json` is gitignored | NRSV | same |",
        "| `02-judaism` | yes | Talmud Bavli, William Davidson Aramaic | William Davidson English |",
        "| `03-islam` | yes | the Uthmani Qur'an (catalogue version `Uthmani (QUL)`) | Saheeh International, same citations |",
        "| `04-sikhism` | yes | Sri Guru Granth Sahib, Shabad OS (SGPC Shabadaarth) | no English SGGS in this corpus |",
        "| `05-hinduism` | yes | Bhagavad Gita, Stotra Samhita (Gita Press text) | Annie Besant (1922) |",
        "| `06-buddhism` | yes | Dhammapada, Chaṭṭha Saṅgāyana (VRI) | no English Dhammapada in this corpus |",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def christianity() -> tuple[str, str]:
    rows, size = passage_lines(load_questions("christianity", "english"))
    size += (
        " Original language of that same population sample, not a second draw: "
        "21 Masoretic passages (168 questions) and 9 Greek New Testament passages (72 questions)."
    )
    rows.append("")
    rows.append(
        "The verse inventory for the draw is the Protestant list in `kjv.json`. "
        "The wording in `christianity/english/` is NRSV. Do not check these against `kjv.json`. "
        "The same 30 citations are in `christianity/native/masoretic/` when the verse is from the "
        "Hebrew Bible (Westminster Leningrad Codex; Daniel 2 is Aramaic) and in "
        "`christianity/native/greek/` when it is from the New Testament (Scrivener 1894). "
        "That is one set, split by original language, and each of those files has an "
        "English prompt and a native-language prompt. The licensed Greek Orthodox TLG "
        "files are not in the repo, so these verses are not the Septuagint."
    )
    return "01-christianity", page(
        title="Christianity",
        version=edition_name("NRSV"),
        english_version="NRSV (same edition; the text is already English)",
        language="English",
        native_prompts=None,
        rows=rows,
        source="texts/raw/Protestant Christian/nrsv.json (gitignored; not in the public repo)",
        size=size,
        english_prompts=EN,
    )


def islam() -> tuple[str, str]:
    rows, size = passage_lines(load_questions("islam", "native"))
    name = edition_name(QURAN_VERSION)
    return "03-islam", page(
        title="Islam",
        version=name,
        english_version="Saheeh International, same citations, in islam/english/",
        language="Arabic",
        native_prompts=QURAN_AR,
        rows=rows,
        source=QURAN_FILE.relative_to(RAW.parent.parent).as_posix(),
        size=size,
        english_prompts=EN,
        english_suffix=f"Answer in the language of {name}.",
        native_note="Signed off by a native Arabic speaker (the owner), 2026-11-01. See METHODOLOGY.md.",
    )


def judaism() -> tuple[str, str]:
    rows, size = passage_lines(load_questions("judaism", "native") + load_questions("judaism", "english"))
    rows.append("- The Aramaic and English Davidson files are different wording (CC-BY-NC).")
    native = {
        "retrieve_quote": "מהו נוסח {citation} בתלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית? ענה בנוסח אותה מהדורה בלבד.",
        "complete_unit": "השלם ציטוט זה מהתלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית: \"{head}\" ענה במילים הנותרות בלבד.",
        "cite_passage": "היכן בתלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית, נמצא הטקסט הזה? \"{text}\" ענה בציון המקום בלבד.",
        "verify_source": "האם הטקסט הבא מן התלמוד הבבלי, מהדורת ויליאם דייווידסון הארמית? \"{text}\" ענה כן או לא.",
    }
    name = edition_name("William Davidson Edition - Aramaic")
    return "02-judaism", page(
        title="Judaism",
        version=name,
        english_version=f"{edition_name('William Davidson Edition - English')} (same citations, a separate file)",
        language="Aramaic / Hebrew",
        native_prompts=native,
        rows=rows,
        source="texts/raw/Judaism/Talmud Bavli/",
        size=size,
        english_prompts=EN,
        english_suffix=f"Answer in the language of {name}.",
    )


def sikhism() -> tuple[str, str]:
    rows, size = passage_lines(load_questions("sikhism", "native"))
    rows.append("- cite_passage asks for and expects the Ang only: line numbering within an Ang is not standardised (#135).")
    rows.append("- retrieve_quote asks for the first or last pankti of the passage's Ang, for the same reason.")
    rows.append("- A familiarity passage's retrieve_quote asks for it by name (`asked_as` in well_known.yaml), e.g. the Mool Mantar.")
    native = {
        "retrieve_quote": "ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਦੇ {ang} ਦੀ {edge} ਪੰਕਤੀ ਦਾ ਪਾਠ ਦੱਸੋ। ਸਿਰਫ਼ ਉਸੇ ਅਡੀਸ਼ਨ ਦਾ ਪਾਠ ਲਿਖੋ।",
        "complete_unit": "ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਵਿਚੋਂ ਇਹ ਟੋਟਾ ਪੂਰਾ ਕਰੋ: \"{head}\" ਸਿਰਫ਼ ਬਾਕੀ ਸ਼ਬਦ ਲਿਖੋ।",
        "cite_passage": "ਇਹ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਵਿਚ ਕਿੱਥੇ ਹੈ? \"{text}\" ਸਿਰਫ਼ ਅੰਗ (ਪੰਨਾ) ਲਿਖੋ।",
        "verify_source": "ਕੀ ਇਹ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਵਿਚੋਂ ਹੈ? \"{text}\" ਹਾਂ ਜਾਂ ਨਹੀਂ।",
    }
    name = edition_name("Shabad OS (SGPC Shabadaarth)")
    return "04-sikhism", page(
        title="Sikhism",
        version=name,
        english_version="none in this corpus",
        language="Gurmukhi (Sant Bhasha)",
        native_prompts=native,
        rows=rows,
        source="texts/raw/Sikhism/sggs_shabados.json",
        size=size,
        english_prompts=SGGS_EN,
        english_suffix=f"Answer in the language of {name}.",
    )


def missing(folder: str, title: str, work: str) -> tuple[str, str]:
    body = "\n".join([
        f"# {title}",
        "",
        f"**Not in `texts/raw`.** There is no file for {work} in this checkout.",
        "No passages and no bilingual prompts are written here, so a reviewer is not",
        "asked to approve a citation or a translation that was not read from a file.",
        "",
        "When a licensed edition is added under `texts/raw/`, name that edition here,",
        "including an English translation edition if it is a different book, and list",
        "a population sample and a separate familiarity panel.",
        "",
    ])
    return folder, body


def page(
    *, title, version, english_version, language, native_prompts, rows, source, size,
    english_prompts=None, english_suffix=None, native_note=None,
) -> str:
    """One review page. ``english_prompts`` / ``english_suffix`` are the live build_questions
    templates and the second line of each English prompt; a page that does not pass them prints the
    shared English templates. ``native_note`` replaces the "draft" label once a speaker has signed off."""
    english = english_prompts or EN
    out = [
        f"# {title}",
        "",
        f"- Canonical edition named in the question: **{version}**",
        f"- English edition: **{english_version}**",
        f"- Language: {language}",
        f"- Raw file: `{source}`",
        f"- Tasks: {', '.join(TASKS)}",
        f"- Size: {size}",
        "",
        "## Passages to check",
        "",
        *rows,
        "",
        "These citations are the question file. Population and familiarity are separate samples.",
        "",
        "## Prompts in English",
        "",
    ]
    for task, tmpl in english.items():
        out.append(
            f"- `{task}`: "
            + tmpl.format(citation="{citation}", version=version, head="{head}", text="{text}", example="{example}", ang="{ang}", edge="{edge}")
        )
    if english_suffix:
        out.extend(["", f"Each English prompt has a second line: `{english_suffix}`"])
    out.append("")
    if native_prompts is None:
        out.append("This edition is English, so there is one answer language.")
    else:
        out.extend(["## Prompts in the text's language" + ("" if native_note else " (draft)"), ""])
        out.append(native_note or "A native speaker should correct these before a run.")
        out.append("")
        for task, tmpl in native_prompts.items():
            out.append(f"- `{task}`: {tmpl}")
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    main()
