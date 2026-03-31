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

  readonly form = this.fb.nonNullable.group({
    company_id: ['', Validators.required],
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

    if (this.jobProfileId) {
      this.jobProfileService
        .update(this.jobProfileId, {
          position_title: raw.position_title,
          experience_tier: (raw.experience_tier || null) as ExperienceTier | null,
          description: raw.description,
          location: raw.location || null,
          employment_type: raw.employment_type || null,
        })
        .subscribe(() => this.router.navigate(['/jobs']));
    } else {
      this.jobProfileService
        .create({
          company_id: raw.company_id,
          position_title: raw.position_title,
          experience_tier: (raw.experience_tier || null) as ExperienceTier | null,
          description: raw.description,
          location: raw.location || null,
          employment_type: raw.employment_type || null,
        })
        .subscribe(() => this.router.navigate(['/jobs']));
    }
  }
}
