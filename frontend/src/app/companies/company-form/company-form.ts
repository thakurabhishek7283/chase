import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { debounceTime, distinctUntilChanged, filter, switchMap } from 'rxjs';

import { CompanyService } from '../../core/services/company.service';
import { Company, GrowthTrajectory } from '../../core/models/company.model';

@Component({
  selector: 'app-company-form',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './company-form.html',
  styleUrl: './company-form.scss',
})
export class CompanyForm implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly companyService = inject(CompanyService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly growthOptions: GrowthTrajectory[] = ['declining', 'stable', 'growing', 'hypergrowth'];
  readonly isEdit = signal(false);
  /** An already-listed company matching what has been typed so far. */
  readonly existing = signal<Company | null>(null);
  readonly error = signal<string | null>(null);
  private companyId: string | null = null;

  readonly form = this.fb.nonNullable.group({
    name: ['', Validators.required],
    industry: [''],
    growth_trajectory: [''],
    website: [''],
  });

  ngOnInit(): void {
    // Warn about a collision while the user is still typing the name, rather
    // than after they have filled in every other field and earned a 409.
    this.form.controls.name.valueChanges
      .pipe(
        debounceTime(350),
        distinctUntilChanged(),
        filter((name) => !this.companyId && name.trim().length > 1),
        switchMap((name) => this.companyService.lookup(name)),
      )
      .subscribe({
        next: (match) => this.existing.set(match),
        // A failed lookup is only a missing hint; the server still enforces
        // uniqueness on submit.
        error: () => this.existing.set(null),
      });

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.isEdit.set(true);
      this.companyId = id;
      this.companyService.get(id).subscribe((company) => {
        this.form.patchValue({
          name: company.name,
          industry: company.industry ?? '',
          growth_trajectory: company.growth_trajectory ?? '',
          website: company.website ?? '',
        });
      });
    }
  }

  submit(): void {
    if (this.form.invalid) {
      return;
    }
    const raw = this.form.getRawValue();
    const payload = {
      name: raw.name,
      industry: raw.industry || null,
      growth_trajectory: (raw.growth_trajectory || null) as GrowthTrajectory | null,
      website: raw.website || null,
    };

    this.error.set(null);
    const request = this.companyId
      ? this.companyService.update(this.companyId, payload)
      : this.companyService.create(payload);

    request.subscribe({
      next: () => void this.router.navigate(['/companies']),
      error: (err) => this.error.set(this.messageFor(err)),
    });
  }

  private messageFor(err: unknown): string {
    const response = err as { status?: number; error?: { detail?: unknown } };
    const detail = response?.error?.detail as { detail?: string } | string | undefined;
    if (response?.status === 409) {
      return typeof detail === 'string'
        ? detail
        : (detail?.detail ?? 'That company is already listed.');
    }
    if (response?.status === 403) {
      return typeof detail === 'string' ? detail : 'You cannot edit this company.';
    }
    return 'Could not save this company.';
  }
}
