import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { AuthService } from '../core/services/auth.service';

const MIN_PASSWORD_LENGTH = 12;

/**
 * Self-service account settings.
 *
 * Career goals live here rather than on an admin user form because they are
 * the input to job matching — the one profile field the user changes often.
 */
@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './profile.html',
  styleUrl: './profile.scss',
})
export class Profile implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);

  readonly currentUser = this.auth.currentUser;
  readonly minLength = MIN_PASSWORD_LENGTH;

  readonly savingProfile = signal(false);
  readonly profileNotice = signal<string | null>(null);
  readonly profileError = signal<string | null>(null);

  readonly savingPassword = signal(false);
  readonly passwordNotice = signal<string | null>(null);
  readonly passwordError = signal<string | null>(null);

  readonly profileForm = this.fb.nonNullable.group({
    full_name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    // Only sent — and only required — when the address actually changes.
    current_password: [''],
    current_title: [''],
    career_goals: [''],
  });

  /** Drives the password prompt that appears once the email field is edited. */
  readonly emailChanged = computed(() => {
    const typed = this.emailValue().trim().toLowerCase();
    const current = this.currentUser()?.email.trim().toLowerCase();
    return typed.length > 0 && current !== undefined && typed !== current;
  });

  private readonly emailValue = toSignal(this.profileForm.controls.email.valueChanges, {
    initialValue: this.profileForm.controls.email.value,
  });

  readonly passwordForm = this.fb.nonNullable.group({
    current_password: ['', Validators.required],
    new_password: ['', [Validators.required, Validators.minLength(MIN_PASSWORD_LENGTH)]],
  });

  ngOnInit(): void {
    const user = this.currentUser();
    if (user) {
      this.profileForm.patchValue({
        full_name: user.full_name,
        email: user.email,
        current_title: user.current_title ?? '',
        career_goals: user.career_goals ?? '',
      });
    }
  }

  saveProfile(): void {
    if (this.profileForm.invalid || this.savingProfile()) return;
    this.savingProfile.set(true);
    this.profileNotice.set(null);
    this.profileError.set(null);

    const raw = this.profileForm.getRawValue();
    const movingEmail = this.emailChanged();
    if (movingEmail && !raw.current_password) {
      this.profileError.set('Enter your current password to change your sign-in email.');
      this.savingProfile.set(false);
      return;
    }

    this.auth
      .updateProfile({
        full_name: raw.full_name,
        email: raw.email,
        // Omitted entirely on an ordinary edit, so a saved profile never
        // carries a password it did not need.
        ...(movingEmail ? { current_password: raw.current_password } : {}),
        current_title: raw.current_title || null,
        career_goals: raw.career_goals || null,
      })
      .subscribe({
        next: () => {
          this.profileNotice.set(
            movingEmail
              ? 'Profile saved. Sign in with your new email next time.'
              : 'Profile saved.',
          );
          this.profileForm.controls.current_password.setValue('');
          this.savingProfile.set(false);
        },
        error: (err) => {
          this.profileError.set(err?.error?.detail ?? 'Could not save your profile.');
          this.savingProfile.set(false);
        },
      });
  }

  changePassword(): void {
    if (this.passwordForm.invalid || this.savingPassword()) return;
    this.savingPassword.set(true);
    this.passwordNotice.set(null);
    this.passwordError.set(null);

    this.auth.changePassword(this.passwordForm.getRawValue()).subscribe({
      next: () => {
        // The server reissues tokens, so this session survives while every
        // other one is revoked.
        this.passwordNotice.set('Password changed. Other sessions have been signed out.');
        this.passwordForm.reset();
        this.savingPassword.set(false);
      },
      error: (err) => {
        this.passwordError.set(err?.error?.detail ?? 'Could not change your password.');
        this.savingPassword.set(false);
      },
    });
  }

  signOutEverywhere(): void {
    this.auth.logout();
  }
}
