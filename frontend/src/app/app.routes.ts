import { Routes } from '@angular/router';

import { DashboardShell } from './layout/dashboard-shell/dashboard-shell';
import { KanbanBoard } from './kanban/kanban-board/kanban-board';
import { CompanyList } from './companies/company-list/company-list';
import { CompanyForm } from './companies/company-form/company-form';
import { JobList } from './jobs/job-list/job-list';
import { JobForm } from './jobs/job-form/job-form';
import { ResumeList } from './resumes/resume-list/resume-list';
import { ResumeForm } from './resumes/resume-form/resume-form';
import { AtsPanel } from './ats/ats-panel/ats-panel';
import { MatchList } from './matches/match-list/match-list';
import { UserList } from './users/user-list/user-list';
import { UserForm } from './users/user-form/user-form';

export const routes: Routes = [
  {
    path: '',
    component: DashboardShell,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'board' },
      { path: 'board', component: KanbanBoard },
      { path: 'companies', component: CompanyList },
      { path: 'companies/new', component: CompanyForm },
      { path: 'companies/:id/edit', component: CompanyForm },
      { path: 'jobs', component: JobList },
      { path: 'jobs/new', component: JobForm },
      { path: 'jobs/:id/edit', component: JobForm },
      { path: 'resumes', component: ResumeList },
      { path: 'resumes/new', component: ResumeForm },
      { path: 'resumes/:id/edit', component: ResumeForm },
      { path: 'ats', component: AtsPanel },
      { path: 'matches', component: MatchList },
      { path: 'users', component: UserList },
      { path: 'users/new', component: UserForm },
      { path: 'users/:id/edit', component: UserForm },
    ],
  },
];
