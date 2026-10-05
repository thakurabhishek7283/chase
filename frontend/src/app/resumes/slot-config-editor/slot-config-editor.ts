import { Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ResumeService } from '../../core/services/resume.service';
import { ResumeOutline, SlotConfigOut } from '../../core/models/resume.model';
import { detailFrom } from '../../core/http-error';

/**
 * Review and correct the boundary between a template and its content.
 *
 * This is where an inferred boundary gets a human's agreement. The backend
 * refuses a config that is structurally unsafe, but it cannot tell prose from a
 * date — only the author knows that argument 3 of their macro is a date range.
 * So the config the upload pass inferred arrives `confirmed: false` and stays
 * that way until someone presses Save here.
 *
 * There is no re-detect button. Detection happens once, at upload, as half of
 * the pass that also proved the document compiles; re-running it alone would
 * spend a model call on a vocabulary nothing had verified against a corrected
 * source. Correcting it by hand is what this panel is for.
 */
@Component({
  selector: 'app-slot-config-editor',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './slot-config-editor.html',
  styleUrl: './slot-config-editor.scss',
})
export class SlotConfigEditor {
  private readonly resumes = inject(ResumeService);

  readonly resumeId = input.required<string>();
  readonly outline = input.required<ResumeOutline>();

  /** Emitted whenever the stored config changes, so the parent can re-read. */
  readonly changed = output<ResumeOutline>();

  readonly open = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  /** A working copy; nothing is sent until Save. */
  readonly draft = signal<SlotConfigOut | null>(null);

  readonly config = computed(() => this.draft() ?? this.outline().slot_config);
  readonly needsReview = computed(() => !this.outline().slot_config.confirmed);

  readonly sourceLabel = computed(() => {
    switch (this.outline().slot_config.source) {
      case 'discovered':
        return 'Detected automatically';
      case 'author':
        return 'Set by you';
      default:
        return 'Built-in shapes';
    }
  });

  toggle(): void {
    this.open.update((open) => !open);
    if (this.open() && !this.draft()) {
      this.draft.set(structuredClone(this.outline().slot_config));
    }
  }

  // --- draft edits ----------------------------------------------------------

  private edit(change: (config: SlotConfigOut) => void): void {
    const next = structuredClone(this.config());
    change(next);
    this.draft.set(next);
  }

  addBulletMacro(): void {
    this.edit((c) => c.bullet_macros.push({ name: '' }));
  }

  removeBulletMacro(index: number): void {
    this.edit((c) => c.bullet_macros.splice(index, 1));
  }

  setBulletMacro(index: number, name: string): void {
    this.edit((c) => (c.bullet_macros[index].name = name));
  }

  addFieldMacro(): void {
    this.edit((c) => c.field_macros.push({ name: '', arity: 1, content_arg: 1, label: 'field' }));
  }

  removeFieldMacro(index: number): void {
    this.edit((c) => c.field_macros.splice(index, 1));
  }

  setFieldMacro(index: number, key: 'name' | 'label', value: string): void {
    this.edit((c) => (c.field_macros[index][key] = value));
  }

  setFieldNumber(index: number, key: 'arity' | 'content_arg', value: number): void {
    this.edit((c) => (c.field_macros[index][key] = Math.max(1, Math.trunc(value || 1))));
  }

  setList(key: 'section_macros' | 'environments', value: string): void {
    const names = value
      .split(',')
      .map((name) => name.trim().replace(/^\\/, ''))
      .filter(Boolean);
    this.edit((c) => (c[key] = names));
  }

  joined(key: 'section_macros' | 'environments'): string {
    return this.config()[key].join(', ');
  }

  discard(): void {
    this.draft.set(null);
    this.error.set(null);
  }

  // --- persistence ----------------------------------------------------------

  save(): void {
    this.run(this.resumes.setSlotConfig(this.resumeId(), this.config()));
  }

  /** Accept the proposal exactly as detected, with no edits. */
  confirmAsIs(): void {
    this.run(this.resumes.setSlotConfig(this.resumeId(), this.outline().slot_config));
  }

  reset(): void {
    this.run(this.resumes.setSlotConfig(this.resumeId(), null));
  }

  private run(request: ReturnType<ResumeService['setSlotConfig']>): void {
    this.busy.set(true);
    this.error.set(null);
    request.subscribe({
      next: (outline) => {
        this.draft.set(null);
        this.busy.set(false);
        this.changed.emit(outline);
      },
      error: async (err) => {
        this.error.set(await detailFrom(err, 'That configuration was rejected.'));
        this.busy.set(false);
      },
    });
  }
}
