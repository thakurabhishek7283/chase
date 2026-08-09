/**
 * A reviewed tailoring — see backend `app/schemas/review.py`.
 *
 * The rule the whole screen is built around: `pending_count` must reach zero
 * before anything can be previewed or finalized. The server enforces it; the UI
 * simply reflects it rather than pretending to be the gate.
 */

import { Severity, Verdict } from './verdict.model';

export type PatchStatus = 'pending' | 'accepted' | 'rejected';
export type ReviewStatus = 'open' | 'finalized';

export interface Patch {
  id: string;
  slot_id: string;
  slot_kind: 'group' | 'region';
  section_heading: string;
  /** What the reviewed resume says today, shown beside the proposal. */
  original_items: string[] | null;
  original_latex: string | null;
  proposed_items: string[] | null;
  proposed_latex: string | null;
  reason: string;
  severity: Severity;
  status: PatchStatus;
  feedback: string | null;
  revision_count: number;
}

/** A verdict with the work attached, mirroring `ai/review.ResumeReviewResult`. */
export interface Review extends Verdict {
  id: string;
  /** The resume reviewed — a master, or a tailored version taken further. */
  source_resume_id: string;
  job_profile_id: string;
  status: ReviewStatus;
  child_resume_id: string | null;
  created_at: string;
  updated_at: string;
  patches: Patch[];
  pending_count: number;
}

export interface ReviewSummary {
  id: string;
  job_profile_id: string;
  status: ReviewStatus;
  match_score: number;
  child_resume_id: string | null;
  created_at: string;
  pending_count: number;
}

export interface FinalizeResponse {
  review_id: string;
  child_resume_id: string;
  title: string;
  version_label: string | null;
  accepted_count: number;
  rejected_count: number;
}
