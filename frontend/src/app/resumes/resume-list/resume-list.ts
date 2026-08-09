import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ResumeService } from '../../core/services/resume.service';
import { ResumeSummary } from '../../core/models/resume.model';
import { detailFrom } from '../../core/http-error';

/**
 * Every resume the signed-in user has, masters with their versions under them.
 *
 * Deliberately thin: there is nothing to do to a resume from here except open
 * it, download it, or delete it. Everything else happens on the detail screen,
 * where the outline is in front of you.
 */
@Component({
  selector: 'app-resume-list',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './resume-list.html',
  styleUrl: './resume-list.scss',
})
export class ResumeList implements OnInit {
  private readonly resumes = inject(ResumeService);

  readonly all = signal<ResumeSummary[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly downloading = signal<string | null>(null);

  readonly masters = computed(() => this.all().filter((r) => !r.master_resume_id));

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    // The list is already the signed-in user's, so there is no owner column
    // to resolve and no user directory to fetch.
    this.loading.set(true);
    this.resumes.list().subscribe({
      next: (rows) => {
        this.all.set(rows);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Could not load resumes.');
        this.loading.set(false);
      },
    });
  }

  versionsOf(masterId: string): ResumeSummary[] {
    return this.all().filter((r) => r.master_resume_id === masterId);
  }

  downloadPdf(resume: ResumeSummary): void {
    this.downloading.set(resume.id);
    this.error.set(null);
    this.resumes.download(resume.id, 'pdf').subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${resume.title.replace(/[^\w-]+/g, '-') || 'resume'}.pdf`;
        link.click();
        URL.revokeObjectURL(url);
        this.downloading.set(null);
      },
      // The API explains *why* a document would not compile — the missing
      // \item, the engine mismatch, the line number. Swallowing that for a
      // generic sentence leaves the only actionable copy on the server.
      error: async (err) => {
        this.error.set(await detailFrom(err, 'Could not render that resume to PDF.'));
        this.downloading.set(null);
      },
    });
  }

  remove(id: string): void {
    this.resumes.delete(id).subscribe({
      next: () => this.reload(),
      error: async (err) =>
        this.error.set(await detailFrom(err, 'Could not delete that resume.')),
    });
  }
}
