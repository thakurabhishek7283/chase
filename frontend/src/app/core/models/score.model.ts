/**
 * A cached ATS score — see backend `app/schemas/score.py`.
 *
 * Two flags carry the whole cost story, and the screen is built around them:
 * `stale` means the resume has changed since this was computed, and `computed`
 * means the response just spent a model call rather than reading a row.
 */

import { Verdict } from './verdict.model';

export interface Score extends Verdict {
  id: string;
  resume_id: string;
  job_profile_id: string;
  /** The resume has moved on. The number is still shown, but labelled. */
  stale: boolean;
  /** False when the answer came from the cache. */
  computed: boolean;
  updated_at: string;
}
