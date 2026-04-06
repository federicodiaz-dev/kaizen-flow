export type QuestionFilter = 'all' | 'answered' | 'unanswered';

export interface QuestionItemRef {
  id: string;
  title: string | null;
  permalink: string | null;
  status: string | null;
}

export interface QuestionAnswer {
  text: string | null;
  status: string | null;
  date_created: string | null;
}

export interface QuestionSummary {
  id: number;
  text: string;
  status: string | null;
  date_created: string | null;
  hold: boolean;
  deleted_from_listing: boolean;
  from_user_id: number | null;
  item: QuestionItemRef | null;
  answer: QuestionAnswer | null;
  has_answer: boolean;
}

export interface QuestionDetail extends QuestionSummary {
  seller_id: number | null;
  can_answer: boolean;
  answer_limitations: string | null;
}

export interface QuestionListResponse {
  items: QuestionSummary[];
  total: number;
  offset: number;
  limit: number;
}
