import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { QuestionDetail, QuestionListResponse } from '../../core/models/questions.models';

@Injectable({ providedIn: 'root' })
export class QuestionsApiService {
  private readonly http = inject(HttpClient);

  list(account: string): Observable<QuestionListResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.get<QuestionListResponse>('/api/questions', { params });
  }

  detail(account: string, questionId: number): Observable<QuestionDetail> {
    const params = new HttpParams().set('account', account);
    return this.http.get<QuestionDetail>(`/api/questions/${questionId}`, { params });
  }

  answer(account: string, questionId: number, text: string): Observable<QuestionDetail> {
    const params = new HttpParams().set('account', account);
    return this.http.post<QuestionDetail>(`/api/questions/${questionId}/answer`, { text }, { params });
  }
}
