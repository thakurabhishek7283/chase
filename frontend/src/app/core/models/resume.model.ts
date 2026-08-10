/**
 * Shapes for resumes and their outlines — see backend `app/schemas/resume.py`.
 *
 * Two ideas are worth knowing before reading the components:
 *
 * - **Slots are addressed by id** (`g1`, `r1`), and those ids are *positional*.
 *   `content_hash` is what proves an edit still refers to the text it was
 *   written against; the review stores the hashes it was built from, so a master
 *   that moved on comes back as a 409 rather than a splice into the wrong bullet.
 * - **`template_hash` covers everything outside the slots.** A master and every
 *   version finalized from it share it. The UI shows it so the promise is
 *   checkable rather than merely asserted.
 *
 * There is no `ResumeCreate`. Content enters through the upload endpoint only.
 */

export type LatexEngine = 'latexmk' | 'pdflatex' | 'xelatex' | 'lualatex';

export interface Resume {
  id: string;
  user_id: string;
  master_resume_id: string | null;
  title: string;
  content: string;
  version_label: string | null;
  latex_engine: string | null;
  created_at: string;
  updated_at: string;
}

/** A resume without its source — what the list screen gets. */
export interface ResumeSummary {
  id: string;
  master_resume_id: string | null;
  title: string;
  version_label: string | null;
  latex_engine: string | null;
  created_at: string;
  updated_at: string;
}

// --- the slot vocabulary ---------------------------------------------------

export interface BulletMacroOut {
  name: string;
}

export interface FieldMacroOut {
  name: string;
  arity: number;
  content_arg: number;
  label: string;
}

export interface ListPairOut {
  start: string;
  end: string;
}

export type SlotConfigSource = 'builtin' | 'discovered' | 'author';

export interface SlotConfigOut {
  section_macros: string[];
  environments: string[];
  bullet_macros: BulletMacroOut[];
  list_pairs: ListPairOut[];
  field_macros: FieldMacroOut[];
  source: SlotConfigSource;
  confirmed: boolean;
}

// --- the outline -----------------------------------------------------------

export interface BulletOut {
  id: string;
  latex: string;
  content_hash: string;
}

export interface ItemGroupOut {
  id: string;
  kind: string;
  bullets: BulletOut[];
  content_hash: string;
}

/** `origin: 'field'` means the parser inferred this from a configured macro. */
export interface MarkedRegionOut {
  id: string;
  label: string;
  latex: string;
  content_hash: string;
  origin: 'marker' | 'field';
}

export interface SectionOut {
  id: string;
  heading: string;
  editable: boolean;
  groups: ItemGroupOut[];
  regions: MarkedRegionOut[];
}

export interface ResumeOutline {
  resume_id: string | null;
  sections: SectionOut[];
  group_count: number;
  bullet_count: number;
  region_count: number;
  frozen_sections: string[];
  latex_engine: string | null;
  engine_available: boolean;
  engine_warning: string | null;
  template_hash: string;
  slot_config: SlotConfigOut;
}

// --- upload ----------------------------------------------------------------

/** One fix the intake pass made. Shown because the stored master is not the file. */
export interface AppliedCorrection {
  find: string;
  replace: string;
  reason: string;
}

export interface ResumeUploadResponse {
  resume_id: string;
  title: string;
  corrections: AppliedCorrection[];
  verdict: string;
  outline: ResumeOutline;
}

export interface LatexEngineStatus {
  available: boolean;
  engine: string;
  version: string | null;
  detail: string | null;
  engines: Record<string, boolean>;
}
