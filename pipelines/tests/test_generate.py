"""Tests for the four-template, per-text question generator (Spec 26)."""

import pytest

from sacredbench.catalogue import TextMeta
from sacredbench.generate import (
    TASKS,
    DEFAULT_PER_TEXT,
    GenerateError,
    build_manifest,
    corpus_hash,
    generate,
    load_questions,
    question_set_digest,
    write_questions,
)
from sacredbench.schema import Document, Entry


def _doc(work, version="V", language="en", document_type="scripture", n=30,
         tradition=("T",), prefix=None, citation_fmt=None):
    """A document with distinct, long per-entry text (so entries clear the word-count
    gates and texts don't accidentally share passages)."""
    tok = (prefix or work).replace(" ", "")
    cfmt = citation_fmt or (lambda i: f"{work} 1:{i}")
    entries = [
        Entry("verse", cfmt(i), " ".join(f"{tok}e{i}w{j}" for j in range(18)))
        for i in range(1, n + 1)
    ]
    return Document(
        tradition=list(tradition), work=work, version=version, language=language,
        document_type=document_type, source_url=None, entries=entries,
    )


def _meta(docs, canonical=None, requested=None, target=None):
    """text_meta for ``docs``; by default every text is in-pool (canonical == its
    language) with requested_as == (work,) and target_key == its own key.
    ``canonical``/``requested``/``target`` override by key."""
    canonical = canonical or {}
    requested = requested or {}
    target = target or {}
    tm = {}
    for d in docs:
        key = (d.work, d.version, d.language)
        tm[key] = TextMeta(
            requested_as=requested.get(key, (d.work,)),
            canonical_language=canonical.get(key, d.language),
            target_key=target.get(key, key),
        )
    return tm


def _gen(docs, **kw):
    return generate(docs, _meta(docs, kw.pop("canonical", None), kw.pop("requested", None)), **kw)


# --- determinism -------------------------------------------------------------


def test_deterministic_same_seed():
    docs = [_doc("Orchards", document_type="scripture"), _doc("Roads", document_type="hadith")]
    a, _ = _gen(docs, per_text=8, seed=7)
    b, _ = _gen(docs, per_text=8, seed=7)
    assert [(q.id, q.prompt) for q in a] == [(q.id, q.prompt) for q in b]
    c, _ = _gen(docs, per_text=8, seed=8)
    assert [q.id for q in a] != [q.id for q in c]  # different seed -> different selection


def test_ids_content_derived_and_order_stable():
    docs = [_doc("Orchards"), _doc("Roads", document_type="hadith")]
    qs, _ = _gen(docs, per_text=8, seed=1)
    for q in qs:
        assert q.id.startswith(q.task + "-")
    assert qs == sorted(qs, key=lambda q: (q.task, q.id))
    assert len({q.id for q in qs}) == len(qs)


def test_questions_roundtrip(tmp_path):
    docs = [_doc("Orchards"), _doc("Roads", document_type="hadith")]
    qs, _ = _gen(docs, per_text=8)
    path = tmp_path / "questions.jsonl"
    write_questions(qs, path)
    back = load_questions(path)
    assert [q.id for q in back] == [q.id for q in qs]
    assert [q.source for q in back] == [q.source for q in qs]


def test_multi_shard_unions_traditions():
    # two shards of ONE text (same work/version/language, same document_type) with DIFFERENT
    # tradition lists: the question source carries the sorted UNION, not just one shard's.
    docs = [_doc("Shared", tradition=("Zeta",), prefix="p1"),
            _doc("Shared", tradition=("Alpha",), prefix="p2")]
    # retrieve_quote only: one text has no cross-family verify_source negative pool.
    qs, _ = _gen(docs, per_text=8, seed=1, tasks=("retrieve_quote",))
    assert qs, "expected questions from the merged shards"
    for q in qs:
        assert q.source["tradition"] == ["Alpha", "Zeta"]  # union, deterministic (sorted)


def test_multi_shard_inconsistent_document_type_fails_fast():
    # shards of one text that disagree on document_type make negative-family selection ambiguous;
    # generation must fail fast rather than depend on sort order.
    docs = [_doc("Shared", document_type="scripture", prefix="p1"),
            _doc("Shared", document_type="hadith", prefix="p2")]
    with pytest.raises(GenerateError, match="document_type"):
        _gen(docs, per_text=8, seed=1)


# --- selection: canonical-language-only --------------------------------------


def test_excluded_when_language_not_canonical():
    docs = [_doc("Qur", language="ar", document_type="scripture"),
            _doc("Hadith", language="ar", document_type="hadith"),
            _doc("TalmudEn", language="en", document_type="talmud")]
    # TalmudEn's canonical language is Hebrew -> excluded; the two Arabic texts stay.
    qs, excl = generate(
        docs,
        _meta(docs, canonical={("TalmudEn", "V", "en"): "he"}),
        per_text=8, seed=1,
    )
    selected = {(q.source["work"], q.source["version"], q.source["language"]) for q in qs}
    assert ("TalmudEn", "V", "en") not in selected
    assert excl == [{"work": "TalmudEn", "version": "V", "language": "en",
                     "reason": "language 'en' != canonical_language 'he'"}]


def test_excluded_aggregates_to_catalogue_target():
    # two documents a converter re-stamped (different works) that resolve to ONE catalogue
    # target (the encyclicals case) -> a single excluded entry naming the TARGET, not two.
    d1 = _doc("Humanae Vitae", version="VE text (A)", language="en", document_type="encyclical")
    d2 = _doc("Rerum Novarum", version="VE text (B)", language="en", document_type="encyclical")
    qur = _doc("Qur", language="ar")  # one in-pool text so generation doesn't fail on empty pool
    target = ("Papal Encyclicals", "Vatican English", "en")
    tm = {
        ("Humanae Vitae", "VE text (A)", "en"): TextMeta(("papal encyclicals",), "la", target),
        ("Rerum Novarum", "VE text (B)", "en"): TextMeta(("papal encyclicals",), "la", target),
        ("Qur", "V", "ar"): TextMeta(("Quran",), "ar", ("Qur", "V", "ar")),
    }
    _, excl = generate([d1, d2, qur], tm, per_text=4, seed=1, tasks=("retrieve_quote",))
    assert excl == [{"work": "Papal Encyclicals", "version": "Vatican English", "language": "en",
                     "reason": "language 'en' != canonical_language 'la'"}]


def test_no_in_pool_texts_fails_fast():
    docs = [_doc("KJV", language="en")]
    with pytest.raises(GenerateError, match="no in-pool texts"):
        generate(docs, _meta(docs, canonical={("KJV", "V", "en"): "he"}), per_text=8)


def test_fail_closed_on_missing_text_meta():
    docs = [_doc("Orchards")]
    with pytest.raises(GenerateError, match="no catalogue text metadata"):
        generate(docs, {}, per_text=8)  # empty text_meta


# --- per-text quota split ----------------------------------------------------


def test_default_per_text_split_evenly_over_four_tasks():
    docs = [_doc("Qur", document_type="scripture"), _doc("Hadith", document_type="hadith")]
    qs, _ = _gen(docs, per_text=DEFAULT_PER_TEXT, seed=1)
    assert len(qs) == 2 * DEFAULT_PER_TEXT
    for work in ("Qur", "Hadith"):
        per = [q for q in qs if q.source["work"] == work]
        counts = {t: sum(1 for q in per if q.task == t) for t in TASKS}
        assert counts == {t: DEFAULT_PER_TEXT // 4 for t in TASKS}  # 7 each at 28


def test_per_text_non_multiple_deterministic_remainder():
    docs = [_doc("Qur", document_type="scripture"), _doc("Hadith", document_type="hadith")]
    qs, _ = _gen(docs, per_text=18, seed=1)  # 18 over 4 tasks -> 5,5,4,4 in canonical order
    per = [q for q in qs if q.source["work"] == "Qur"]
    counts = [sum(1 for q in per if q.task == t) for t in TASKS]
    assert counts == [5, 5, 4, 4]


def test_tasks_subset_splits_over_subset():
    docs = [_doc("Qur"), _doc("Hadith", document_type="hadith")]
    qs, _ = _gen(docs, per_text=10, seed=1, tasks=("retrieve_quote",))
    per = [q for q in qs if q.source["work"] == "Qur"]
    assert len(per) == 10 and {q.task for q in per} == {"retrieve_quote"}


def test_per_text_below_active_count_fails_fast():
    docs = [_doc("Qur"), _doc("Hadith", document_type="hadith")]
    with pytest.raises(GenerateError, match=r"per-text 3 < number of active tasks 4"):
        _gen(docs, per_text=3, seed=1)


def test_unknown_task_fails():
    docs = [_doc("Qur")]
    with pytest.raises(GenerateError, match="unknown task"):
        _gen(docs, per_text=8, tasks=("identify_version",))


def test_negatives_share_out_of_range_fails_fast():
    # negatives_share is validated in generate() core (not only the CLI), so a library caller
    # cannot pass an out-of-range share silently.
    docs = [_doc("Qur"), _doc("Hadith", document_type="hadith")]
    for bad in (-0.1, 1.5):
        with pytest.raises(GenerateError, match=r"negatives_share .* out of range"):
            _gen(docs, per_text=8, seed=1, negatives_share=bad)
    # the boundary values are valid
    _gen(docs, per_text=8, seed=1, negatives_share=0.0)
    _gen(docs, per_text=8, seed=1, negatives_share=1.0)


def test_retired_tasks_absent():
    assert "identify_version" not in TASKS and "identify_source" not in TASKS
    assert TASKS == ("retrieve_quote", "complete_unit", "cite_passage", "verify_source")


# --- prompt rendering --------------------------------------------------------


def test_display_citation_strips_work_prefix():
    # work-prefixed citation (hadith/D&C shape) renders the edition once
    pref = _doc("Sahih al-Bukhari", document_type="hadith",
                citation_fmt=lambda i: f"Sahih al-Bukhari {i}")
    bare = _doc("Qur", document_type="scripture", citation_fmt=lambda i: f"{i}:1")
    qs, _ = generate([pref, bare], _meta([pref, bare]),
                     per_text=4, seed=1, tasks=("retrieve_quote",))
    # the work name appears exactly once in the hadith prompt (no "...Sahih al-Bukhari Sahih al-Bukhari 1")
    hadith_prompt = next(q.prompt for q in qs if q.source["work"] == "Sahih al-Bukhari")
    assert hadith_prompt.count("Sahih al-Bukhari") == 1
    # bare citation is unchanged
    bare_prompt = next(q.prompt for q in qs if q.source["work"] == "Qur")
    assert "What is the text of Qur " in bare_prompt


def test_prompt_strings_are_byte_exact():
    """Pin the four authoritative template strings byte-for-byte (they feed the digest)."""
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma"
    e1 = Entry("verse", "Work 1:1", text)
    e2 = Entry("verse", "Work 2:2",
               "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen")
    doc = Document(tradition=["T"], work="Work", version="V", language="en",
                   document_type="scripture", source_url=None, entries=[e1, e2])
    meta = {("Work", "V", "en"): TextMeta(requested_as=("Edition",), canonical_language="en",
                                          target_key=("Work", "V", "en"))}

    rq, _ = generate([doc], meta, per_text=2, seed=1, tasks=("retrieve_quote",))
    p = next(q.prompt for q in rq if q.expected["text"] == text)
    assert p == "What is the text of Edition 1:1? Reply with the exact text of that verse and nothing else."

    cu, _ = generate([doc], meta, per_text=2, seed=1, tasks=("complete_unit",))
    p = next(q.prompt for q in cu if q.expected.get("full_text") == text)
    assert p == ('Please complete this quote from Edition: '
                 '"alpha beta gamma delta epsilon zeta eta theta iota" '
                 'Reply with only the remaining words.')

    cp, _ = generate([doc], meta, per_text=2, seed=1, tasks=("cite_passage",))
    p = next(q.prompt for q in cp if q.expected["citation"] == "Work 1:1")
    assert p == ('Where in Edition can I find this quote? '
                 f'"{text}" Answer with the citation only, in the same form as: Work 2:2.')

    vs, _ = generate([doc], meta, per_text=2, seed=1, negatives_share=0.0, tasks=("verify_source",))
    p = next(q.prompt for q in vs if text in q.prompt)
    assert p == f'Is the following text from Edition? "{text}" Answer Yes or No.'


def test_verify_source_source_citation_empty_and_true_citation_recorded():
    asked = _doc("Bukhari", language="ar", document_type="hadith_collection")
    other = _doc("Qur", language="ar", document_type="scripture")
    qs, _ = generate([asked, other], _meta([asked, other]),
                     per_text=8, seed=1, negatives_share=0.5, tasks=("verify_source",))
    for q in qs:
        assert q.source["citation"] == ""  # a passage, not a citation, is shown
        assert "true_citation" in q.expected  # the passage's real citation is ground truth
    neg = next(q for q in qs if q.source["work"] == "Bukhari" and q.expected["answer"] == "no")
    # the negative's true_citation is the passage's real citation (from Qur), while source.work
    # is the asked edition (Bukhari) — the provenance lives in expected, not in source.citation
    assert neg.expected["true_work"] == "Qur" and neg.expected["true_citation"].startswith("Qur ")


def test_edition_is_seeded_choice_recorded_in_source():
    docs = [_doc("Qur"), _doc("Hadith", document_type="hadith")]
    names = {("Qur", "V", "en"): ("the Qur'an", "Quran", "Koran")}
    qs, _ = _gen(docs, per_text=8, seed=3, requested=names)
    qur = [q for q in qs if q.source["work"] == "Qur"]
    used = {q.source["requested_as"] for q in qur}
    assert used <= {"the Qur'an", "Quran", "Koran"}  # only names from the list
    # the rendered name appears in the prompt and never the raw version string "V"
    for q in qur:
        assert q.source["requested_as"] in q.prompt
        assert "from V" not in q.prompt and "of V " not in q.prompt


def test_cite_passage_shows_exemplar_from_other_entry():
    docs = [_doc("Qur", n=30), _doc("Hadith", document_type="hadith", n=30)]
    qs, _ = _gen(docs, per_text=8, seed=1, tasks=("cite_passage",))
    for q in qs:
        # "...in the same form as: <exemplar>." — exemplar is a real OTHER citation of the text
        assert "in the same form as:" in q.prompt
        exemplar = q.prompt.rsplit("in the same form as:", 1)[1].strip().rstrip(".")
        assert exemplar != q.expected["citation"]  # a DIFFERENT entry's citation


def test_cite_passage_exact_quota_succeeds_with_two_entries():
    # max(quota, 2): a text with exactly quota == 2 entries fills, because each target's
    # exemplar may be the OTHER target entry (just not itself).
    docs = [_doc("Qur", n=2)]
    qs, _ = _gen(docs, per_text=2, seed=1, tasks=("cite_passage",))
    assert len(qs) == 2 and {q.task for q in qs} == {"cite_passage"}
    # the exemplar shown is the sibling entry's citation, never the target's own
    for q in qs:
        exemplar = q.prompt.rsplit("in the same form as:", 1)[1].strip().rstrip(".")
        assert exemplar != q.expected["citation"]


def test_cite_passage_single_entry_fails_fast():
    # one entry, quota 1 -> max(quota, 2) == 2 > 1: no distinct exemplar exists -> fail
    docs = [_doc("Qur", n=1)]
    with pytest.raises(GenerateError, match="cite_passage"):
        _gen(docs, per_text=1, seed=1, tasks=("cite_passage",))


# --- verify_source identity + cross-family negatives -------------------------


def test_verify_source_positive_and_negative_identity():
    asked = _doc("Bukhari", version="arabic", language="ar", document_type="hadith")
    other = _doc("Qur", version="uthmani", language="ar", document_type="scripture")
    qs, _ = generate([asked, other], _meta([asked, other]),
                     per_text=8, seed=1, negatives_share=0.5, tasks=("verify_source",))
    bukhari = [q for q in qs if q.source["work"] == "Bukhari"]
    pos = [q for q in bukhari if q.expected["answer"] == "yes"]
    neg = [q for q in bukhari if q.expected["answer"] == "no"]
    assert pos and neg
    for q in pos:  # positive: asked == passage source
        assert q.expected["true_work"] == "Bukhari" and q.expected["true_version"] == "arabic"
    for q in neg:  # negative: source is the ASKED edition, true_* is the passage's real source
        assert q.source["work"] == "Bukhari" and q.source["version"] == "arabic"
        assert q.expected["true_work"] == "Qur" and q.expected["true_version"] == "uthmani"
        assert "from " in q.prompt  # attributed to the asked edition's requested_as name


def test_verify_source_negatives_are_cross_family_only():
    # the nine hadith collections are ONE family: Bukhari's negatives must come from the
    # scripture, never another hadith collection (shared-narration risk).
    a = _doc("Bukhari", language="ar", document_type="hadith_collection")
    b = _doc("Muslim", language="ar", document_type="hadith_collection")
    s = _doc("Qur", language="ar", document_type="scripture")
    qs, _ = generate([a, b, s], _meta([a, b, s]),
                     per_text=8, seed=2, negatives_share=0.5, tasks=("verify_source",))
    for q in qs:
        if q.source["work"] == "Bukhari" and q.expected["answer"] == "no":
            assert q.expected["true_work"] == "Qur"  # never "Muslim" (same family)


def test_verify_source_same_work_bible_editions_are_same_family():
    # KJV/ASV/WEB are all work "The Bible" -> one family (near-identical verses would make
    # "no" a trap); a Bible edition's negatives come from a different work (Book of Mormon).
    kjv = _doc("The Bible", version="KJV", language="en", document_type="scripture")
    asv = _doc("The Bible", version="ASV", language="en", document_type="scripture")
    bom = _doc("Book of Mormon", version="2013", language="en", document_type="scripture")
    qs, _ = generate([kjv, asv, bom], _meta([kjv, asv, bom]),
                     per_text=8, seed=1, negatives_share=0.5, tasks=("verify_source",))
    for q in qs:
        if q.source["work"] == "The Bible" and q.expected["answer"] == "no":
            assert q.expected["true_work"] == "Book of Mormon"  # never the other Bible edition


def test_verify_source_prefers_same_language_negatives():
    # same-language different-family partner (Hadith ar) is preferred over cross-language.
    asked = _doc("Qur", language="ar", document_type="scripture")
    same = _doc("Bukhari", language="ar", document_type="hadith_collection")
    cross = _doc("BoM", language="en", document_type="scripture")
    qs, _ = generate([asked, same, cross], _meta([asked, same, cross]),
                     per_text=8, seed=1, negatives_share=0.5, tasks=("verify_source",))
    neg = [q for q in qs if q.source["work"] == "Qur" and q.expected["answer"] == "no"]
    assert neg and all(q.expected["true_language"] == "ar" for q in neg)  # Qur: all same-language
    man = build_manifest([asked, same, cross], qs, [], 1, 8, 0.5)
    # Qur has a same-language partner (Bukhari ar), so none of its negatives are cross-language
    assert not any(r["work"] == "Qur" for r in man["verify_source_cross_language_negatives"])


def test_verify_source_cross_language_fallback_recorded():
    # Talmud Aramaic (he) has no same-language different-family partner -> cross-language,
    # and the manifest records the per-text count.
    asked = _doc("Talmud", language="he", document_type="talmud")
    other = _doc("Qur", language="ar", document_type="scripture")
    qs, excl = generate([asked, other], _meta([asked, other]),
                        per_text=8, seed=1, negatives_share=0.5, tasks=("verify_source",))
    man = build_manifest([asked, other], qs, excl, 1, 8, 0.5)
    rows = man["verify_source_cross_language_negatives"]
    talmud = next((r for r in rows if r["work"] == "Talmud"), None)
    assert talmud is not None and talmud["count"] >= 1  # Talmud (he) had no he partner


def test_verify_source_negative_excludes_contained_passage():
    # A passage that occurs in the asked edition (even under a non-canonical/short citation)
    # must never be used as a FALSE negative for it (the "no" ground truth would be wrong).
    # Book-of-Mormon-quotes-KJV-Isaiah is the real case this guards.
    shared_text = " ".join(f"sharedverse w{j}" for j in range(18))
    asked = _doc("Bukhari", language="ar", document_type="hadith_collection")
    # the asked edition also contains the shared passage, under a NON-canonical citation
    asked.entries.append(Entry("verse", "unnumbered para.", shared_text))
    other = _doc("Qur", language="ar", document_type="scripture")
    other.entries.append(Entry("verse", "Qur 9:9", shared_text))  # same text, different family
    qs, _ = generate([asked, other], _meta([asked, other]),
                     per_text=8, seed=1, negatives_share=0.5, tasks=("verify_source",))
    negs = [q for q in qs if q.source["work"] == "Bukhari" and q.expected["answer"] == "no"]
    assert negs  # there ARE negatives
    # none of them presents the shared passage, because it is contained in the asked edition
    assert all(shared_text not in q.prompt for q in negs)


def test_verify_source_fails_fast_when_all_cross_family_passages_contained():
    """Structural proof that the containment filter is load-bearing (deterministic, seed-free):
    if EVERY different-family passage is also present in the asked edition, there is no eligible
    negative and generation fails fast — remove the `ne in asked.all_norm` filter and it would
    wrongly succeed."""
    asked = _doc("Bukhari", language="ar", document_type="hadith_collection", n=30)
    other = _doc("Qur", language="ar", document_type="scripture", n=0)
    # every Qur entry is verbatim one of Bukhari's texts -> all contained in the asked edition
    other.entries = [Entry("verse", f"Qur {i}", e.text) for i, e in enumerate(asked.entries, 1)]
    with pytest.raises(GenerateError, match="cross-family"):
        generate([asked, other], _meta([asked, other]), per_text=8, seed=1,
                 negatives_share=0.5, tasks=("verify_source",))


def test_verify_source_insufficient_cross_family_pool_fails_fast():
    # only hadith collections (one family) -> a hadith's different-family negative pool is empty
    a = _doc("Bukhari", language="ar", document_type="hadith_collection")
    b = _doc("Muslim", language="ar", document_type="hadith_collection")
    with pytest.raises(GenerateError, match="cross-family"):
        generate([a, b], _meta([a, b]), per_text=8, seed=1,
                 negatives_share=0.5, tasks=("verify_source",))


def test_verify_source_no_negatives_when_share_zero():
    docs = [_doc("Bukhari", document_type="hadith"), _doc("Qur")]
    qs, _ = _gen(docs, per_text=8, seed=1, negatives_share=0.0, tasks=("verify_source",))
    assert all(q.expected["answer"] == "yes" for q in qs)


# --- pool gating -------------------------------------------------------------


def test_noncanonical_citations_excluded():
    doc = _doc("Enc", document_type="scripture", n=0)
    doc.entries = [
        Entry("paragraph", "unnumbered para.", " ".join(f"front w{j}" for j in range(18))),
        Entry("paragraph", "Enc 2 (dup 1)", " ".join(f"dup w{j}" for j in range(18))),
    ] + [Entry("paragraph", f"Enc {i}", " ".join(f"real{i} w{j}" for j in range(18))) for i in range(1, 20)]
    qs, _ = _gen([doc], per_text=8, seed=1, tasks=("retrieve_quote",))
    cited = {q.expected and q.source["citation"] for q in qs}
    assert "unnumbered para." not in cited and "Enc 2 (dup 1)" not in cited


def test_insufficient_pool_fails_fast():
    docs = [_doc("Qur", n=3), _doc("Hadith", document_type="hadith", n=30)]
    with pytest.raises(GenerateError, match="insufficient entries"):
        _gen(docs, per_text=28, seed=1, tasks=("retrieve_quote",))  # Qur has only 3 entries


# --- manifest + digest -------------------------------------------------------


def test_build_manifest_fields():
    docs = [_doc("Qur"), _doc("Hadith", document_type="hadith"),
            _doc("TalmudEn", language="en", document_type="talmud")]
    tm = _meta(docs, canonical={("TalmudEn", "V", "en"): "he"})
    qs, excl = generate(docs, tm, per_text=8, seed=1)
    m = build_manifest(docs, qs, excl, seed=1, per_text=8, negatives_share=0.5,
                       tasks=None, inputs=["std/x"])
    assert m["per_text"] == 8
    assert "per_task" not in m and "quotas" not in m
    assert m["n_questions"] == len(qs)
    assert m["tasks_requested"] == list(TASKS)
    assert {(t["work"], t["version"], t["language"]) for t in m["selected_texts"]} == {
        ("Qur", "V", "en"), ("Hadith", "V", "en")}
    assert m["excluded_texts"] == [{"work": "TalmudEn", "version": "V", "language": "en",
                                    "reason": "language 'en' != canonical_language 'he'"}]
    assert len(m["question_set_digest"]) == 16 and len(m["corpus_hash"]) == 16


def test_digest_reflects_full_content_not_just_ids():
    docs = [_doc("Qur"), _doc("Hadith", document_type="hadith")]
    qs, _ = _gen(docs, per_text=8, seed=1)
    d1 = question_set_digest(qs)
    qs[0].prompt = qs[0].prompt + " (tampered)"
    assert question_set_digest(qs) != d1  # prompt change moves the digest


def test_corpus_hash_changes_with_content():
    a = [_doc("Qur")]
    b = [_doc("Qur")]
    assert corpus_hash(a) == corpus_hash(b)
    b[0].entries[0] = Entry("verse", b[0].entries[0].citation, "different text here now")
    assert corpus_hash(a) != corpus_hash(b)


def test_real_guru_granth_sahib_pools_fill_every_template():
    """Spec 37: the Granth's eligible pools, through generate's own selection. Full ``generate``
    over the corpus takes ~40 min, so this pins the pools instead: 1,452 panktis >= 12 words
    (every template), 100 >= 16 (complete_unit) — both well above the per-template quota of 7.
    Dandas are not entry words, so they cannot inflate either count."""
    from pathlib import Path

    from sacredbench import catalogue as cat
    from sacredbench.convert import convert_target
    from sacredbench.generate import MIN_WORDS_COMPLETABLE, _build_texts

    raw = Path(__file__).resolve().parents[2] / "texts" / "raw"
    sources = cat.discover_catalogue(raw)
    [t] = [t for t in cat.all_targets(sources) if t.source_id == "Sikhism"]
    docs = convert_target(t.payload_paths(raw), t)
    [text], excluded = _build_texts(docs, cat.text_metadata(sources))
    assert not excluded and text.language == "pa"
    assert len(text.entries) == 1452
    assert sum(len(e.text.split()) >= MIN_WORDS_COMPLETABLE for e in text.entries) == 100
