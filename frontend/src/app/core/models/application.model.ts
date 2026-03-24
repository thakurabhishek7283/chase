import { Company } from './company.model';
import { JobProfile } from './job-profile.model';
import { Resume } from './resume.model';

export type Stage = 'applied' | 'interviewing' | 'offer' | 'archive';

export const STAGES: Stage[] = ['applied', 'interviewing', 'offer', 'archive'];

export const STAGE_LABELS: Record<Stage, string> = {
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  archive: 'Archive',
};

export interface Application {
  id: string;
  user_id: string;
  company_id: string;
  job_profile_id: string;
  resume_id: string;
  stage: Stage;
  board_position: number;
  stage_updated_at: string;
  applied_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApplicationWithDetails extends Application {
  company: Company;
  job_profile: JobProfile;
  resume: Resume;
}

export interface ApplicationCreate {
  user_id: string;
  company_id: string;
  job_profile_id: string;
  resume_id: string;
  stage?: Stage;
  board_position?: number;
  applied_date?: string | null;
  notes?: string | null;
}

export interface ApplicationStageUpdate {
  stage: Stage;
  board_position: number;
}
