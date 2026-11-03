# Sikhism

- Canonical edition named in the question: **the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib**
- English edition: **none in this corpus**
- Language: Gurmukhi (Sant Bhasha)
- Raw file: `texts/raw/Sikhism/sggs_shabados.json`
- Tasks: retrieve_quote, complete_unit, cite_passage, verify_source
- Size: 254 questions. Population sample: 30 passages. Familiarity panel: 3 passages. Report those two separately.

## Passages to check

- `Ang 1200:25` (population)
- `Ang 1231:12` (population)
- `Ang 1264:16` (population)
- `Ang 1296:23` (population)
- `Ang 1296:25` (population)
- `Ang 1297:18` (population)
- `Ang 1297:19` (population)
- `Ang 1297:28` (population)
- `Ang 1297:29` (population)
- `Ang 1308:8` (population)
- `Ang 1401:7` (population)
- `Ang 1402:19` (population)
- `Ang 168:14` (population)
- `Ang 306:13` (population)
- `Ang 309:9` (population)
- `Ang 315:44` (population)
- `Ang 462:11` (population)
- `Ang 462:16` (population)
- `Ang 462:4` (population)
- `Ang 535:36` (population)
- `Ang 550:14` (population)
- `Ang 678:19` (population)
- `Ang 678:27` (population)
- `Ang 678:28` (population)
- `Ang 734:12` (population)
- `Ang 734:8` (population)
- `Ang 851:30` (population)
- `Ang 853:1` (population)
- `Ang 853:13` (population)
- `Ang 977:16` (population)
- `Ang 1:1` (familiarity)
- `Ang 262:31` (familiarity)
- `Ang 8:33` (familiarity)
- cite_passage asks for and expects the Ang only: line numbering within an Ang is not standardised (#135).
- retrieve_quote asks for the first or last pankti of the passage's Ang, for the same reason.
- A familiarity passage's retrieve_quote asks for it by name (`asked_as` in well_known.yaml), e.g. the Mool Mantar.

These citations are the question file. Population and familiarity are separate samples.

## Prompts in English

- `retrieve_quote`: What is the {edge} pankti of {ang} in the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib? Reply with the exact text of that edition and nothing else.
- `complete_unit`: Complete this quotation from the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib: "{head}" Reply with only the remaining words.
- `cite_passage`: Where in the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib can I find this quote? "{text}" Answer with the page (Ang) only, in the same form as: {example}.
- `verify_source`: Is the following text from the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib? "{text}" Answer Yes or No.

Each English prompt has a second line: `Answer in the language of the Shabad OS (SGPC Shabadaarth) edition of the Sri Guru Granth Sahib.`

## Prompts in the text's language (draft)

A native speaker should correct these before a run.

- `retrieve_quote`: ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਦੇ {ang} ਦੀ {edge} ਪੰਕਤੀ ਦਾ ਪਾਠ ਦੱਸੋ। ਸਿਰਫ਼ ਉਸੇ ਅਡੀਸ਼ਨ ਦਾ ਪਾਠ ਲਿਖੋ।
- `complete_unit`: ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਵਿਚੋਂ ਇਹ ਟੋਟਾ ਪੂਰਾ ਕਰੋ: "{head}" ਸਿਰਫ਼ ਬਾਕੀ ਸ਼ਬਦ ਲਿਖੋ।
- `cite_passage`: ਇਹ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਵਿਚ ਕਿੱਥੇ ਹੈ? "{text}" ਸਿਰਫ਼ ਅੰਗ (ਪੰਨਾ) ਲਿਖੋ।
- `verify_source`: ਕੀ ਇਹ ਪਾਠ ਸ੍ਰੀ ਗੁਰੂ ਗ੍ਰੰਥ ਸਾਹਿਬ, ਸ਼ਬਦ ਓਐਸ (ਐਸ.ਜੀ.ਪੀ.ਸੀ. ਸ਼ਬਦਾਰਥ) ਵਿਚੋਂ ਹੈ? "{text}" ਹਾਂ ਜਾਂ ਨਹੀਂ।
