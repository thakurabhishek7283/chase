import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { CompanyService } from '../../core/services/company.service';
import { GrowthTrajectory } from '../../core/models/company.model';

@Component({
  selector: 'app-company-form',
  standalone: true,
  imports: [ReactiveFormsModule],
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
  private companyId: string | null = null;

  readonly form = this.fb.nonNullable.group({
    name: ['', Validators.required],
    industry: [''],
    growth_trajectory: [''],
    website: [''],
  });

  ngOnInit(): void {
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

    const request = this.companyId
      ? this.companyService.update(this.companyId, payload)
      : this.companyService.create(payload);

    request.subscribe(() => this.router.navigate(['/companies']));
  }
}
