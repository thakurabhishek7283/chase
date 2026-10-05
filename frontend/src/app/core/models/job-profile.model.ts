import { ModerationStatus } from './auth.model';

export type ExperienceTier =
  'intern' | 'junior' | 'mid' | 'senior' | 'staff' | 'principal' | 'executive';

export interface JobProfile {
  id: string;
  company_id: string;
  /** The employer's requisition id. With `company_id`, identifies the posting. */
  external_job_id: string | null;
  position_title: string;
  experience_tier: ExperienceTier | null;
  description: string;
  location: string | null;
  employment_type: string | null;
  status: ModerationStatus;
  created_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobProfileCreate {
  company_id: string;
  external_job_id?: string | null;
  position_title: string;
  experience_tier?: ExperienceTier | null;
  description: string;
  location?: string | null;
  employment_type?: string | null;
}

export type JobProfileUpdate = Partial<Omit<JobProfileCreate, 'company_id'>>;

export interface DuplicateJobProfile {
  detail: string;
  existing: JobProfile;
}
