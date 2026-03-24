import { Company } from './company.model';
import { JobProfile } from './job-profile.model';

export type Severity = 'critical' | 'important' | 'nice_to_have';

export type StoppedBecause = 'target_reached' | 'no_further_gains' | 'max_iterations';

export interface MissingKeyword {
  keyword: string;
  severity: Severity;
  rationale: string;
}

export interface PhrasingSuggestion {
  original_text: string;
  suggested_text: string;
  reason: string;
  severity: Severity;
}

export interface ATSReport {
  match_score: number;
  summary: string;
  matched_keywords: string[];
  missing_keywords: MissingKeyword[];
  suggestions: PhrasingSuggestion[];
}

export interface ATSScoreRequest {
  resume_id: string;
  job_profile_id: string;
}

export interface ATSScoreResponse {
  resume_id: string;
  job_profile_id: string;
  report: ATSReport;
}

export interface AutofixRequest {
  resume_id: string;
  job_profile_id: string;
  target_score?: number;
  max_iterations?: number | null;
  save_as_tailored_version?: boolean;
}

export interface AutofixResult {
  original_score: number;
  final_score: number;
  iterations: number;
  revised_resume_markdown: string;
  applied_suggestions: PhrasingSuggestion[];
  final_report: ATSReport;
  stopped_because: StoppedBecause;
}

export interface AutofixResponse {
  resume_id: string;
  job_profile_id: string;
  saved_resume_id: string | null;
  result: AutofixResult;
}

export interface ResumeParseResult {
  filename: string;
  character_count: number;
  content_markdown: string;
}

export interface ReindexSummary {
  job_profiles_indexed: number;
  users_indexed: number;
}

export interface JobMatch {
  similarity: number;
  job_profile: JobProfile;
  company: Company;
}
