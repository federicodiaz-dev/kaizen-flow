import { PlanSummary } from './plan.models';


export interface UserProfile {
  id: number;
  email: string;
  username: string;
  created_at: string;
  is_first_visit: boolean;
  default_account: string | null;
  current_plan: PlanSummary | null;
}

export interface SessionResponse {
  user: UserProfile;
}
