import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { JobProfileService } from '../../core/services/job-profile.service';
import { CompanyService } from '../../core/services/company.service';
import { JobProfile } from '../../core/models/job-profile.model';
import { Company } from '../../core/models/company.model';

@Component({
  selector: 'app-job-list',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './job-list.html',
  styleUrl: './job-list.scss',
})
export class JobList implements OnInit {
  private readonly jobProfileService = inject(JobProfileService);
  private readonly companyService = inject(CompanyService);
  private readonly auth = inject(AuthService);

  readonly jobProfiles = signal<JobProfile[]>([]);
  readonly companiesById = signal<Record<string, Company>>({});
  readonly loading = signal(true);
  /** Deleting a public row is admin-only; editing one is not. */
  readonly isAdmin = this.auth.isAdmin;
  readonly isModerator = this.auth.isModerator;

  /** Mirrors the server's `can_edit` — see the note on `CompanyList`. */
  canEdit(job: JobProfile): boolean {
    if (this.isModerator()) return true;
    return job.status === 'pending' && job.created_by === this.auth.currentUser()?.id;
  }

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.companyService.list().subscribe((companies) => {
      this.companiesById.set(Object.fromEntries(companies.map((c) => [c.id, c])));
      this.jobProfileService.list().subscribe((jobProfiles) => {
        this.jobProfiles.set(jobProfiles);
        this.loading.set(false);
      });
    });
  }

  companyName(companyId: string): string {
    return this.companiesById()[companyId]?.name ?? 'Unknown';
  }

  remove(id: string): void {
    this.jobProfileService.delete(id).subscribe(() => this.reload());
  }
}
