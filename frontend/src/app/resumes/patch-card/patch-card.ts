import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Patch } from '../../core/models/review.model';

/** What the parent should do with this patch. */
export type PatchAction =
  | { kind: 'accept' }
  | { kind: 'reject' }
  | { kind: 'feedback'; feedback: string }
  | { kind: 'revert' };

/**
 * One proposed change, with the text it would replace beside it.
 *
 * A patch is unjudgeable without the original — "use the job's vocabulary" means
 * nothing until you can see what it currently says — so the two are always shown
 * together rather than behind a toggle.
 *
 * The card owns no state that outlives a decision. It reports what the author
 * chose and lets the parent round-trip it, so what is on screen is always what
 * the server has.
 */
@Component({
  selector: 'app-patch-card',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './patch-card.html',
  styleUrl: './patch-card.scss',
})
export class PatchCard {
  readonly patch = input.required<Patch>();
  readonly busy = input(false);
  /** True once the review is finalized — the decisions are a record by then. */
  readonly locked = input(false);

  readonly act = output<PatchAction>();

  readonly showFeedback = signal(false);
  readonly draft = signal('');

  readonly isGroup = computed(() => this.patch().slot_kind === 'group');

  readonly originalLines = computed(() => {
    const patch = this.patch();
    return patch.original_items ?? (patch.original_latex ? [patch.original_latex] : []);
  });

  readonly proposedLines = computed(() => {
    const patch = this.patch();
    return patch.proposed_items ?? (patch.proposed_latex ? [patch.proposed_latex] : []);
  });

  readonly statusLabel = computed(() => {
    switch (this.patch().status) {
      case 'accepted':
        return 'Accepted';
      case 'rejected':
        return 'Rejected';
      default:
        return 'Needs a decision';
    }
  });

  toggleFeedback(): void {
    this.showFeedback.update((open) => !open);
    if (!this.showFeedback()) {
      this.draft.set('');
    }
  }

  submitFeedback(): void {
    const feedback = this.draft().trim();
    if (feedback.length < 3) return;
    this.act.emit({ kind: 'feedback', feedback });
    this.showFeedback.set(false);
    this.draft.set('');
  }
}
