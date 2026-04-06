export interface AccountSummary {
  key: string;
  label: string;
  source: string;
  user_id: number | null;
  scope: string | null;
  is_default: boolean;
}

export interface AccountsResponse {
  default_account: string;
  items: AccountSummary[];
}
