import { ModerationStatus } from './auth.model';

export type GrowthTrajectory = 'declining' | 'stable' | 'growing' | 'hypergrowth';

export interface Company {
  id: string;
  name: string;
  /** Normalised name — the deduplication key. Server-derived, never sent. */
  slug: string;
  industry: string | null;
  growth_trajectory: GrowthTrajectory | null;
  website: string | null;
  status: ModerationStatus;
  created_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompanyCreate {
  name: string;
  industry?: string | null;
  growth_trajectory?: GrowthTrajectory | null;
  website?: string | null;
}

export type CompanyUpdate = Partial<CompanyCreate>;

/** The 409 body when a submission collides with an existing company. */
export interface DuplicateCompany {
  detail: string;
  existing: Company;
}
