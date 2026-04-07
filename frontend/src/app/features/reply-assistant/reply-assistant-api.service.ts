import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface QuestionDraftRequest {
  current_draft?: string | null;
}

export interface QuestionDraftResponse {
  draft_answer: string;
}

export interface ClaimDraftRequest {
  receiver_role?: string | null;
  current_draft?: string | null;
}

export interface ClaimDraftResponse {
  draft_message: string;
}

export interface PostSaleDraftRequest {
  current_draft?: string | null;
}

export interface PostSaleDraftResponse {
  draft_message: string;
}

@Injectable({ providedIn: 'root' })
export class ReplyAssistantApiService {
  private readonly http = inject(HttpClient);

  suggestQuestionAnswer(
    account: string,
    questionId: number,
    payload: QuestionDraftRequest
  ): Observable<QuestionDraftResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.post<QuestionDraftResponse>(
      `/api/reply-assistant/questions/${questionId}/draft`,
      payload,
      { params }
    );
  }

  suggestClaimMessage(
    account: string,
    claimId: number,
    payload: ClaimDraftRequest
  ): Observable<ClaimDraftResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.post<ClaimDraftResponse>(
      `/api/reply-assistant/claims/${claimId}/draft`,
      payload,
      { params }
    );
  }

  suggestPostSaleMessage(
    account: string,
    packId: string,
    payload: PostSaleDraftRequest
  ): Observable<PostSaleDraftResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.post<PostSaleDraftResponse>(
      `/api/reply-assistant/post-sale/${packId}/draft`,
      payload,
      { params }
    );
  }
}
