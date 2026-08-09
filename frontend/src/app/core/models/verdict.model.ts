/**
 * How a resume screens against one job — see backend `app/ai/schemas.py`.
 *
 * Two calls answer this shape and the backend types share a base class for it:
 * the scorer returns it alone, the reviewer returns it with patches attached.
 * The split lives here for the same reason it lives there — a number labelled
 * "ATS score" has to mean the same thing whichever call produced it, and one
 * `<app-verdict>` rendering both is how the screen keeps that promise visible.
 */

export type Severity = 'critical' | 'important' | 'nice_to_have';

export interface MissingKeyword {
  keyword: string;
  severity: Severity;
  rationale: string;
}

export interface Verdict {
  match_score: number;
  summary: string;
  matched_keywords: string[];
  missing_keywords: MissingKeyword[];
}
