export interface UserProfile {
  id: string;
  email: string;
  created_at: string;
  is_first_visit: boolean;
  default_account: string | null;
}

export interface WorkspaceProfile {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface SubscriptionProfile {
  status: string;
  plan_code: string | null;
  plan_name: string | null;
  started_at: string | null;
  updated_at: string | null;
  expires_at: string | null;
  is_active: boolean;
}

export interface SessionResponse {
  user: UserProfile;
  workspace: WorkspaceProfile;
  subscription: SubscriptionProfile;
  csrf_token: string | null;
}
