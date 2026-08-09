import { Company } from './company.model';
import { JobProfile } from './job-profile.model';

export interface ReindexSummary {
  job_profiles_indexed: number;
  users_indexed: number;
}

export interface JobMatch {
  similarity: number;
  job_profile: JobProfile;
  company: Company;
}
