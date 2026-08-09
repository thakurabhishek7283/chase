import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { MatchingService } from '../../core/services/matching.service';
import { AuthService } from '../../core/services/auth.service';
import { JobMatch } from '../../core/models/matching.model';

@Component({
  selector: 'app-match-list',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './match-list.html',
  styleUrl: './match-list.scss',
})
export class MatchList implements OnInit {
  private readonly matching = inject(MatchingService);
  private readonly auth = inject(AuthService);

  readonly currentUser = this.auth.currentUser;
  readonly isAdmin = this.auth.isAdmin;
  readonly matches = signal<JobMatch[]>([]);
  readonly loading = signal(false);
  readonly reindexing = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);

  /** Matching runs against the signed-in user's own career goals. */
  readonly hasGoals = signal(false);

  ngOnInit(): void {
    this.hasGoals.set(Boolean(this.currentUser()?.career_goals));
    if (this.hasGoals()) {
      this.loadMatches();
    }
  }

  percent(similarity: number): number {
    return Math.round(similarity * 100);
  }

  reindex(): void {
    this.reindexing.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.matching.reindex().subscribe({
      next: (summary) => {
        this.notice.set(
          `Indexed ${summary.job_profiles_indexed} job profile(s) and ${summary.users_indexed} user goal(s).`,
        );
        this.reindexing.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? 'Reindex failed.');
        this.reindexing.set(false);
      },
    });
  }

  loadMatches(): void {
    const user = this.currentUser();
    if (!user) return;
    this.loading.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.matching.jobMatches(user.id).subscribe({
      next: (matches) => {
        this.matches.set(matches);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? 'Could not load matches.');
        this.matches.set([]);
        this.loading.set(false);
      },
    });
  }
}
