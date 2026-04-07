export type ListingDoctorJobState =
  | 'queued'
  | 'running'
  | 'partial'
  | 'completed'
  | 'failed'
  | 'interrupted';

export type ListingDoctorStepState =
  | 'pending'
  | 'running'
  | 'completed'
  | 'skipped'
  | 'failed';

export type ListingDoctorTracePhase =
  | 'started'
  | 'completed'
  | 'failed'
  | 'info';

export interface ListingDoctorJobRequest {
  item_id: string;
  site_id?: string | null;
  include_copywriter?: boolean;
  competitor_limit?: number;
  search_depth?: number;
}

export interface ListingDoctorProgressStep {
  key: string;
  label: string;
  status: ListingDoctorStepState;
  message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ListingDoctorTraceEntry {
  sequence: number;
  timestamp: string;
  agent: string;
  node: string;
  phase: ListingDoctorTracePhase;
  message: string;
  details: Record<string, unknown> | unknown[] | string | null;
}

export interface ListingDoctorListingSummary {
  item_id: string;
  title: string;
  status: string | null;
  category_id: string | null;
  category_name: string | null;
  site_id: string | null;
  currency_id: string | null;
  price: number | null;
  sold_quantity: number | null;
  available_quantity: number | null;
  condition: string | null;
  listing_type_id: string | null;
  listing_exposure: string | null;
  health: number | null;
  health_actions: string[];
  brand: string | null;
  product_type: string | null;
  key_attributes: string[];
  missing_attributes: string[];
  attributes_count: number;
  pictures_count: number;
  description_present: boolean;
  description_length: number;
  thumbnail: string | null;
  permalink: string | null;
  last_updated: string | null;
}

export interface ListingDoctorMarketSummary {
  total_candidates: number;
  shortlisted_competitors: number;
  query_count: number;
  median_price: number | null;
  min_price: number | null;
  max_price: number | null;
  priced_competitors: number;
  detailed_competitors: number;
  benchmark_confidence: 'low' | 'medium' | 'high';
  price_benchmark_confidence: 'low' | 'medium' | 'high';
  dominant_keywords: string[];
  dominant_brands: string[];
  search_queries: string[];
}

export interface ListingDoctorScores {
  overall: number;
  title: number;
  price: number;
  attributes: number;
  description: number;
  competitiveness: number;
  opportunity: number;
}

export interface ListingDoctorCompetitorSnapshot {
  item_id: string;
  title: string;
  price: number | null;
  currency_id: string | null;
  sold_quantity: number | null;
  status: string | null;
  brand: string | null;
  condition: string | null;
  listing_type_id: string | null;
  listing_exposure: string | null;
  health: number | null;
  attributes_count: number;
  description_present: boolean;
  recurrence: number;
  average_position: number | null;
  similarity_score: number;
  strength_score: number;
  benchmark_score: number;
  growth_proxy: number | null;
  selection_reason: string;
  signals: string[];
  thumbnail: string | null;
  permalink: string | null;
  last_updated: string | null;
}

export interface ListingDoctorFindings {
  strengths: string[];
  weaknesses: string[];
  missing_attributes: string[];
  pricing_position: string[];
  title_gaps: string[];
  description_gaps: string[];
}

export interface ListingDoctorAction {
  title: string;
  summary: string;
  priority: 'high' | 'medium' | 'low';
  impact: 'high' | 'medium' | 'low';
  effort: 'low' | 'medium' | 'high';
  tags: string[];
  evidence: string[];
}

export interface ListingDoctorAiSuggestions {
  suggested_titles: string[];
  suggested_description: string;
  positioning_strategy: string;
}

export interface ListingDoctorEvidence {
  factual_points: string[];
  proxy_points: string[];
  uncertainties: string[];
}

export interface ListingDoctorResult {
  listing: ListingDoctorListingSummary;
  market_summary: ListingDoctorMarketSummary;
  scores: ListingDoctorScores;
  executive_summary: string;
  detailed_diagnosis: string[];
  competitor_snapshot: ListingDoctorCompetitorSnapshot[];
  findings: ListingDoctorFindings;
  actions: ListingDoctorAction[];
  ai_suggestions: ListingDoctorAiSuggestions;
  evidence: ListingDoctorEvidence;
  generated_at: string;
  account_key: string;
  site_id: string;
  warnings: string[];
  execution_trace: ListingDoctorTraceEntry[];
  log_file_path: string | null;
}

export interface ListingDoctorJobAccepted {
  job_id: string;
  status: ListingDoctorJobState;
  created_at: string;
  updated_at: string;
  account_key: string;
  site_id: string;
  item_id: string;
  steps: ListingDoctorProgressStep[];
  trace: ListingDoctorTraceEntry[];
  log_file_path: string | null;
}

export interface ListingDoctorJobStatus extends ListingDoctorJobAccepted {
  include_copywriter: boolean;
  competitor_limit: number;
  search_depth: number;
  error_message: string | null;
  warnings: string[];
  result: ListingDoctorResult | null;
}
