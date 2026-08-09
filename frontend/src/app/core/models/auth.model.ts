/**
 * Mirrors `ROLES` in the backend's user model.
 *
 * `moderator` was missing here, and its absence was not cosmetic: every
 * role check in the app compared against `'admin'`, so an account the API
 * happily let approve and reject public data was bounced out of the very
 * screen for doing it.
 */
export type Role = 'user' | 'moderator' | 'admin';

/** Mirrors `ModerationStatus` in the backend schemas. */
export type ModerationStatus = 'pending' | 'approved' | 'rejected';

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterRequest {
  full_name: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}
