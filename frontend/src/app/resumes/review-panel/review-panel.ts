import { Component, OnDestroy, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { ReviewService } from '../../core/services/review.service';
import { Patch, Review } from '../../core/models/review.model';
import { detailFrom } from '../../core/http-error';
import { PatchAction, PatchCard } from '../patch-card/patch-card';
import { VerdictView } from '../verdict/verdict-view';

/**
 * Work through a review one patch at a time, then keep the result.
 *
 * The gate — nothing renders while a patch is pending — belongs to the server;
 * this only mirrors it, so the button being enabled and the request succeeding
 * cannot disagree. `pending_count` comes back on every response, which is why
 * each decision round-trips rather than being applied optimistically.
 */
@Component({
  selector: 'app-review-panel',
  standalone: true,
  imports: [FormsModule, PatchCard, VerdictView],
  templateUrl: './review-panel.html',
  styleUrl: './review-panel.scss',
})
export class ReviewPanel implements OnDestroy {
  private readonly reviews = inject(ReviewService);
  private readonly sanitizer = inject(DomSanitizer);

  readonly review = input.required<Review>();

  /** A child was written — the parent reloads its version list. */
  readonly finalized = output<string>();
  readonly changed = output<Review>();

  readonly busyPatchId = signal<string | null>(null);
  readonly rendering = signal(false);
  readonly finalizing = signal(false);
  readonly versionLabel = signal('');
  readonly error = signal<string | null>(null);

  private previewObjectUrl: string | null = null;
  readonly previewUrl = signal<SafeResourceUrl | null>(null);

  readonly locked = computed(() => this.review().status === 'finalized');
  readonly total = computed(() => this.review().patches.length);
  readonly resolved = computed(() => this.total() - this.review().pending_count);
  readonly ready = computed(() => this.review().pending_count === 0);
  readonly acceptedCount = computed(
    () => this.review().patches.filter((p) => p.status === 'accepted').length,
  );

  readonly progress = computed(() => {
    const total = this.total();
    if (total === 0) return 'Nothing to review — this resume already fits.';
    return `${this.resolved()} of ${total} resolved`;
  });

  ngOnDestroy(): void {
    this.releasePreview();
  }

  // --- per-patch ------------------------------------------------------------

  onPatchAction(patch: Patch, action: PatchAction): void {
    const reviewId = this.review().id;
    this.busyPatchId.set(patch.id);
    this.error.set(null);
    // Any decision invalidates the rendered preview.
    this.releasePreview();

    const request =
      action.kind === 'feedback'
        ? this.reviews.sendBack(reviewId, patch.id, action.feedback)
        : action.kind === 'revert'
          ? this.reviews.revert(reviewId, patch.id)
          : this.reviews.decide(reviewId, patch.id, action.kind);

    request.subscribe({
      next: () => this.reload(),
      error: async (err) => {
        this.error.set(await detailFrom(err, 'That change could not be applied.'));
        this.busyPatchId.set(null);
      },
    });
  }

  acceptAll(): void {
    const pending = this.review().patches.filter((p) => p.status === 'pending');
    if (!pending.length) return;
    // Sequential rather than parallel: each response carries the authoritative
    // pending count, and firing them at once means racing to be last.
    this.applyInSequence(pending, 0);
  }

  private applyInSequence(patches: Patch[], index: number): void {
    if (index >= patches.length) {
      this.reload();
      return;
    }
    this.busyPatchId.set(patches[index].id);
    this.reviews.decide(this.review().id, patches[index].id, 'accept').subscribe({
      next: () => this.applyInSequence(patches, index + 1),
      error: async (err) => {
        this.error.set(await detailFrom(err, 'That change could not be applied.'));
        this.busyPatchId.set(null);
      },
    });
  }

  private reload(): void {
    this.reviews.get(this.review().id).subscribe({
      next: (fresh) => {
        this.busyPatchId.set(null);
        this.changed.emit(fresh);
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'Could not reload the review.'));
        this.busyPatchId.set(null);
      },
    });
  }

  // --- output ---------------------------------------------------------------

  private releasePreview(): void {
    if (this.previewObjectUrl) {
      URL.revokeObjectURL(this.previewObjectUrl);
      this.previewObjectUrl = null;
    }
    this.previewUrl.set(null);
  }

  renderPreview(): void {
    if (!this.ready()) return;
    this.rendering.set(true);
    this.error.set(null);

    this.reviews.preview(this.review().id, 'pdf').subscribe({
      next: (blob) => {
        this.releasePreview();
        this.previewObjectUrl = URL.createObjectURL(blob);
        this.previewUrl.set(
          this.sanitizer.bypassSecurityTrustResourceUrl(this.previewObjectUrl),
        );
        this.rendering.set(false);
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'Could not compile that preview.'));
        this.rendering.set(false);
      },
    });
  }

  downloadTex(): void {
    if (!this.ready()) return;
    this.reviews.preview(this.review().id, 'tex').subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'tailored.tex';
        link.click();
        URL.revokeObjectURL(url);
      },
      error: async (err) =>
        this.error.set(await detailFrom(err, 'Could not produce the source.')),
    });
  }

  finalize(): void {
    if (!this.ready() || this.locked()) return;
    this.finalizing.set(true);
    this.error.set(null);

    this.reviews.finalize(this.review().id, this.versionLabel().trim() || null).subscribe({
      next: (response) => {
        this.finalizing.set(false);
        this.finalized.emit(response.child_resume_id);
        this.reload();
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'Could not save the tailored resume.'));
        this.finalizing.set(false);
      },
    });
  }
}
