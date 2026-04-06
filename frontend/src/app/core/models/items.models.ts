export interface ItemSummary {
  id: string;
  title: string;
  price: number | null;
  currency_id: string | null;
  available_quantity: number | null;
  sold_quantity: number | null;
  status: string | null;
  permalink: string | null;
  thumbnail: string | null;
  last_updated: string | null;
}

export interface ItemDetail extends ItemSummary {
  seller_id: number | null;
  category_id: string | null;
  listing_type_id: string | null;
  condition: string | null;
  health: string | null;
  variations: Record<string, unknown>[];
  attributes: Record<string, unknown>[];
  pictures: Record<string, unknown>[];
}

export interface ItemListResponse {
  items: ItemSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface ItemUpdatePayload {
  title?: string;
  price?: number;
  available_quantity?: number;
  status?: 'active' | 'paused' | 'closed';
}
