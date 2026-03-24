import { Technology } from './technology.model';

export type ExperienceTier =
  | 'intern'
  | 'junior'
  | 'mid'
  | 'senior'
  | 'staff'
  | 'principal'
  | 'executive';

export interface JobProfile {
  id: string;
  company_id: string;
  position_title: string;
  experience_tier: ExperienceTier | null;
  description: string;
  location: string | null;
  employment_type: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobProfileWithTechnologies extends JobProfile {
  technologies: Technology[];
}

export interface JobProfileCreate {
  company_id: string;
  position_title: string;
  experience_tier?: ExperienceTier | null;
  description: string;
  location?: string | null;
  employment_type?: string | null;
}

export type JobProfileUpdate = Partial<Omit<JobProfileCreate, 'company_id'>>;
