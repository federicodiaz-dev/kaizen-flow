export interface UserProfile {
  id: number;
  email: string;
  created_at: string;
  default_account: string | null;
}

export interface SessionResponse {
  user: UserProfile;
}
