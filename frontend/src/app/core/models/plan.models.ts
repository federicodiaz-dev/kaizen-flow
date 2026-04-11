export interface PlanSummary {
  code: string;
  name: string;
  headline: string;
  status: string;
  price_monthly: number;
  currency: string;
  max_accounts: number;
  reply_assistant_limit: number | null;
  listing_doctor_limit: number | null;
}

export interface PlanCatalogItem {
  code: string;
  name: string;
  headline: string;
  description: string;
  price_monthly: number;
  currency: string;
  max_accounts: number;
  reply_assistant_limit: number | null;
  listing_doctor_limit: number | null;
  features: string[];
  sort_order: number;
}

export interface PlanCatalogResponse {
  plans: PlanCatalogItem[];
}
