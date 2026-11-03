# Items for test

This folder is the test set for the six traditions. The population sample is 30 passages. A native edition is asked twice, an English prompt and a prompt in the text's language, except the Pali Dhammapada, which is asked with the English prompt only (#113). An English edition, when this corpus has one, is a third file. Sampling is in `METHODOLOGY.md`.

| Tradition | Native text | English prompt | Native prompt | English text | Missing |
|---|---|---|---|---|---|
| Christianity | Yes | Yes | Yes | Yes | The Book of Mormon and the encyclicals are their own categories, 30 English passages each, not part of this row |
| Judaism | Yes | Yes | Yes | Yes | — |
| Islam | Yes | Yes | Yes | Yes | — |
| Sikhism | Yes | Yes | Yes | No | English text |
| Hinduism | Yes | Yes | Yes | Yes | — |
| Buddhism | Yes | Yes | No | No | English text. No Pali-language prompt: Pali has no native speakers (#113) |

`*/familiarity/` is the pre-registered list and is not in the run (Christianity 4, Judaism 1, Islam 8, Sikhism 3, Hinduism 4, Buddhism 4). `cost.py` writes `COST.md`. `models/openrouter.yaml` is the 16-model run and `models/openrouter-subset.yaml` is 7 of those models. `review/` is check pages only.

`join_run.py --test` collects the first 3 passages of each tradition; the same command without `--test` adds the rest to those answer files. It collects one model at a time. It creates `runs/<model>/base/` plus the same folders as the question file (`christianity/english/population/`, `sikhism/native/population/`, and the rest) only when that file is collected. `base` is temperature 0 and search off. A later English Guru Granth Sahib is a new folder under that model and does not replace the Gurmukhi answers. Finished dated runs are in `runs/archive/`. `--run-dir runs/<name>` writes a whole new run under `runs/<name>/<model>/base/` instead, with the usage card at `runs/<name>/<model>/model.json` (prices copied from the committed card); it refuses `runs` itself and any path inside a committed model folder, and the viewer shows the folder as its own panel run `<name>`. Standings key these panel runs on the bare model id, so an in-flight rerun replaces each model's row (newest wins) and becomes the viewer's home default; name the folder `exp-…` to keep it out of both.

## Before a run

No pull request is open. These issues are still open and the work is not already on `main`.

| Issue | Still to do | Blocks |
|---|---|---|
| #37 | Septuagint is not in the repo. The test set has a Masoretic excerpt and Scrivener 1894, not a full Tanakh and not Nestle-Aland | The catalogue copies of those witnesses. The excerpt already in this folder can run |
| #43 | Qur'an, Latter-day Saint, and NRSV license terms | Releasing questions, not collecting them |

Already done, so not on that list: #60 (hamza-alef `ءَا` ↔ alef-madda `آ` is credited, and a verse number glued to the last word is stripped; `ىٰ` stays the optional long ā, because folding it to ya merges different words), #50's scoring half (`normalize()` keeps Gurmukhi, Devanagari, and Pali vowel signs; the Guru Granth Sahib text landed in #51), #63 (Dhammapada, closed), #64 (Gita text landed in #66; the issue is still open and should be closed), #52 (main Arabic fold, closed). #54's harness merged in #59; the live search run has not been done, and it is a separate experiment.

Safe to collect now: Christianity (NRSV, Masoretic, Greek), Judaism (Aramaic and English), Islam, Sikhism, the Sanskrit and English Gita, and the Pali Dhammapada. The Christian supplemental set waits until after the main 30.

## Passage files

Each `passages.json` is the scored wording for that tradition and language.
A verify question can quote some other tradition; those quotes are not copied here.

| Field | Meaning |
|---|---|
| `tradition` | One of the six: Christianity, Judaism, Islam, Sikhism, Hinduism, Buddhism. The Christian supplemental files name the Book of Mormon and the encyclical instead |
| `citation` | The passage, in the form the scorer expects |
| `sample` | `population` (the headline 30), `familiarity` (the pre-registered list), or `supplemental` (the Christian modern set, not in the run) |
| `version` | The edition that question asks for. An English file names the English edition |
| `run` | On the file, not each passage. True only in `population/` |
| `text.native` | The native-edition wording. Omitted when the edition is already English |
| `text.english` | The English wording. Omitted when this corpus has no English edition |

`notice` holds the NRSV copyright line and the Talmud CC-BY-NC line.

## Counts

The run is the `population/` folder. `passages.json` there is the 30 passages, and `run` is true. The `familiarity/` folder is not collected with the run (Christianity 4, Judaism 1, Islam 8, Sikhism 3, Hinduism 4, Buddhism 4).

A native edition is the same passages asked twice: `prompt-english/` and `prompt-native/`. Buddhism has `prompt-english/` only. Christianity's native text is not a second draw and not two full Bibles. Hebrew Bible verses are in `native/masoretic/` and New Testament verses are in `native/greek/`. Each of those has `population/` (the same 30, split) and `familiarity/` (Genesis 1:1 and Psalms 23:1; John 3:16 and Matthew 6:9). The NRSV file is the English edition. `modern/english/` is the supplemental Book of Mormon and encyclical set, not a population or familiarity sample.

| Tradition | Questions in the run | Population | Familiarity | File |
|---|---|---|---|---|
| Christianity (NRSV, then original language) | 120 + 240 | 30 | 4, not in the run | `christianity/english/population/`, `native/masoretic/`, `native/greek/` |
| Judaism (Aramaic, two prompts, then English) | 120 + 120 + 120 | 30 | 1, not in the run | `judaism/native/population/prompt-english/`, `prompt-native/`, `judaism/english/population/` |
| Islam (Arabic, two prompts, then Saheeh International) | 120 + 120 + 120 | 30 | 8, not in the run | `islam/native/population/`, `islam/english/population/` |
| Sikhism (Gurmukhi, two prompts) | 240 | 30 | 3, not in the run | `sikhism/native/population/prompt-english/`, `prompt-native/` |
| Hinduism (Sanskrit, two prompts, then English) | 120 + 120 + 120 | 30 | 4, not in the run | `hinduism/native/population/`, `hinduism/english/population/` |
| Buddhism (Pali, English prompt only) | 120 | 30 | 4, not in the run | `buddhism/native/population/prompt-english/` |

Report the population sample and the familiarity panel separately. The reason
is in `METHODOLOGY.md`.

## The four prompts

Each passage is asked once as each task. `expected` is what `score_answer` reads.

| Task | The model is asked to | `expected` |
|---|---|---|
| `retrieve_quote` | Give the exact text of a citation | `text`: the whole passage |
| `complete_unit` | Finish a quotation after the first half of its words | `text`: the remaining words |
| `cite_passage` | Name where a quotation appears | `citation`: the citation only |
| `verify_source` | Say whether a quotation is from the named edition | `answer`: `yes` or `no` |

A cite prompt shows one other citation from the same edition, so the answer has a form to follow (`in the same form as: …`). Within each sample, half of the verify prompts quote a real passage from a different work in the same language and expect `no`. Where this corpus has only one work in that language, the donor is another tradition, and the script differs. The rule is in `METHODOLOGY.md`.

Guru Granth Sahib citations are asked and scored at the Ang (page), because line numbering within an Ang is not standardised (issue #135). The Sikh cite prompt asks for the page (Ang) and expects `Ang 306`; `ਅੰਗ ੩੦੬`, `Page 306` and a line the model adds (`Ang 306:9`) all count. A qualifier beside the Ang (`line 9`, `Mehl 5`, `ਮਹਲਾ ੫`, a raag) is not a second citation; a second Ang is. `retrieve_quote` names no line either: it asks for the first or the last pankti of the Ang ("What is the first pankti of Ang 306 in …?"), the two panktis an Ang identifies without a line number. A heading at that edge (`ਪਉੜੀ`, `ਗਉੜੀ ਮਹਲਾ ੫`) is never asked for, nor a record holding several tuks, which can cross the page break (Shabad OS's last record on Ang 315 ends with a tuk BaniDB prints on Ang 316); the row asks for the other edge instead. An Ang has two edges, so it asks at most two retrieve questions: the population draw has four passages on Ang 1297 and three on Ang 462 and Ang 678, and those extra passages get no `retrieve_quote` row. Neither edge of Ang 315 can be asked, so its passage gets none either (25 population retrieve rows per prompt arm, not 30). Their other three tasks are unchanged. The three familiarity passages are asked for by name instead (`asked_as` in `well_known.yaml`): "What is the Mool Mantar in …?", the first line of the closing salok of Japji Sahib, the rahao line of Sukhmani Sahib.

```
Where in the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib can I find this quote? "ਪਰਾਈ ਜੋ ਨਿੰਦਾ ਚੁਗਲੀ ਨੋ ਵੇਮੁਖੁ ਕਰਿ ਕੈ ਭੇਜਿਆ ਓਥੈ ਭੀ ਮੁਹੁ ਕਾਲਾ ਦੁਹਾ ਵੇਮੁਖਾ ਦਾ ਕਰਾਇਆ" Answer with the page (Ang) only, in the same form as: Ang 1231.
Answer in the language of the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib.
```

`expected`: `{"citation": "Ang 306"}`

## How a prompt is built

The edition and its work are named inside the prompt. The model call has no language field. Every set is rebuilt by one command, in `METHODOLOGY.md`.

**English edition, already English** (the NRSV file). One line. It names that edition and asks for the answer in English.

The same 30 citations are also in `christianity/native/masoretic/` (Hebrew Bible, including Aramaic Daniel 2) and `christianity/native/greek/` (New Testament). Those use the two-call native form below. Together they are one set of 30, not a second draw.

```
What is the text of Exodus 28:43 in the New Revised Standard Version (NRSV)? Reply with the exact text of that edition and nothing else.
```

**Native edition, two calls** (Islam, Sikhism, and the Aramaic half of Judaism). The same question is not stacked in one prompt. `prompt-english/` is the English question plus one line saying which language to answer in. `prompt-native/` is only the question in the text's language. Those native lines are drafts for a native speaker.

```
What is the text of Ang 306:13 in the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib? Reply with the exact text of that edition and nothing else.
Answer in the language of the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib.
```

```
Ang 306:13 ਦਾ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ ਵਿਚੋਂ ਦੱਸੋ। ਸਿਰਫ਼ ਉਸੇ ਅਡੀਸ਼ਨ ਦਾ ਪਾਠ ਲਿਖੋ।
```

**English edition of a non-English work** (Judaism). One English line, the same shape as Christianity. It names the English edition. It does not repeat the question in Hebrew, and it does not warn that the translation can differ.

Judaism's native edition is one text, the Aramaic Davidson edition. Hebrew and Aramaic are mixed in that text; they are not two scored languages. The English Davidson edition is a second scored answer. `complete_unit` cuts each edition at half of its own words (`split_quote` in `generate.py`, the same cut the main generator uses). The two remainders are the same fraction of each wording. They are not the same point in the passage, because the translation is not the same length.

Islam's English edition is Saheeh International, the same 30 citations, one English call. Sikhism and Buddhism do not have this third prompt. This corpus has no English Guru Granth Sahib and no English Dhammapada. Hinduism asks the same 30 verses in Besant's English as well as in Sanskrit.

## Run the panel

The run joins the population question files in `RUNNING.md`. `review/` has check pages and does not keep a second copy of the questions.

List A is `models/openrouter.yaml` (16 models), and that is the run. List B is `models/openrouter-subset.yaml` (7 models). Both go through OpenRouter with temperature 0. One `OPENROUTER_API_KEY` covers every model. No Anthropic, OpenAI, or Gemini key. The reference file `configs/models.openrouter.yaml` is the old three-model run and is not this panel.

Search is the `search` key at the top of the panel file. It is `false`, which strips `web_search` from every model, so nothing in this run uses search. Set it to `true` to turn search on for every model, or `both` to run each model twice (the plain id, and `<id>-search`) where OpenRouter can forward that provider's own search. Google, DeepSeek, Moonshot, Reflection, and Qwen are not forwarded, so `true` fails on this panel and `both` leaves those models search-off.

OpenRouter has no language field. The prompt already names the edition and the answer language. One collect writes every model in the chosen file into the same answers file; each row is marked with its `model_id`.

`COST.md` prices List A. Christianity, Judaism, Islam, and Hinduism are 360 population questions each (native two prompts, plus an English edition). Sikhism is 240 (native only). Buddhism is 120 (Pali, English prompt only). Familiarity lists and `christianity/modern/` are not in that total. Refresh with `python items/for-test/cost.py`.

`complete_unit` scores the remaining words of that passage. An answer that then continues into later verses still counts as correct, because the remainder is contained in the answer. A cite task that asks for a passage from the wrong edition is not in this run.

How to run, pause, and resume is in `RUNNING.md` at the top of the repo. A pilot collects `christianity/english/population/questions.jsonl` with `--model haiku` into its own answers file. Finished answers are kept if you stop midway.
