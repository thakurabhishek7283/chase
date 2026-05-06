import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AtsService } from '../../core/services/ats.service';
import { UserService } from '../../core/services/user.service';
import { JobMatch } from '../../core/models/ats.model';
import { User } from '../../core/models/user.model';

@Component({
  selector: 'app-match-list',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './match-list.html',
  styleUrl: './match-list.scss',
})
export class MatchList implements OnInit {
  private readonly atsService = inject(AtsService);
  private readonly userService = inject(UserService);

  readonly users = signal<User[]>([]);
  readonly selectedUserId = signal('');
  readonly matches = signal<JobMatch[]>([]);
  readonly loading = signal(false);
  readonly reindexing = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);

  ngOnInit(): void {
    this.userService.list().subscribe((users) => this.users.set(users));
  }

  percent(similarity: number): number {
    return Math.round(similarity * 100);
  }

  reindex(): void {
    this.reindexing.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.atsService.reindex().subscribe({
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
    const userId = this.selectedUserId();
    if (!userId) return;
    this.loading.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.atsService.jobMatches(userId).subscribe({
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
