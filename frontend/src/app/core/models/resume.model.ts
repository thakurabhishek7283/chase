export type ContentFormat = 'markdown' | 'json';

export interface Resume {
  id: string;
  user_id: string;
  master_resume_id: string | null;
  title: string;
  content_format: ContentFormat;
  content: string;
  version_label: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeCreate {
  user_id: string;
  master_resume_id?: string | null;
  title: string;
  content_format?: ContentFormat;
  content: string;
  version_label?: string | null;
}

export type ResumeUpdate = Partial<Omit<ResumeCreate, 'user_id' | 'master_resume_id'>>;
