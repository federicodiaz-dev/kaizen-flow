export interface UserProfile {
  id: number;
  email: string;
  created_at: string;
  is_first_visit: boolean;
  default_account: string | null;
}

export interface SessionResponse {
  user: UserProfile;
}
