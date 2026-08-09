import { DatePipe } from '@angular/common';
import { Component, computed, inject, input, output, signal } from '@angular/core';

import { ScoreService } from '../../core/services/score.service';
import { Score } from '../../core/models/score.model';
import { detailFrom } from '../../core/http-error';
import { VerdictView } from '../verdict/verdict-view';

/**
 * What this resume scores against the selected role, and how to find out.
 *
 * The panel renders from a score the parent already holds — the resume screen
 * loads every stored score in one request on open — so switching between roles
 * is instant and costs nothing. The button is the only thing here that can
 * reach a model, and it is never pressed on the screen's behalf.
 *
 * Works the same on a master and on a tailored version, which is the point: a
 * version's score is the answer to "did the tailoring actually help", and it
 * used to be unanswerable.
 */
@Component({
  selector: 'app-score-panel',
  standalone: true,
  imports: [DatePipe, VerdictView],
  templateUrl: './score-panel.html',
  styleUrl: './score-panel.scss',
})
export class ScorePanel {
  private readonly scores = inject(ScoreService);

  readonly resumeId = input.required<string>();
  readonly jobProfileId = input.required<string>();
  /** The stored score for this pair, or null if nobody has asked yet. */
  readonly score = input<Score | null>(null);

  readonly scored = output<Score>();

  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  readonly label = computed(() => {
    if (this.busy()) return 'Scoring…';
    return this.score() ? 'Score again' : 'Score this resume';
  });

  readonly caption = computed(() => (this.score()?.stale ? 'out of date' : 'as it stands'));

  run(): void {
    if (this.busy() || !this.jobProfileId()) return;
    this.busy.set(true);
    this.error.set(null);

    // `refresh` only when the stored answer is already current — otherwise the
    // server re-scores anyway, and sending it would forbid the free path on the
    // one press where it is genuinely available.
    const refresh = !!this.score() && !this.score()!.stale;

    this.scores.score(this.resumeId(), this.jobProfileId(), refresh).subscribe({
      next: (fresh) => {
        this.busy.set(false);
        this.scored.emit(fresh);
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'Could not score this resume.'));
        this.busy.set(false);
      },
    });
  }
}
