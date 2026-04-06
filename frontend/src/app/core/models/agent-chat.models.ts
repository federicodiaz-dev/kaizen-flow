export type AgentRoute = 'mercadolibre_account' | 'market_intelligence' | 'clarification';

export interface AgentIntentMetadata {
  route: AgentRoute;
  confidence: number;
  user_goal: string;
  normalized_request: string;
  needs_account_context: boolean;
  needs_market_context: boolean;
  required_data_points: string[];
  clarifying_question: string | null;
  reasoning: string;
}

export interface AgentChatMessage {
  role: string;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown> | null;
}

export interface AgentThreadSummary {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview: string;
}

export interface AgentThreadDetail extends AgentThreadSummary {
  messages: AgentChatMessage[];
}

export interface AgentMessageRequest {
  content: string;
  site_id?: string | null;
}

export interface AgentMessageResponse {
  thread: AgentThreadDetail;
  assistant_message: AgentChatMessage;
  final_response: string;
  route: AgentRoute;
  intent: AgentIntentMetadata;
  account_key: string;
  site_id: string;
}
