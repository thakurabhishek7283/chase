import { Routes } from '@angular/router';

import { adminGuard, authGuard, moderatorGuard } from './core/auth.guard';
import { DashboardShell } from './layout/dashboard-shell/dashboard-shell';
import { Login } from './auth/login/login';
import { Register } from './auth/register/register';
import { CompanyList } from './companies/company-list/company-list';
import { CompanyForm } from './companies/company-form/company-form';
import { JobList } from './jobs/job-list/job-list';
import { JobForm } from './jobs/job-form/job-form';
import { ResumeList } from './resumes/resume-list/resume-list';
import { ResumeUpload } from './resumes/resume-upload/resume-upload';
import { MatchList } from './matches/match-list/match-list';
import { Profile } from './profile/profile';
import { ModerationQueue } from './admin/moderation-queue/moderation-queue';
import { UserList } from './users/user-list/user-list';
import { UserForm } from './users/user-form/user-form';

export const routes: Routes = [
  { path: 'login', component: Login },
  { path: 'register', component: Register },
  {
    path: '',
    component: DashboardShell,
    // One guard on the parent covers every child, so a new page cannot be
    // added unprotected by forgetting a line.
    canActivate: [authGuard],
    children: [
      // Resumes are the landing page. The app is a resume optimizer with a job
      // list attached, and signing in used to drop you on a pipeline board that
      // no part of the tailoring flow ever read from or wrote to.
      { path: '', pathMatch: 'full', redirectTo: 'resumes' },
      { path: 'companies', component: CompanyList },
      { path: 'companies/new', component: CompanyForm },
      { path: 'companies/:id/edit', component: CompanyForm },
      { path: 'jobs', component: JobList },
      { path: 'jobs/new', component: JobForm },
      { path: 'jobs/:id/edit', component: JobForm },
      { path: 'resumes', component: ResumeList },
      { path: 'resumes/upload', component: ResumeUpload },
      // The whole resume workflow on one screen: outline, slot config, review,
      // and the patch list. A tailored child opens in the same view — it is a
      // readable document in its own right, it just cannot start a review.
      //
      // Lazy-loaded, unlike its neighbours: this screen and its editors are the
      // largest feature in the app and most sessions never open them, so
      // eager-loading them pushed the initial bundle past its budget.
      {
        path: 'resumes/:id',
        loadComponent: () =>
          import('./resumes/resume-detail/resume-detail').then((m) => m.ResumeDetail),
      },
      { path: 'matches', component: MatchList },
      { path: 'profile', component: Profile },
      // Role-gated. The guard is the real boundary; hiding the nav links is
      // only cosmetic, and the API refuses these regardless.
      //
      // Moderation is deliberately the looser of the two: approving and
      // rejecting is exactly what the moderator role exists for, and the
      // backend has allowed it all along.
      { path: 'moderation', component: ModerationQueue, canActivate: [moderatorGuard] },
      { path: 'users', component: UserList, canActivate: [adminGuard] },
      { path: 'users/new', component: UserForm, canActivate: [adminGuard] },
      { path: 'users/:id/edit', component: UserForm, canActivate: [adminGuard] },
    ],
  },
  { path: '**', redirectTo: '' },
];
