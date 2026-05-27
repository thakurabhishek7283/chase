import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { API_BASE_URL } from '../../core/api-config';
import { AtsService } from '../../core/services/ats.service';
import { ResumeService } from '../../core/services/resume.service';
import { JobProfileService } from '../../core/services/job-profile.service';
import { ATSReport, AutofixResult, PhrasingSuggestion } from '../../core/models/ats.model';
import { Resume } from '../../core/models/resume.model';
import { JobProfile } from '../../core/models/job-profile.model';

@Component({
  selector: 'app-ats-panel',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './ats-panel.html',
  styleUrl: './ats-panel.scss',
})
export class AtsPanel implements OnInit {
  private readonly atsService = inject(AtsService);
  private readonly resumeService = inject(ResumeService);
  private readonly jobProfileService = inject(JobProfileService);

  readonly resumes = signal<Resume[]>([]);
  readonly jobProfiles = signal<JobProfile[]>([]);

  readonly selectedResumeId = signal('');
  readonly selectedJobId = signal('');
  readonly targetScore = signal(85);
  readonly saveAsTailored = signal(true);

  readonly report = signal<ATSReport | null>(null);
  readonly autofixResult = signal<AutofixResult | null>(null);
  readonly savedResumeId = signal<string | null>(null);
  readonly scoring = signal(false);
  readonly fixing = signal(false);
  readonly error = signal<string | null>(null);

  /** Suggestions the user has ticked, keyed by index into the report. */
  private readonly accepted = signal<Set<number>>(new Set());

  readonly canRun = computed(() => !!this.selectedResumeId() && !!this.selectedJobId());
  readonly acceptedCount = computed(() => this.accepted().size);

  ngOnInit(): void {
    this.resumeService.list().subscribe((resumes) => this.resumes.set(resumes));
    this.jobProfileService.list().subscribe((jobs) => this.jobProfiles.set(jobs));
  }

  isAccepted(index: number): boolean {
    return this.accepted().has(index);
  }

  toggleSuggestion(index: number): void {
    const next = new Set(this.accepted());
    if (next.has(index)) {
      next.delete(index);
    } else {
      next.add(index);
    }
    this.accepted.set(next);
  }

  scoreLabel(score: number): string {
    if (score >= 85) return 'strong';
    if (score >= 65) return 'moderate';
    return 'weak';
  }

  runScore(): void {
    if (!this.canRun()) return;
    this.scoring.set(true);
    this.error.set(null);
    this.autofixResult.set(null);
    this.accepted.set(new Set());

    this.atsService
      .score({ resume_id: this.selectedResumeId(), job_profile_id: this.selectedJobId() })
      .subscribe({
        next: (response) => {
          this.report.set(response.report);
          this.scoring.set(false);
        },
        error: (err) => {
          this.error.set(err?.error?.detail ?? 'Scoring failed.');
          this.scoring.set(false);
        },
      });
  }

  runAutofix(): void {
    if (!this.canRun()) return;
    this.fixing.set(true);
    this.error.set(null);
    this.savedResumeId.set(null);

    this.atsService
      .autofix({
        resume_id: this.selectedResumeId(),
        job_profile_id: this.selectedJobId(),
        target_score: this.targetScore(),
        save_as_tailored_version: this.saveAsTailored(),
      })
      .subscribe({
        next: (response) => {
          this.autofixResult.set(response.result);
          this.report.set(response.result.final_report);
          this.fixing.set(false);
          if (response.saved_resume_id) {
            this.savedResumeId.set(response.saved_resume_id);
            this.resumeService.list().subscribe((resumes) => this.resumes.set(resumes));
          }
        },
        error: (err) => {
          this.error.set(err?.error?.detail ?? 'Autofix failed.');
          this.fixing.set(false);
        },
      });
  }

  pdfUrl(resumeId: string): string {
    return `${API_BASE_URL}/resumes/${resumeId}/pdf`;
  }

  trackSuggestion(index: number, _suggestion: PhrasingSuggestion): number {
    return index;
  }
}
