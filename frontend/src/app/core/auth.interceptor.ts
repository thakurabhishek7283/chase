import {
  HttpErrorResponse,
  HttpEvent,
  HttpHandlerFn,
  HttpInterceptorFn,
  HttpRequest,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { Observable, Subject, switchMap, take, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { API_BASE_URL } from './api-config';
import { AuthService } from './services/auth.service';

/** Endpoints that must never carry (or retry with) a token. */
const PUBLIC_PATHS = ['/auth/login', '/auth/register', '/auth/refresh', '/health'];

/**
 * Shared refresh state.
 *
 * Without it, a page that fires several requests at once would hit 401 on all
 * of them and start a refresh per request. That was always wasteful; now that
 * the server rotates refresh tokens and treats a second use of one as theft,
 * it is actively harmful — the parallel refreshes would look exactly like a
 * stolen token being replayed and get the whole session revoked.
 *
 * The first failure refreshes; the rest wait here and then replay with
 * whatever token it produced. `null` means "in flight"; a failed refresh
 * publishes an *error* so the waiters terminate instead of hanging.
 */
let refreshing = false;
let refreshed = new Subject<string>();

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);

  if (PUBLIC_PATHS.some((path) => req.url.startsWith(`${API_BASE_URL}${path}`))) {
    return next(req);
  }

  const token = auth.token();
  const authorized = token ? withToken(req, token) : req;

  return next(authorized).pipe(
    catchError((error: unknown) => {
      const is401 = error instanceof HttpErrorResponse && error.status === 401;
      if (!is401 || !auth.hasRefreshToken()) {
        return throwError(() => error);
      }
      return retryAfterRefresh(req, next, auth);
    }),
  );
};

function retryAfterRefresh(
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
  auth: AuthService,
): Observable<HttpEvent<unknown>> {
  if (refreshing) {
    // Another request is already refreshing — wait for its result.
    return refreshed.pipe(
      take(1),
      switchMap((fresh) => next(withToken(req, fresh))),
    );
  }

  refreshing = true;
  // A fresh Subject per attempt. Reusing one across attempts means the error
  // that ends this session also permanently poisons the next one, since an
  // errored Subject stays errored forever.
  const waiters = refreshed;

  return auth.refresh().pipe(
    switchMap((tokens) => {
      refreshing = false;
      refreshed = new Subject<string>();
      waiters.next(tokens.access_token);
      waiters.complete();
      return next(withToken(req, tokens.access_token));
    }),
    catchError((error: unknown) => {
      // The refresh token is expired or was revoked — the session is over.
      // Waiters must be told: they were parked on a value that is never
      // coming, and without this they hang until the page is reloaded,
      // leaving their components stuck on a spinner forever.
      refreshing = false;
      refreshed = new Subject<string>();
      waiters.error(error);
      auth.logout();
      return throwError(() => error);
    }),
  );
}

function withToken(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}
