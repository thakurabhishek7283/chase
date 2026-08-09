import { Role } from './auth.model';

export interface User {
  id: string;
  full_name: string;
  email: string;
  role: Role;
  is_active: boolean;
  current_title: string | null;
  career_goals: string | null;
  desired_salary_min: string | null;
  desired_salary_max: string | null;
  salary_currency: string;
  created_at: string;
  updated_at: string;
}

/**
 * Admin-side provisioning only — ordinary signup goes through
 * `AuthService.register`. Note the absence of `role`: promotion is a separate,
 * admin-only endpoint so it can never ride along on a profile edit.
 */
export interface UserCreate {
  full_name: string;
  email: string;
  password: string;
  current_title?: string | null;
  career_goals?: string | null;
  desired_salary_min?: string | null;
  desired_salary_max?: string | null;
  salary_currency?: string;
}

export interface UserUpdate {
  full_name?: string;
  email?: string;
  /**
   * Required by `PATCH /auth/me` only when `email` actually changes — that
   * field is the sign-in identity, so moving it costs a re-authentication.
   * Ignored on every other edit.
   */
  current_password?: string;
  current_title?: string | null;
  career_goals?: string | null;
  desired_salary_min?: string | null;
  desired_salary_max?: string | null;
  salary_currency?: string;
}
