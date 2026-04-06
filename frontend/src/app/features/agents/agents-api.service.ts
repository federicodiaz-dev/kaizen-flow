import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AgentMessageRequest,
  AgentMessageResponse,
  AgentThreadDetail,
  AgentThreadSummary,
} from '../../core/models/agent-chat.models';

@Injectable({ providedIn: 'root' })
export class AgentsApiService {
  private readonly http = inject(HttpClient);

  listThreads(): Observable<AgentThreadSummary[]> {
    return this.http.get<AgentThreadSummary[]>('/api/agents/threads');
  }

  createThread(): Observable<AgentThreadDetail> {
    return this.http.post<AgentThreadDetail>('/api/agents/threads', {});
  }

  getThread(threadId: string): Observable<AgentThreadDetail> {
    return this.http.get<AgentThreadDetail>(`/api/agents/threads/${threadId}`);
  }

  sendMessage(
    threadId: string,
    content: string,
    accountKey: string,
    siteId?: string | null
  ): Observable<AgentMessageResponse> {
    const params = new HttpParams().set('account', accountKey);
    const body: AgentMessageRequest = { content };
    if (siteId) {
      body.site_id = siteId;
    }
    return this.http.post<AgentMessageResponse>(
      `/api/agents/threads/${threadId}/messages`,
      body,
      { params }
    );
  }
}
