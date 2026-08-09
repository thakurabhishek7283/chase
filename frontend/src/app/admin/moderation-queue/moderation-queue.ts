import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { CompanyService } from '../../core/services/company.service';
import { JobProfileService } from '../../core/services/job-profile.service';
import { Company } from '../../core/models/company.model';
import { JobProfile } from '../../core/models/job-profile.model';

/**
 * The admin review queue for community-contributed public data.
 *
 * Both lists are filtered server-side to `status=pending`; the admin's
 * `visible_scope` would otherwise include everything.
 */
@Component({
  selector: 'app-moderation-queue',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './moderation-queue.html',
  styleUrl: './moderation-queue.scss',
})
export class ModerationQueue implements OnInit {
  private readonly companyService = inject(CompanyService);
  private readonly jobService = inject(JobProfileService);

  readonly companies = signal<Company[]>([]);
  readonly jobs = signal<JobProfile[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly busy = signal<string | null>(null);

  /** Rejection reasons, keyed by row id — a reason is required to reject. */
  readonly reasons = signal<Record<string, string>>({});

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.error.set(null);
    this.companyService.list({ status: 'pending' }).subscribe({
      next: (companies) => {
        this.companies.set(companies);
        this.jobService.list({ status: 'pending' }).subscribe({
          next: (jobs) => {
            this.jobs.set(jobs);
            this.loading.set(false);
          },
          error: () => this.fail(),
        });
      },
      error: () => this.fail(),
    });
  }

  reasonFor(id: string): string {
    return this.reasons()[id] ?? '';
  }

  setReason(id: string, value: string): void {
    this.reasons.update((current) => ({ ...current, [id]: value }));
  }

  approveCompany(company: Company): void {
    this.run(company.id, this.companyService.approve(company.id));
  }

  rejectCompany(company: Company): void {
    const reason = this.reasonFor(company.id).trim();
    if (!reason) return;
    this.run(company.id, this.companyService.reject(company.id, reason));
  }

  approveJob(job: JobProfile): void {
    this.run(job.id, this.jobService.approve(job.id));
  }

  rejectJob(job: JobProfile): void {
    const reason = this.reasonFor(job.id).trim();
    if (!reason) return;
    this.run(job.id, this.jobService.reject(job.id, reason));
  }

  private run(id: string, request: Observable<unknown>): void {
    this.busy.set(id);
    request.subscribe({
      next: () => {
        this.busy.set(null);
        this.reload();
      },
      error: () => {
        this.error.set('That review could not be recorded.');
        this.busy.set(null);
      },
    });
  }

  private fail(): void {
    this.error.set('Could not load the moderation queue.');
    this.loading.set(false);
  }
}
