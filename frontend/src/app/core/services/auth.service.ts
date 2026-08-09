import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, tap } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import {
  LoginRequest,
  PasswordChangeRequest,
  RegisterRequest,
  TokenPair,
} from '../models/auth.model';
import { User, UserUpdate } from '../models/user.model';

const ACCESS_TOKEN_KEY = 'jarvis.access_token';
const REFRESH_TOKEN_KEY = 'jarvis.refresh_token';

/**
 * Session state for the whole app.
 *
 * Tokens live in `localStorage` so a reload does not sign the user out. That
 * choice trades a little XSS exposure for usability; it is defensible here
 * because the API is same-origin-free (a separate host) and cookie auth would
 * need CSRF machinery this app does not otherwise have. If the threat model
 * tightens, the swap is confined to `read`/`persist` below.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly baseUrl = `${API_BASE_URL}/auth`;

  private readonly accessToken = signal<string | null>(read(ACCESS_TOKEN_KEY));
  private readonly refreshToken = signal<string | null>(read(REFRESH_TOKEN_KEY));

  readonly currentUser = signal<User | null>(null);
  readonly isAuthenticated = computed(() => this.accessToken() !== null);
  readonly isAdmin = computed(() => this.currentUser()?.role === 'admin');
  /**
   * Mirrors `User.is_moderator` on the backend — admins are moderators too.
   *
   * Use this for anything about *reviewing shared data*, and `isAdmin` only
   * for what genuinely needs an administrator: managing accounts and deleting
   * public rows.
   */
  readonly isModerator = computed(() => {
    const role = this.currentUser()?.role;
    return role === 'moderator' || role === 'admin';
  });

  token(): string | null {
    return this.accessToken();
  }

  register(data: RegisterRequest): Observable<User> {
    return this.http.post<User>(`${this.baseUrl}/register`, data);
  }

  login(data: LoginRequest): Observable<TokenPair> {
    return this.http
      .post<TokenPair>(`${this.baseUrl}/login`, data)
      .pipe(tap((tokens) => this.store(tokens)));
  }

  /**
   * Exchange the refresh token for a new pair.
   *
   * Returns the raw observable rather than swallowing errors: the interceptor
   * needs to distinguish "refreshed" from "session is genuinely over".
   */
  refresh(): Observable<TokenPair> {
    return this.http
      .post<TokenPair>(`${this.baseUrl}/refresh`, { refresh_token: this.refreshToken() })
      .pipe(tap((tokens) => this.store(tokens)));
  }

  loadCurrentUser(): Observable<User> {
    return this.http
      .get<User>(`${this.baseUrl}/me`)
      .pipe(tap((user) => this.currentUser.set(user)));
  }

  updateProfile(data: UserUpdate): Observable<User> {
    return this.http
      .patch<User>(`${this.baseUrl}/me`, data)
      .pipe(tap((user) => this.currentUser.set(user)));
  }

  /** Changing the password reissues tokens, because it revokes the old ones. */
  changePassword(data: PasswordChangeRequest): Observable<TokenPair> {
    return this.http
      .post<TokenPair>(`${this.baseUrl}/me/password`, data)
      .pipe(tap((tokens) => this.store(tokens)));
  }

  logout(redirect = true): void {
    this.accessToken.set(null);
    this.refreshToken.set(null);
    this.currentUser.set(null);
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    if (redirect) {
      void this.router.navigate(['/login']);
    }
  }

  private store(tokens: TokenPair): void {
    this.accessToken.set(tokens.access_token);
    this.refreshToken.set(tokens.refresh_token);
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token);
  }

  hasRefreshToken(): boolean {
    return this.refreshToken() !== null;
  }
}

function read(key: string): string | null {
  // Guards against server-side rendering, where localStorage is undefined.
  return typeof localStorage === 'undefined' ? null : localStorage.getItem(key);
}
