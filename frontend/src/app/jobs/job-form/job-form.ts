import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { CompanyService } from '../../core/services/company.service';
import { JobProfileService } from '../../core/services/job-profile.service';
import { Company } from '../../core/models/company.model';
import { ExperienceTier } from '../../core/models/job-profile.model';

@Component({
  selector: 'app-job-form',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './job-form.html',
  styleUrl: './job-form.scss',
})
export class JobForm implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly companyService = inject(CompanyService);
  private readonly jobProfileService = inject(JobProfileService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly companies = signal<Company[]>([]);
  readonly isEdit = signal(false);
  readonly experienceTiers: ExperienceTier[] = [
    'intern',
    'junior',
    'mid',
    'senior',
    'staff',
    'principal',
    'executive',
  ];
  private jobProfileId: string | null = null;

  readonly duplicate = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    company_id: ['', Validators.required],
    // With `company_id`, this is the posting's identity. Optional because not
    // every listing shows one — the server falls back to title + location.
    external_job_id: [''],
    position_title: ['', Validators.required],
    experience_tier: [''],
    description: ['', Validators.required],
    location: [''],
    employment_type: [''],
  });

  ngOnInit(): void {
    this.companyService.list().subscribe((companies) => this.companies.set(companies));

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.isEdit.set(true);
      this.jobProfileId = id;
      this.jobProfileService.get(id).subscribe((job) => {
        this.form.patchValue({
          company_id: job.company_id,
          external_job_id: job.external_job_id ?? '',
          position_title: job.position_title,
          experience_tier: job.experience_tier ?? '',
          description: job.description,
          location: job.location ?? '',
          employment_type: job.employment_type ?? '',
        });
      });
    }
  }

  submit(): void {
    if (this.form.invalid) {
      return;
    }
    const raw = this.form.getRawValue();
    this.duplicate.set(null);

    const payload = {
      external_job_id: raw.external_job_id.trim() || null,
      position_title: raw.position_title,
      experience_tier: (raw.experience_tier || null) as ExperienceTier | null,
      description: raw.description,
      location: raw.location || null,
      employment_type: raw.employment_type || null,
    };

    const request = this.jobProfileId
      ? this.jobProfileService.update(this.jobProfileId, payload)
      : this.jobProfileService.create({ ...payload, company_id: raw.company_id });

    request.subscribe({
      next: () => void this.router.navigate(['/jobs']),
      error: (err) => this.duplicate.set(this.conflictMessage(err)),
    });
  }

  /**
   * Turn the 409 body into something actionable.
   *
   * The server sends the colliding row along with the message, so the user
   * learns *which* posting already covers this one rather than just being told
   * no.
   */
  private conflictMessage(err: unknown): string {
    const response = err as { status?: number; error?: { detail?: unknown } };
    if (response?.status !== 409) {
      return 'Could not save this job profile.';
    }
    const detail = response.error?.detail as { detail?: string } | string | undefined;
    if (typeof detail === 'string') return detail;
    return detail?.detail ?? 'A posting with this identity already exists.';
  }
}
