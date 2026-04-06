export interface AccountSummary {
  key: string;
  label: string;
  source: string;
  user_id: number | null;
  scope: string | null;
  is_default: boolean;
  is_active: boolean;
}

export interface AccountsResponse {
  default_account: string | null;
  items: AccountSummary[];
}

export interface DefaultAccountResponse {
  default_account: string;
}
