import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { UserService } from '../../core/services/user.service';

@Component({
  selector: 'app-user-form',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './user-form.html',
  styleUrl: './user-form.scss',
})
export class UserForm implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly userService = inject(UserService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly isEdit = signal(false);
  private userId: string | null = null;

  readonly form = this.fb.nonNullable.group({
    full_name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    current_title: [''],
    career_goals: [''],
    desired_salary_min: [''],
    desired_salary_max: [''],
    salary_currency: ['USD'],
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.isEdit.set(true);
      this.userId = id;
      this.userService.get(id).subscribe((user) => {
        this.form.patchValue({
          full_name: user.full_name,
          email: user.email,
          current_title: user.current_title ?? '',
          career_goals: user.career_goals ?? '',
          desired_salary_min: user.desired_salary_min ?? '',
          desired_salary_max: user.desired_salary_max ?? '',
          salary_currency: user.salary_currency,
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
      full_name: raw.full_name,
      email: raw.email,
      current_title: raw.current_title || null,
      career_goals: raw.career_goals || null,
      desired_salary_min: raw.desired_salary_min || null,
      desired_salary_max: raw.desired_salary_max || null,
      salary_currency: raw.salary_currency || 'USD',
    };

    const request = this.userId
      ? this.userService.update(this.userId, payload)
      : this.userService.create(payload);

    request.subscribe(() => this.router.navigate(['/users']));
  }
}
