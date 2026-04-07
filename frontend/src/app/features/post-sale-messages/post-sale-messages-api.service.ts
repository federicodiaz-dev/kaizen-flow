import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  PostSaleConversationDetail,
  PostSaleConversationListResponse,
  PostSaleMessageResult,
} from '../../core/models/post-sale-messages.models';

@Injectable({ providedIn: 'root' })
export class PostSaleMessagesApiService {
  private readonly http = inject(HttpClient);

  list(account: string): Observable<PostSaleConversationListResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.get<PostSaleConversationListResponse>('/api/post-sale-messages', { params });
  }

  detail(account: string, packId: string, markAsRead = false): Observable<PostSaleConversationDetail> {
    const params = new HttpParams()
      .set('account', account)
      .set('mark_as_read', String(markAsRead));
    return this.http.get<PostSaleConversationDetail>(`/api/post-sale-messages/${packId}`, { params });
  }

  reply(account: string, packId: string, text: string): Observable<PostSaleMessageResult> {
    const params = new HttpParams().set('account', account);
    return this.http.post<PostSaleMessageResult>(
      `/api/post-sale-messages/${packId}/reply`,
      { text },
      { params }
    );
  }
}
