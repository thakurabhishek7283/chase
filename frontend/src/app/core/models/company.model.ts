import { Technology } from './technology.model';

export type GrowthTrajectory = 'declining' | 'stable' | 'growing' | 'hypergrowth';

export interface Company {
  id: string;
  name: string;
  industry: string | null;
  growth_trajectory: GrowthTrajectory | null;
  website: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompanyWithTechnologies extends Company {
  technologies: Technology[];
}

export interface CompanyCreate {
  name: string;
  industry?: string | null;
  growth_trajectory?: GrowthTrajectory | null;
  website?: string | null;
}

export type CompanyUpdate = Partial<CompanyCreate>;
