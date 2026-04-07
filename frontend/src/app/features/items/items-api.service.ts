import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ItemDetail, ItemListResponse, ItemUpdatePayload } from '../../core/models/items.models';

@Injectable({ providedIn: 'root' })
export class ItemsApiService {
  private readonly http = inject(HttpClient);

  list(account: string, status?: string, limit = 50): Observable<ItemListResponse> {
    let params = new HttpParams().set('account', account).set('limit', limit);
    if (status && status !== 'all') {
      params = params.set('status', status);
    }
    return this.http.get<ItemListResponse>('/api/items', { params });
  }

  detail(account: string, itemId: string): Observable<ItemDetail> {
    const params = new HttpParams().set('account', account);
    return this.http.get<ItemDetail>(`/api/items/${itemId}`, { params });
  }

  update(account: string, itemId: string, payload: ItemUpdatePayload): Observable<ItemDetail> {
    const params = new HttpParams().set('account', account);
    return this.http.patch<ItemDetail>(`/api/items/${itemId}`, payload, { params });
  }
}
