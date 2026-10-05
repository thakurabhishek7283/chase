import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ResumeService } from '../../core/services/resume.service';
import { ReviewService } from '../../core/services/review.service';
import { ScoreService } from '../../core/services/score.service';
import { JobProfileService } from '../../core/services/job-profile.service';
import { JobProfile } from '../../core/models/job-profile.model';
import { Resume, ResumeOutline, ResumeSummary } from '../../core/models/resume.model';
import { Review, ReviewSummary } from '../../core/models/review.model';
import { Score } from '../../core/models/score.model';
import { detailFrom } from '../../core/http-error';
import { ReviewPanel } from '../review-panel/review-panel';
import { ScorePanel } from '../score-panel/score-panel';
import { SlotConfigEditor } from '../slot-config-editor/slot-config-editor';

/**
 * Everything you can do to one resume, on one screen.
 *
 * This used to be three: a LaTeX workbench, a tailoring studio, and an ATS
 * panel, each with its own idea of what a resume was. They are one page now
 * because they were always one job — see what the template exposes, score it
 * against a role, and work through what that turns up.
 *
 * One control drives the whole page: the role selector. Picking a role shows
 * what this resume already scores against it, from the scores loaded on open,
 * with no request at all — then the two buttons underneath are the cheap
 * question ("what does it score?") and the expensive one ("what should change?").
 *
 * A tailored version gets exactly the same screen. That is the point of it: the
 * way to raise a tailored resume's score is to review the version, which is why
 * nothing here special-cases one.
 *
 * The outline leads rather than hides: an author who cannot see that their
 * Skills section is frozen has no way to work out why nothing ever proposes a
 * change to it.
 */
@Component({
  selector: 'app-resume-detail',
  standalone: true,
  imports: [DatePipe, FormsModule, RouterLink, ReviewPanel, ScorePanel, SlotConfigEditor],
  templateUrl: './resume-detail.html',
  styleUrl: './resume-detail.scss',
})
export class ResumeDetail implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly resumes = inject(ResumeService);
  private readonly reviews = inject(ReviewService);
  private readonly scores = inject(ScoreService);
  private readonly jobs = inject(JobProfileService);

  readonly resumeId = signal('');
  readonly resume = signal<Resume | null>(null);
  readonly outline = signal<ResumeOutline | null>(null);
  readonly versions = signal<ResumeSummary[]>([]);
  readonly history = signal<ReviewSummary[]>([]);
  readonly jobProfiles = signal<JobProfile[]>([]);
  /** Every stored score for this resume, fetched once on open. */
  readonly storedScores = signal<Score[]>([]);

  readonly selectedJobId = signal('');
  readonly activeReview = signal<Review | null>(null);

  readonly loading = signal(true);
  readonly starting = signal(false);
  readonly downloading = signal(false);
  readonly error = signal<string | null>(null);

  readonly isChild = computed(() => !!this.resume()?.master_resume_id);
  readonly canReview = computed(() => !!this.selectedJobId() && !this.starting());
  /**
   * The score for the selected role, straight from what was already loaded.
   * Switching roles is a lookup, not a request — the whole reason the scores
   * arrive as one list rather than one call per role.
   */
  readonly selectedScore = computed(
    () => this.storedScores().find((s) => s.job_profile_id === this.selectedJobId()) ?? null,
  );
  readonly editableSections = computed(
    () => this.outline()?.sections.filter((s) => s.editable) ?? [],
  );
  /** Short enough to compare at a glance, long enough to be meaningless to fake. */
  readonly shortTemplateHash = computed(() => this.outline()?.template_hash.slice(0, 12) ?? '');

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    this.resumeId.set(id);
    this.jobs.list().subscribe((profiles) => this.jobProfiles.set(profiles));
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.resumes.get(this.resumeId()).subscribe({
      next: (resume) => this.resume.set(resume),
      error: async (err) => this.error.set(await detailFrom(err, 'Could not load that resume.')),
    });
    this.resumes.outline(this.resumeId()).subscribe({
      next: (outline) => {
        this.outline.set(outline);
        this.loading.set(false);
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'Could not read that .tex file.'));
        this.loading.set(false);
      },
    });
    this.reloadVersions();
    this.reviews.listFor(this.resumeId()).subscribe({
      next: (rows) => this.history.set(rows),
      error: () => this.history.set([]),
    });
    this.reloadScores();
  }

  /**
   * One request for every role this resume has been scored against.
   *
   * Deliberately not one per role on demand: it never reaches a model, so the
   * page can open on the numbers instead of on a row of spinners.
   */
  reloadScores(): void {
    this.scores.list(this.resumeId()).subscribe({
      next: (rows) => {
        this.storedScores.set(rows);
        // Land on something already answered rather than an empty selector.
        if (!this.selectedJobId() && rows.length) {
          this.selectedJobId.set(rows[0].job_profile_id);
        }
      },
      error: () => this.storedScores.set([]),
    });
  }

  /** Fold one freshly computed score into the list, replacing any older one. */
  onScored(score: Score): void {
    this.storedScores.update((rows) => [
      score,
      ...rows.filter((row) => row.job_profile_id !== score.job_profile_id),
    ]);
  }

  reloadVersions(): void {
    this.resumes.versions(this.resumeId()).subscribe({
      next: (rows) => this.versions.set(rows.filter((v) => v.id !== this.resumeId())),
      error: () => this.versions.set([]),
    });
  }

  onOutlineChanged(outline: ResumeOutline): void {
    this.outline.set(outline);
  }

  // --- reviews --------------------------------------------------------------

  startReview(): void {
    if (!this.canReview()) return;
    this.starting.set(true);
    this.error.set(null);
    this.activeReview.set(null);

    this.reviews.create(this.resumeId(), this.selectedJobId()).subscribe({
      next: (review) => {
        this.activeReview.set(review);
        this.starting.set(false);
        this.reviews.listFor(this.resumeId()).subscribe((rows) => this.history.set(rows));
        // The review scored this resume on its way past and cached the verdict,
        // so the card above now has a current number waiting for it — for free.
        this.reloadScores();
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'The review could not be run.'));
        this.starting.set(false);
      },
    });
  }

  openReview(reviewId: string): void {
    this.error.set(null);
    this.reviews.get(reviewId).subscribe({
      next: (review) => this.activeReview.set(review),
      error: async (err) => this.error.set(await detailFrom(err, 'Could not open that review.')),
    });
  }

  onReviewChanged(review: Review): void {
    this.activeReview.set(review);
  }

  onFinalized(): void {
    this.reloadVersions();
    this.reviews.listFor(this.resumeId()).subscribe((rows) => this.history.set(rows));
  }

  jobTitle(jobProfileId: string): string {
    return this.jobProfiles().find((job) => job.id === jobProfileId)?.position_title ?? 'a role';
  }

  // --- the document itself --------------------------------------------------

  download(output: 'pdf' | 'tex'): void {
    this.downloading.set(true);
    this.error.set(null);
    this.resumes.download(this.resumeId(), output).subscribe({
      next: (blob) => {
        const name = (this.resume()?.title ?? 'resume').replace(/[^\w-]+/g, '-');
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${name}.${output}`;
        link.click();
        URL.revokeObjectURL(url);
        this.downloading.set(false);
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, `Could not produce the ${output.toUpperCase()}.`));
        this.downloading.set(false);
      },
    });
  }
}
