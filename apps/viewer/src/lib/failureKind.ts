// How an answered cell failed, finer than correct / incorrect / refused / missing.
//
// The four outcomes stay the headline: this label never changes `correct`. It is a
// deterministic reading of the metrics and the two texts, task by task:
//
//   retrieve_quote / complete_unit (incorrect)
//     other_script   the answer is not in the reference's script (often English prose)
//     omission       the answer is a shorter span contained in the reference
//     near_copy      token overlap ≥ 0.85: the scorer did not fold a close copy
//     paraphrase     token overlap in [0.4, 0.85): a rewrite, not a near copy
//     wrong_passage  everything else (a different span, or too little overlap to call)
//   retrieve_quote / complete_unit (correct, contained, not exact)
//     addition       the reference is delivered and the answer continues well past it
//                    (containment still scores this correct; the label only surfaces it)
//   cite_passage (incorrect)
//     hedge          more than one formally shaped citation
//     wrong_locus    exactly one citation, and it is not the reference
//     no_citation    no formally shaped citation
//   verify_source (incorrect)
//     wrong_verdict  a committed Yes/No that is not the expected one
//
// Refused and missing cells get no kind. A script mismatch is not evidence of another edition.

export type FailureKind =
  | "paraphrase"
  | "wrong_passage"
  | "other_script"
  | "near_copy"
  | "omission"
  | "addition"
  | "wrong_locus"
  | "hedge"
  | "no_citation"
  | "wrong_verdict";

export const FAILURE_KINDS: readonly FailureKind[] = [
  "paraphrase",
  "wrong_passage",
  "other_script",
  "near_copy",
  "omission",
  "addition",
  "wrong_locus",
  "hedge",
  "no_citation",
  "wrong_verdict",
];

/** A minor kind stays on the passage that was asked for. A major kind replaces it. */
const MINOR: ReadonlySet<FailureKind> = new Set(["paraphrase", "omission", "addition", "near_copy"]);

export function failureSeverity(kind: FailureKind | null): "minor" | "major" | null {
  if (!kind) return null;
  return MINOR.has(kind) ? "minor" : "major";
}

/** Short label for the explorer badge and filter. */
export const FAILURE_KIND_LABEL: Record<FailureKind, string> = {
  paraphrase: "paraphrase",
  wrong_passage: "wrong passage",
  other_script: "other script",
  near_copy: "near copy",
  omission: "omission",
  addition: "addition",
  wrong_locus: "wrong locus",
  hedge: "hedge",
  no_citation: "no citation",
  wrong_verdict: "wrong verdict",
};

/** High token-F1 misses in the committed runs are paraphrases, not contained quotes. */
const PARAPHRASE_F1 = 0.4;
const NEAR_COPY_F1 = 0.85;
/** Extra tokens past the reference before a contained answer is called an addition. */
const ADDITION_EXTRA_TOKENS = 8;

export interface FailureInput {
  task: string;
  correct: boolean;
  refused: boolean;
  missing: boolean;
  answer: string;
  expected: string;
  tokenF1: number | null;
  normalized: number | null;
  containsReference: number | null;
  nCandidates: number | null;
}

/** Devanagari or Gurmukhi block. */
function isIndic(c: number): boolean {
  return (c >= 0x0900 && c <= 0x097f) || (c >= 0x0a00 && c <= 0x0a7f);
}

// Devanagari/Gurmukhi vowel signs (\p{M}) are part of the word, so they are kept, as in
// pipelines/sacredbench/failure_kind.py. Every other non-letter/number folds to a space.
function normalize(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, (ch) => (isIndic(ch.codePointAt(0)!) && /\p{M}/u.test(ch) ? ch : " "))
    .replace(/\s+/g, " ")
    .trim();
}

function tokenList(s: string): string[] {
  const n = normalize(s);
  return n ? n.split(" ") : [];
}

type Script = "hebrew" | "arabic" | "greek" | "latin" | "devanagari" | "gurmukhi";

function primaryScript(s: string): Script | null {
  let hebrew = 0;
  let arabic = 0;
  let greek = 0;
  let latin = 0;
  let devanagari = 0;
  let gurmukhi = 0;
  for (const ch of s) {
    const c = ch.codePointAt(0)!;
    if (c >= 0x0900 && c <= 0x097f) devanagari++;
    else if (c >= 0x0a00 && c <= 0x0a7f) gurmukhi++;
    else if (c >= 0x0590 && c <= 0x05ff) hebrew++;
    else if (
      (c >= 0x0600 && c <= 0x06ff) ||
      (c >= 0x0750 && c <= 0x077f) ||
      (c >= 0x08a0 && c <= 0x08ff) ||
      (c >= 0xfb50 && c <= 0xfdff) ||
      (c >= 0xfe70 && c <= 0xfeff)
    )
      arabic++;
    // Greek and Coptic + Greek Extended. grc is a supported canonical language, so a Greek
    // prompt answered in English must read as other_script, not wrong_passage.
    else if ((c >= 0x0370 && c <= 0x03ff) || (c >= 0x1f00 && c <= 0x1fff)) greek++;
    else if ((c >= 65 && c <= 90) || (c >= 97 && c <= 122)) latin++;
  }
  const best = Math.max(hebrew, arabic, greek, latin, devanagari, gurmukhi);
  if (best < 4) return null;
  if (hebrew === best) return "hebrew";
  if (arabic === best) return "arabic";
  if (greek === best) return "greek";
  if (devanagari === best) return "devanagari";
  if (gurmukhi === best) return "gurmukhi";
  return "latin";
}

/** The answer's normalised text is a shorter, word-bounded span of the reference. */
function isOmission(answer: string, expected: string): boolean {
  const a = normalize(answer);
  const e = normalize(expected);
  const aTokens = a ? a.split(" ") : [];
  const eTokens = e ? e.split(" ") : [];
  if (aTokens.length < 2 || aTokens.length >= eTokens.length) return false;
  if (aTokens.length > eTokens.length * 0.85) return false;
  const padded = ` ${e} `;
  return padded.includes(` ${a} `);
}

function textRetrievalKind(input: FailureInput): FailureKind | null {
  if (input.correct) {
    if (input.containsReference !== 1 || input.normalized === 1) return null;
    const extra = tokenList(input.answer).length - tokenList(input.expected).length;
    return extra >= ADDITION_EXTRA_TOKENS ? "addition" : null;
  }
  const expectedScript = primaryScript(input.expected);
  const answerScript = primaryScript(input.answer);
  if (expectedScript && answerScript && expectedScript !== answerScript) return "other_script";
  if (isOmission(input.answer, input.expected)) return "omission";
  const f1 = input.tokenF1 ?? 0;
  if (f1 >= NEAR_COPY_F1) return "near_copy";
  if (f1 >= PARAPHRASE_F1) return "paraphrase";
  return "wrong_passage";
}

/** A failure kind for this cell, or null when the four-way outcome is the whole story. */
export function classifyFailure(input: FailureInput): FailureKind | null {
  if (input.missing || input.refused) return null;
  if (input.task === "retrieve_quote" || input.task === "complete_unit") return textRetrievalKind(input);
  if (!input.correct && input.task === "cite_passage") {
    if ((input.nCandidates ?? 0) > 1) return "hedge";
    if (input.nCandidates === 1) return "wrong_locus";
    return "no_citation";
  }
  if (!input.correct && input.task === "verify_source") return "wrong_verdict";
  return null;
}
