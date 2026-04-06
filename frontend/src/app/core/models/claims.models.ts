export interface ClaimAction {
  action: string;
  due_date: string | null;
  mandatory: boolean | null;
  player_role: string | null;
  player_type: string | null;
  user_id: number | null;
}

export interface ClaimPlayer {
  role: string;
  type: string | null;
  user_id: number | null;
  available_actions: ClaimAction[];
}

export interface ClaimMessageAttachment {
  filename: string | null;
  original_filename: string | null;
  size: number | null;
  type: string | null;
  date_created: string | null;
}

export interface ClaimMessage {
  sender_role: string | null;
  receiver_role: string | null;
  stage: string | null;
  date_created: string | null;
  message: string | null;
  attachments: ClaimMessageAttachment[];
}

export interface ClaimStatusHistoryEntry {
  stage: string | null;
  status: string | null;
  date: string | null;
  change_by: string | null;
}

export interface ClaimExpectedResolution {
  player_role: string | null;
  user_id: number | null;
  expected_resolution: string | null;
  status: string | null;
  date_created: string | null;
  last_updated: string | null;
}

export interface ClaimReputationImpact {
  affects_reputation: string | null;
  has_incentive: boolean | null;
  due_date: string | null;
}

export interface ClaimReasonDetail {
  id: string | null;
  name: string | null;
  detail: string | null;
  flow: string | null;
  parent_id: string | null;
  status: string | null;
}

export interface ClaimSummary {
  id: number;
  type: string | null;
  stage: string | null;
  status: string | null;
  reason_id: string | null;
  resource: string | null;
  resource_id: number | null;
  parent_id: number | null;
  date_created: string | null;
  last_updated: string | null;
  players: ClaimPlayer[];
  available_actions: ClaimAction[];
}

export interface ClaimDetail extends ClaimSummary {
  resolution: Record<string, unknown> | null;
  labels: Record<string, unknown>[];
  coverages: Record<string, unknown>[];
  site_id: string | null;
  messages: ClaimMessage[];
  status_history: ClaimStatusHistoryEntry[];
  expected_resolutions: ClaimExpectedResolution[];
  reputation_impact: ClaimReputationImpact | null;
  reason_detail: ClaimReasonDetail | null;
  can_message: boolean;
  message_limitations: string | null;
  allowed_receiver_roles: string[];
}

export interface ClaimListResponse {
  items: ClaimSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface ClaimMessageResult {
  execution_response: Record<string, unknown> | null;
  new_state: Record<string, unknown> | null;
  raw: Record<string, unknown> | null;
}
