import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ClaimDetail, ClaimListResponse, ClaimMessage, ClaimMessageResult } from '../../core/models/claims.models';

@Injectable({ providedIn: 'root' })
export class ClaimsApiService {
  private readonly http = inject(HttpClient);

  list(account: string): Observable<ClaimListResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.get<ClaimListResponse>('/api/claims', { params });
  }

  detail(account: string, claimId: number): Observable<ClaimDetail> {
    const params = new HttpParams().set('account', account);
    return this.http.get<ClaimDetail>(`/api/claims/${claimId}`, { params });
  }

  messages(account: string, claimId: number): Observable<ClaimMessage[]> {
    const params = new HttpParams().set('account', account);
    return this.http.get<ClaimMessage[]>(`/api/claims/${claimId}/messages`, { params });
  }

  sendMessage(
    account: string,
    claimId: number,
    message: string,
    receiverRole?: string
  ): Observable<ClaimMessageResult> {
    const params = new HttpParams().set('account', account);
    return this.http.post<ClaimMessageResult>(
      `/api/claims/${claimId}/message`,
      { message, receiver_role: receiverRole ?? null },
      { params }
    );
  }
}
