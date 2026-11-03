# Methodology

This is the sampling design for the test set in this folder. The headline
estimate and the familiarity check are different questions. Report them
separately. Do not average them into one accuracy.

## What is being estimated

The population sample estimates how a model handles a typical passage of a
work. The familiarity panel estimates how it handles lines that are widely
quoted and therefore likely to have been seen in training. Those lines are not
a random sample of the work. Mixing them into the headline would favor
traditions whose famous passages are over-represented in training data.

## Population sample

Thirty passages per tradition. The draw is uniform, seed `20261030`, from
passages of at least 16 words. Every citation in `well_known.yaml` is removed
before the draw, so a famous line cannot also occupy a population slot.

The full NRSV file is gitignored. The draw uses the Protestant verse list in
`kjv.json` to choose citations. The scored wording is the NRSV text of those
citations, in `christianity/english/population/questions.jsonl`.

## Familiarity panel

The panel is the whole list in `well_known.yaml` for that edition. It is not a
quarter of the draw, and it is not cut or padded so the traditions match. The
population draw is conditional on this pre-registered list: the familiar citations
are removed from the pool before the seeded draw, so changing the list re-draws the
population sample (seed fixed at 20261030).

| Tradition | Familiar passages |
|---|---|
| Christianity | 4 |
| Judaism | 1 |
| Islam | 8 |
| Sikhism | 3 |
| Hinduism | 4 |
| Buddhism | 4 |

Compare traditions on the population sample of 30. Report the familiarity
panel with its own count.

## Questions

Each passage is asked as four tasks: `retrieve_quote`, `complete_unit`,
`cite_passage`, and `verify_source`.

Christianity is one set of 30. The English edition is the NRSV. The same
citations are also asked in their original language: the Masoretic text
(Westminster Leningrad Codex) for Hebrew Bible verses, including the Aramaic
of Daniel 2, and the Greek New Testament (Scrivener 1894) for New Testament
verses. That is not a second sample of 30, and the Old Testament verses are
not also asked from the Septuagint. The licensed Greek Orthodox TLG files
are still not in the repo.

The Masoretic wording comes from the Open Scriptures Hebrew Bible copy of the
Westminster Leningrad Codex. That file tags every word for grammar and
carries its editors' notes. Four rules turn a verse into the text a reader
sees (issue #85, `wlc_text` in `review/build_christian_original.py`):

1. The "/" between the parts of a word is deleted: `וְ/הָיוּ֩` is `וְהָיוּ֩`.
2. Where the written form (Ketiv) and the read form (Qere) differ, the verse
   has the read form, with its vowels. A word read but not written is added;
   a word written but not read is left out. A printed Tanakh is read this
   way, and on the 2026-11-02 run more answers gave the Qere than the Ketiv.
3. Every other note is dropped. Those are the editors' remarks, in English,
   such as "BHS has been faithful to the Leningrad Codex…" inside Isaiah 49:7.
4. The paragraph markers ס and פ after a verse are dropped.

Maqaf, sof pasuq, paseq, the vowels and the cantillation marks stay as they
are. The build stops if a verse still has a Latin letter or a "/". Before
#85 the text kept all four, so a model that wrote the verse correctly could
not match it.

Judaism's Aramaic edition and its English edition are the same 30 citations.
The Aramaic edition is two calls: an English prompt and a native-language
prompt. The English edition is one call. Islam is the same shape: the Uthmani
text as two calls, and Saheeh International as one English call, on the same
citations. Sikhism is the native edition only, also as two calls. This corpus
has no English Guru Granth Sahib. Buddhism's Pali Dhammapada is one call, the
English prompt only. Romanized Pali is a liturgical language with no native
speakers, so a Pali-language prompt would not measure what the other native
prompts measure (owner decision, issue #113).

The prompt names the work as well as the edition: "the 2013 edition of the
Book of Mormon", "the William Davidson Aramaic edition of the Babylonian
Talmud", "the Vatican English text of the encyclical Fides et Ratio (John Paul
II, 1998-09-14)". A bare catalogue version ("Is the following text from 2013
edition?") left the model guessing which work was meant, and that cost 16-28
points on `verify_source` for the traditions it hit (issue #90). The names are
`_EDITION_DISPLAY` in `review/build_questions.py`; a new edition without one
stops the build. The Sanskrit prompts name the Gita in their own language,
as the Hebrew, Punjabi and Arabic ones already did. A native edition is not asked in both languages
inside one prompt. The native-language lines are drafts for a native speaker.
The model call has no language field. OpenRouter does not add one.

The Qur'an's English prompts name the edition "the Uthmani Qur'an" and the Arabic
prompts "القرآن الكريم بالرسم العثماني" (no "QUL"); the catalogue `version`
("Uthmani (QUL)") is unchanged in each question's source metadata. The Arabic
wording was signed off by the Islam representative, a native speaker: "رسم" is
orthography, "طبعة" a print run, so "طبعة عثماني" was wrong; "النص" rather than
"الاقتباس" for revelation; "رقم السورة والآية" rather than "الاستشهاد" (which means
martyrdom / evidentiary citation); and a closing "فقط" because Arabic-prompted
models tend to open with a preamble (بسم الله…, قال تعالى:) or a clause before the
verdict, which the leading-stance parser scores as refused — a deliberate, small
asymmetry versus the English "Answer Yes or No". The verify `no` donors are hadith
(content negatives), so naming the orthography does not turn verify into a spelling
test.

`complete_unit` expects the remaining words of the passage. Continuing into
later verses is still correct: the headline treats the answer as correct when
those remaining words are contained in it. A `cite_passage` item that should
be declined because the quotation is from another edition is not in this run.

Guru Granth Sahib citations are asked and scored at the Ang (page), because
line numbering within an Ang is not standardised (issue #135). A line, Mehl
or raag the model adds beside the Ang is ignored; a second Ang is a hedge.
`retrieve_quote` asks for the first or last pankti of the Ang, never a
heading or a multi-tuk record, for the same reason. An Ang asks at most two such questions, so
a passage drawn from an Ang that already has two gets no retrieve row.
A familiarity passage is asked for by its name (the Mool Mantar).

Within each sample, half of the `verify_source` questions quote a real passage
from a different work and expect `no`. The donor is the same language as the
edition in the question, and the nearest other work this corpus holds. A
familiarity list of one passage stays `yes`, because half of one rounds to zero.
`true_tradition` is a scorer label. The prompt only asks yes or no.

| Edition being asked | Donor for `no` | Why |
|---|---|---|
| Aramaic Talmud | Masoretic text | Hebrew or Aramaic that is not the Talmud. No Midrash is in the corpus |
| English Talmud | NRSV, Hebrew Bible verses only | The English Tanakh this corpus holds. New Testament verses are not the donor. No English Midrash is in the corpus |
| NRSV | Book of Mormon, 2013 edition | Another English scripture |
| Masoretic text | Aramaic Talmud | The other Hebrew-Aramaic work |
| Qur'an | A hadith from the six canonical collections (Bukhari, Muslim, Abu Dawud, Tirmidhi, Nasa'i, Ibn Majah) | Same script and same tradition as the Qur'an, a different work. The question is a real "Qur'an or hadith?" judgement, not an alphabet test (issue #75) |
| Greek New Testament, Guru Granth Sahib, Sanskrit Gita, Pali Dhammapada | Another tradition's native-language passage in a different script, never an English edition | No second work in that language. The script differs, so these `no` items are easier |
| English Gita (Besant) | Another tradition's English edition | The English works this corpus holds |
| Book of Mormon / encyclicals | The other one of the pair | The two modern supplemental categories |

The table is `_donor_pool` in `review/build_questions.py`. Every set's
passages, population and familiarity, are one pool, so a donor can come from
any set the table allows. Each `no` row draws from its own RNG (seed
20261030, tradition, edition, condition, sample, citation), so no other set
or build order can move it. A set quotes each donor once (issue #116): when
two of its rows draw the same donor, the first in citation order keeps it and
the other draws again from its own RNG, skipping every donor the set's first
draws took, so only the repeated row changes.

A `no` row is its own prompt template filled with the donor passage
(`prompt_for` in `build_questions.py`). The donor is never pasted between the
prompt's quotation marks, because a passage can contain quotation marks of its
own. Every prompt quotes exactly one passage. Inside an English prompt, a
passage's own quotation marks become `'`; the expected answer keeps the
original text. A passage that would put a straight `"` inside a prompt stops
the build.

The hadith donor is chosen by the script of the quoted passage, not by the
tradition: an Arabic passage gets a hadith, so an English Qur'an edition, if
one is added, would get an English donor. Four rules keep the hadith item a
fair "Qur'an or hadith?" question:

- **Sayings only** (owner-approved matn-only, quote-bounded). The quoted text
  is the span sunnah.com puts in quotation marks right after a salawat
  ("صلى الله عليه وسلم"), optionally with a speech verb between ("قَالَ",
  "يَقُولُ", "فَقَالَ", "أَنَّهُ قَالَ"), up to its closing mark. That is the
  Prophet's own words. The narrator chain (isnad) before it, and anything after
  the closing mark (a narrator's remark, a second chain, the compiler's
  commentary), are never quoted. sunnah.com's quotation marks and the
  right-to-left marks around them are not copied, so the prompt keeps exactly
  one pair of quotation marks. A hadith is not used when there is no such span,
  or when the span:
  - has fewer than 16 words;
  - opens with a narrator chain or a reported clause (حَدَّثَنَا, أَخْبَرَنَا,
    عَنْ, وَعَنْ, أَنَّ, …), which would announce "hadith" from its first word.
    "إِنَّ" ("indeed") is a normal opening and is kept;
  - reads as a bare verdict itself ("لاَ، …"), by the scorer's own yes/no
    reader;
  - carries God's speech ("قَالَ اللَّهُ", "يَقُولُ اللَّهُ", "إِنَّ اللَّهَ … قَالَ"):
    hadith qudsi are out, and so are Qur'an citations framed that way;
  - carries a salawat. The Qur'an never does, so it would announce "hadith".

  These rules leave 4,204 sayings across the six books. A speaking-verb rule
  without the closing mark was tried first; by eye it left 11 of 38 items
  starting mid-sentence or ending in a chain.
- **No Qur'an wording** (owner-raised). Hadith quote the Qur'an, so a donor
  could make a `no` item partly true. A hadith is skipped if it contains a
  whole ayah, lies inside one, or shares 6 consecutive words with one. The
  comparison is orthography-aware (Uthmani or Imla'i spelling, the scorer's
  `fold_aware_contains`). It is conservative: a matn that merely contains a
  one-word ayah such as "وَٱلْعَصْرِ" (103:1) or "ٱلرَّحْمَٰنُ" (55:1) is also
  skipped, as is one containing the word "أَلَمْ", which folds to "الٓمٓ" (2:1).
  On the committed draw it changed 1 of the 38 `no` items: Nasa'i 3573, whose
  "عَبْدُ الرَّحْمَنِ" contains the one-word ayah 55:1. The God's-speech rule above
  already removes most hadith that quote an ayah.
- **Curated skip list** (owner check). After reading every drawn donor, two
  hadith are skipped at draw time: Sahih al-Bukhari 6784, a reply cut from a
  longer hadith that also shares 5 words with 9:102 (one under the threshold),
  and Sahih al-Bukhari 7122, God's words ("إِنَّ رَحْمَتِي تَغْلِبُ غَضَبِي")
  without a "قَالَ اللَّهُ" frame. The list is `DONOR_SKIP` in
  `build_questions.py`, with a reason for each entry. Like the Qur'an-wording
  screen, it re-draws only the rows that drew a listed hadith.
- **Seeded per row.** Each Arabic row's hadith comes from its own RNG
  (seed 20261030, condition, sample, citation), so no other row or
  tradition can move it, and rebuilding Islam alone reproduces the full build.

The Qur'an `no` donors were re-drawn twice while these rules were settled
(PR #78 rounds 2 and 3). The skip list then re-drew two rows. Nothing had been
collected from any earlier draw.

## Rebuilding the question sets

One command rebuilds every `questions.jsonl` under this folder, population
and familiarity, every tradition, and the `passages.json` beside each set
whose builder writes one:

```
uv --project pipelines run python items/for-test/review/build_questions.py
```

Run it twice and the files are byte-identical. It builds every set's `yes`
rows first, then draws every `no` row from one pool by the table above, then
writes. The other `review/build_*.py` scripts are called from it and are not
run on their own; `review/build_review.py` writes only the review pages.
`pipelines/tests/test_question_sets_rebuild.py` rebuilds every set offline
and checks it against the committed files. It also checks that each `verify_source`
prompt quotes the passage its expected answer names: its own passage for
`yes`, the donor for `no`.

Most wording is read from `texts/raw/` and `well_known.yaml`. Three texts are
fetched over the network and the build stops if a fetch fails: the NRSV
(oremus), the Westminster Leningrad Codex, and Scrivener's Greek New
Testament. The last two are fetched at a pinned commit. Each set's
`passages.json` records the source in `provenance`. The question ids are the
hash of the prompt, so any wording or donor change gives a new id.

The sets before issue #91 could not be rebuilt this way: the `no` donors had
been moved after the build by a separate pass (`retarget_verify.py`, now
removed), and two builders read each other's output files. The rebuild kept
every passage, citation and expected answer. It re-drew the `no` donors to
the table above and re-worded the prompts that did not name their work, so
every question id outside Islam changed.

## What to report

Report population accuracy on its own. Report familiarity accuracy on its own,
with the number of passages. Do not pool the two.

On `retrieve_quote` and `complete_unit`, read the two overlap scores together.
Neither one is the headline. `correct` still requires the passage, marks
included.

`token_f1` is the strict overlap. A vowel sign or a Latin accent is part of
the word, so `dhammā` is not `dhamma` and `café` is not `cafe`. Dropping a
Gurmukhi or Devanagari vowel sign, or a Pali length mark, misses that word.
Greek accents already fold, and Arabic and Hebrew vowel marks already fold,
so those pairs match on this score too.

`token_f1_base` is the same overlap after those Latin accents and Indic and
Pali vowel signs are removed. It answers a different question: did the words
change, or only the marks?

| Strict | Base | Reading |
|---|---|---|
| High | High | The same words, marks included |
| Low | High | The right words, with vowel signs or accents dropped |
| Low | Low | Different words. Treat this as a different passage |

A low strict score and a high base score is a spelling miss, not a theological
miss. A low score on both is a change of words.

Each `summary.json` and `summary.md` splits `incorrect` into `minor` (still the
passage asked for) and `major` (another passage, citation, or verdict), per task
and per text, and counts each failure kind. A near copy (token overlap 0.85 or
more) is named three ways:

| Kind | Reading |
|---|---|
| `diacritic_only` | The same words once vowel signs, accents and pointing are dropped |
| `edition_variant` | One or two words differ: another edition or spelling (`ἔθηκε` for `ἔθηκεν`) |
| `near_copy` | A close copy with more than two words changed |

All three are still incorrect.

Hinduism is the same 30 citations in both editions. The 16-word floor is
applied to Annie Besant's English, because only 16 Sanskrit verses reach 16
words. Buddhism is 30 Pali verses of at least 16 words. This corpus has no
English Dhammapada. Each has a familiarity panel in `well_known.yaml` (Gita
2:47, 4:7, 4:8, 18:66; Dhammapada 5, 103, 183, 223). Those verses are not in
the population 30, so the drawn sample was left as it is. Dhammapada 1 is
already in that draw, so it is not also on the familiarity list.

The Book of Mormon and the papal encyclicals are their own categories, not
part of the Christianity sample. Each is 30 English passages: Book of Mormon
verses from the 2013 edition, and numbered paragraphs from the Vatican
English encyclicals. They are not averaged into the NRSV estimate.

## Models

Every run is search off, with no tools, through OpenRouter. The run artifacts
record the panel fingerprint: provider, model, and temperature.

Google's 4-series currently exposes only the argon tier on OpenRouter.
OpenAI's 6.1 generation has not yet refreshed its top and bottom tiers, so
astra and luna come from gpt-6.
