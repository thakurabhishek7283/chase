import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { API_BASE_URL } from '../../core/api-config';
import { ResumeService } from '../../core/services/resume.service';
import { UserService } from '../../core/services/user.service';
import { Resume } from '../../core/models/resume.model';
import { User } from '../../core/models/user.model';

@Component({
  selector: 'app-resume-list',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './resume-list.html',
  styleUrl: './resume-list.scss',
})
export class ResumeList implements OnInit {
  private readonly resumeService = inject(ResumeService);
  private readonly userService = inject(UserService);

  readonly resumes = signal<Resume[]>([]);
  readonly usersById = signal<Record<string, User>>({});
  readonly loading = signal(true);

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.userService.list().subscribe((users) => {
      this.usersById.set(Object.fromEntries(users.map((u) => [u.id, u])));
      this.resumeService.list().subscribe((resumes) => {
        this.resumes.set(resumes);
        this.loading.set(false);
      });
    });
  }

  userName(userId: string): string {
    return this.usersById()[userId]?.full_name ?? 'Unknown';
  }

  pdfUrl(resumeId: string): string {
    return `${API_BASE_URL}/resumes/${resumeId}/pdf`;
  }

  remove(id: string): void {
    this.resumeService.delete(id).subscribe(() => this.reload());
  }
}
