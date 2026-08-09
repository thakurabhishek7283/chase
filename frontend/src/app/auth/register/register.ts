import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';

/** Mirrors `min_password_length` in the backend settings. */
const MIN_PASSWORD_LENGTH = 12;

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './register.html',
  styleUrl: '../login/auth-form.scss',
})
export class Register {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly minLength = MIN_PASSWORD_LENGTH;
  readonly submitting = signal(false);
  readonly error = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    full_name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(MIN_PASSWORD_LENGTH)]],
  });

  submit(): void {
    if (this.form.invalid || this.submitting()) return;
    this.submitting.set(true);
    this.error.set(null);

    const { email, password } = this.form.getRawValue();
    this.auth.register(this.form.getRawValue()).subscribe({
      next: () => {
        // Sign in straight away — making a new user re-type credentials they
        // just chose serves no purpose.
        this.auth.login({ email, password }).subscribe({
          next: () =>
            this.auth.loadCurrentUser().subscribe({
              next: () => void this.router.navigate(['/resumes']),
              error: () => void this.router.navigate(['/resumes']),
            }),
          error: () => void this.router.navigate(['/login']),
        });
      },
      error: (err) => {
        this.error.set(this.messageFor(err));
        this.submitting.set(false);
      },
    });
  }

  private messageFor(err: unknown): string {
    const detail = (err as { error?: { detail?: unknown } })?.error?.detail;
    if (typeof detail === 'string') return detail;
    // A 422 body is a list of field errors, not a string.
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      return first?.msg ?? 'Please check the details you entered.';
    }
    return 'Could not create the account.';
  }
}
