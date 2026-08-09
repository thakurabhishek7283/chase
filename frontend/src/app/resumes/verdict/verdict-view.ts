import { Component, computed, input } from '@angular/core';

import { Verdict } from '../../core/models/verdict.model';

/**
 * How a resume screens, rendered once for both the things that answer it.
 *
 * A score and a review carry the same four fields — see
 * `core/models/verdict.model` — and this is the only place they are drawn. Two
 * copies of this markup would let "your ATS score" look like one thing on the
 * scoring card and another on the review panel, which is precisely the
 * confusion a resume optimizer cannot afford.
 *
 * Presentational and stateless: it takes a verdict and shows it. Anything that
 * can be clicked belongs to whichever panel is hosting it.
 */
@Component({
  selector: 'app-verdict-view',
  standalone: true,
  templateUrl: './verdict-view.html',
  styleUrl: './verdict-view.scss',
})
export class VerdictView {
  readonly verdict = input.required<Verdict>();
  /** Rendered under the score — "as of last Tuesday", "improved from 62". */
  readonly caption = input<string>('');

  readonly band = computed(() => {
    const score = this.verdict().match_score;
    if (score >= 85) return 'strong';
    return score < 65 ? 'weak' : 'fair';
  });
}
