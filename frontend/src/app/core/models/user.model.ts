export interface User {
  id: string;
  full_name: string;
  email: string;
  current_title: string | null;
  career_goals: string | null;
  desired_salary_min: string | null;
  desired_salary_max: string | null;
  salary_currency: string;
  created_at: string;
  updated_at: string;
}

export interface UserCreate {
  full_name: string;
  email: string;
  current_title?: string | null;
  career_goals?: string | null;
  desired_salary_min?: string | null;
  desired_salary_max?: string | null;
  salary_currency?: string;
}

export interface UserUpdate {
  full_name?: string;
  email?: string;
  current_title?: string | null;
  career_goals?: string | null;
  desired_salary_min?: string | null;
  desired_salary_max?: string | null;
  salary_currency?: string;
}
