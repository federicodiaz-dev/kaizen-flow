export interface MarketTrendReportRequest {
  natural_query: string;
  site_id?: string | null;
  limit?: number;
}

export interface MarketTrendResolutionNote {
  stage: 'category_predictor' | 'search_fallback' | 'public_listing_inference';
  query_used: string;
  status: 'ok' | 'empty' | 'error';
  suggestion_count?: number | null;
  category_count?: number | null;
  message?: string | null;
}

export interface MarketResolvedCategory {
  category_id: string;
  category_name?: string | null;
  domain_id?: string | null;
  domain_name?: string | null;
  resolved_by: string;
  query_used: string;
  search_hit_count?: number | null;
  fallback_titles: string[];
  category_path: string[];
  category_depth: number;
  is_low_signal_category: boolean;
}

export interface MarketPriceStats {
  min?: number | null;
  max?: number | null;
  avg?: number | null;
  median?: number | null;
}

export interface MarketSampleResult {
  id?: string | null;
  title?: string | null;
  price?: number | null;
  currency_id?: string | null;
  sold_quantity?: number | null;
  permalink?: string | null;
}

export interface MarketOpportunityEvidence {
  search_scope: 'category' | 'site' | 'web_listing' | 'web_category_listing';
  total_results?: number | null;
  sample_result_count: number;
  matching_title_count: number;
  price_stats: MarketPriceStats;
  avg_sold_quantity?: number | null;
  sample_titles: string[];
  sample_results: MarketSampleResult[];
}

export interface MarketValidatedOpportunity {
  keyword: string;
  category_id?: string | null;
  category_name?: string | null;
  category_path: string[];
  trend_bucket: string;
  trend_rank: number;
  validation_status: 'validated';
  specificity_score: number;
  evidence_score: number;
  ranking_score: number;
  justification: string;
  risk_flags: string[];
  market_evidence: MarketOpportunityEvidence;
}

export interface MarketDiscardedSignal {
  keyword?: string | null;
  category_id?: string | null;
  category_name?: string | null;
  reason: string;
}

export interface MarketTrendReportSummary {
  resolved_category_count: number;
  validated_opportunity_count: number;
  discarded_signal_count: number;
}

export interface MarketInsightsTraceEntry {
  sequence: number;
  timestamp: string;
  stage: string;
  phase: 'started' | 'completed' | 'failed' | 'info';
  message: string;
  details?: Record<string, unknown> | unknown[] | string | null;
}

export interface MarketTrendReportResponse {
  ok: boolean;
  run_id?: string | null;
  site_id: string;
  input_query: string;
  resolution_notes: MarketTrendResolutionNote[];
  resolved_categories: MarketResolvedCategory[];
  validated_opportunities: MarketValidatedOpportunity[];
  discarded_signals: MarketDiscardedSignal[];
  summary: MarketTrendReportSummary;
  execution_trace?: MarketInsightsTraceEntry[];
  log_file_path?: string | null;
}
