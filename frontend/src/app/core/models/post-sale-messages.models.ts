export interface PostSaleConversationParty {
  user_id: number | null;
  name: string | null;
  nickname: string | null;
}

export interface PostSaleMessageAttachment {
  filename: string | null;
  original_filename: string | null;
  size: number | null;
  type: string | null;
  date_created: string | null;
  potential_security_threat: boolean | null;
}

export interface PostSaleMessage {
  id: string | null;
  site_id: string | null;
  client_id: string | null;
  text: string | null;
  status: string | null;
  date_created: string | null;
  date_received: string | null;
  date_available: string | null;
  date_notified: string | null;
  date_read: string | null;
  from_user: PostSaleConversationParty | null;
  to_users: PostSaleConversationParty[];
  attachments: PostSaleMessageAttachment[];
  moderation_status: string | null;
  moderation_substatus: string | null;
  moderation_source: string | null;
  moderation_date: string | null;
  conversation_first_message: boolean | null;
  is_from_seller: boolean;
}

export interface PostSaleOrderItemRef {
  item_id: string | null;
  title: string | null;
  quantity: number | null;
  unit_price: number | null;
  currency_id: string | null;
  full_unit_price: number | null;
  variation_id: number | null;
  thumbnail: string | null;
}

export interface PostSaleOrderRef {
  id: number;
  pack_id: string | null;
  status: string | null;
  status_detail: string | null;
  date_created: string | null;
  date_closed: string | null;
  last_updated: string | null;
  total_amount: number | null;
  paid_amount: number | null;
  currency_id: string | null;
  shipping_id: number | null;
  tags: string[];
  items: PostSaleOrderItemRef[];
}

export interface PostSaleConversationSummary {
  pack_id: string;
  buyer_user_id: number | null;
  buyer_name: string | null;
  buyer_nickname: string | null;
  primary_item_title: string | null;
  item_titles: string[];
  order_ids: number[];
  date_created: string | null;
  last_updated: string | null;
  unread_count: number;
  message_count: number;
  conversation_status: string | null;
  conversation_substatus: string | null;
  pack_status: string | null;
  pack_status_detail: string | null;
  seller_max_message_length: number | null;
  buyer_max_message_length: number | null;
  can_reply: boolean;
  reply_limitations: string | null;
  site_id: string | null;
  shipping_id: number | null;
  total_amount: number | null;
  currency_id: string | null;
  claim_ids: number[];
}

export interface PostSaleConversationDetail extends PostSaleConversationSummary {
  seller_user_id: number | null;
  messages: PostSaleMessage[];
  orders: PostSaleOrderRef[];
}

export interface PostSaleConversationListResponse {
  items: PostSaleConversationSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface PostSaleMessageResult {
  raw: Record<string, unknown> | null;
}
