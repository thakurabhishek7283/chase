import { inject } from '@angular/core';
import { CanActivateFn, GuardResult, Router } from '@angular/router';
import { catchError, isObservable, map, of } from 'rxjs';

import { AuthService } from './services/auth.service';

/**
 * Require a session, and make sure `currentUser` is populated before the route
 * renders.
 *
 * The user is fetched here rather than in each component because the shell and
 * the role guards all need the role, and re-fetching it per component would
 * make the nav flicker between roles on every navigation.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const rejected = () =>
    router.createUrlTree(['/login'], { queryParams: { redirect: state.url } });

  if (!auth.isAuthenticated()) {
    return rejected();
  }
  if (auth.currentUser()) {
    return true;
  }
  return auth.loadCurrentUser().pipe(
    map(() => true),
    // A stored token that the server rejects is no session at all.
    catchError(() => of(rejected())),
  );
};

/**
 * Build a guard that runs `authGuard` first and then checks a role.
 *
 * The signed-in check resolves either synchronously or asynchronously
 * depending on whether the user is already loaded, and each role guard
 * handling both shapes itself is how the second one ends up subtly different
 * from the first.
 */
function roleGuard(allowed: (auth: AuthService) => boolean): CanActivateFn {
  return (route, state) => {
    const auth = inject(AuthService);
    const router = inject(Router);

    // Bounced to the resume list rather than to /login: the session is
    // perfectly valid, it simply does not carry this role, and sending someone
    // to a sign-in form they have already completed explains nothing.
    const check = (): GuardResult => (allowed(auth) ? true : router.createUrlTree(['/resumes']));

    const signedIn = authGuard(route, state);
    if (signedIn === true) {
      return check();
    }
    if (isObservable(signedIn)) {
      return signedIn.pipe(map((result) => (result === true ? check() : result)));
    }
    return signedIn;
  };
}

/** Reviewing community-contributed data: moderators and admins. */
export const moderatorGuard = roleGuard((auth) => auth.isModerator());

/** Account management and other genuinely administrative screens. */
export const adminGuard = roleGuard((auth) => auth.isAdmin());
