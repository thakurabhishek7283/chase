import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { ResumeService } from '../../core/services/resume.service';
import { AppliedCorrection, LatexEngineStatus } from '../../core/models/resume.model';
import { detailFrom } from '../../core/http-error';

/**
 * The only way a resume enters the app.
 *
 * The wait is real — one model call to read the template, then a full compile to
 * prove the result works — so the screen says what is happening rather than
 * showing a spinner and hoping.
 *
 * When the upload lands, anything the intake pass had to change is shown before
 * navigating on. The stored master is not byte-identical to the file that was
 * picked, and the author is entitled to see exactly where it differs.
 */
@Component({
  selector: 'app-resume-upload',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './resume-upload.html',
  styleUrl: './resume-upload.scss',
})
export class ResumeUpload implements OnInit {
  private readonly resumes = inject(ResumeService);
  private readonly router = inject(Router);

  readonly title = signal('');
  readonly engine = signal('');
  readonly file = signal<File | null>(null);

  readonly status = signal<LatexEngineStatus | null>(null);
  readonly uploading = signal(false);
  readonly error = signal<string | null>(null);

  /** Set on success, so the corrections can be read before moving on. */
  readonly resumeId = signal<string | null>(null);
  readonly corrections = signal<AppliedCorrection[]>([]);
  readonly verdict = signal('');

  readonly canUpload = computed(() => !!this.title().trim() && !!this.file() && !this.uploading());

  /** Only engines that are actually installed; the rest would 503 on render. */
  readonly installedEngines = computed(() =>
    Object.entries(this.status()?.engines ?? {})
      .filter(([, available]) => available)
      .map(([name]) => name),
  );

  ngOnInit(): void {
    this.resumes.engineStatus().subscribe({
      next: (status) => this.status.set(status),
      error: () => this.status.set(null),
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const picked = input.files?.[0] ?? null;
    this.file.set(picked);
    this.error.set(null);
    if (picked && !this.title().trim()) {
      this.title.set(picked.name.replace(/\.tex$/i, ''));
    }
  }

  upload(): void {
    const file = this.file();
    if (!file || !this.canUpload()) return;

    this.uploading.set(true);
    this.error.set(null);

    this.resumes.upload(this.title().trim(), file, this.engine() || null).subscribe({
      next: (response) => {
        this.resumeId.set(response.resume_id);
        this.corrections.set(response.corrections);
        this.verdict.set(response.verdict);
        this.uploading.set(false);
        // Nothing was changed and there is nothing to read — go straight there.
        if (response.corrections.length === 0) {
          this.open();
        }
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'That file could not be accepted.'));
        this.uploading.set(false);
      },
    });
  }

  open(): void {
    const id = this.resumeId();
    if (id) {
      void this.router.navigate(['/resumes', id]);
    }
  }
}
