import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AtsService } from '../../core/services/ats.service';
import { ResumeService } from '../../core/services/resume.service';
import { UserService } from '../../core/services/user.service';
import { User } from '../../core/models/user.model';

@Component({
  selector: 'app-resume-form',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './resume-form.html',
  styleUrl: './resume-form.scss',
})
export class ResumeForm implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly resumeService = inject(ResumeService);
  private readonly userService = inject(UserService);
  private readonly atsService = inject(AtsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly users = signal<User[]>([]);
  readonly isEdit = signal(false);
  readonly uploading = signal(false);
  readonly uploadError = signal<string | null>(null);
  readonly uploadNotice = signal<string | null>(null);
  private resumeId: string | null = null;

  /** Extract Markdown from a PDF and drop it into the content field. */
  onPdfSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    this.uploading.set(true);
    this.uploadError.set(null);
    this.uploadNotice.set(null);

    this.atsService.parsePdf(file).subscribe({
      next: (result) => {
        this.form.patchValue({ content: result.content_markdown });
        if (!this.form.getRawValue().title) {
          this.form.patchValue({ title: result.filename.replace(/\.pdf$/i, '') });
        }
        this.uploadNotice.set(
          `Extracted ${result.character_count} characters from ${result.filename}. Review before saving.`,
        );
        this.uploading.set(false);
        input.value = '';
      },
      error: (err) => {
        this.uploadError.set(err?.error?.detail ?? 'Could not read that PDF.');
        this.uploading.set(false);
        input.value = '';
      },
    });
  }

  readonly form = this.fb.nonNullable.group({
    user_id: ['', Validators.required],
    title: ['', Validators.required],
    version_label: [''],
    content: ['', Validators.required],
  });

  ngOnInit(): void {
    this.userService.list().subscribe((users) => this.users.set(users));

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.isEdit.set(true);
      this.resumeId = id;
      this.resumeService.get(id).subscribe((resume) => {
        this.form.patchValue({
          user_id: resume.user_id,
          title: resume.title,
          version_label: resume.version_label ?? '',
          content: resume.content,
        });
      });
    }
  }

  submit(): void {
    if (this.form.invalid) {
      return;
    }
    const raw = this.form.getRawValue();

    if (this.resumeId) {
      this.resumeService
        .update(this.resumeId, {
          title: raw.title,
          version_label: raw.version_label || null,
          content: raw.content,
        })
        .subscribe(() => this.router.navigate(['/resumes']));
    } else {
      this.resumeService
        .create({
          user_id: raw.user_id,
          title: raw.title,
          version_label: raw.version_label || null,
          content: raw.content,
        })
        .subscribe(() => this.router.navigate(['/resumes']));
    }
  }
}
