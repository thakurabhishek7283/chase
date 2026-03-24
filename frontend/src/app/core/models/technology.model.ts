export interface Technology {
  id: string;
  name: string;
  category: string | null;
}

export interface TechnologyAttach {
  technology_name: string;
  category?: string | null;
}

export type RequirementLevel = 'required' | 'nice_to_have';

export interface JobProfileTechnologyAttach extends TechnologyAttach {
  requirement_level: RequirementLevel;
}
