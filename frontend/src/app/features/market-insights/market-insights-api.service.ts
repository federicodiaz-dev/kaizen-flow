import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  MarketTrendReportRequest,
  MarketTrendReportResponse,
} from '../../core/models/market-insights.models';

@Injectable({ providedIn: 'root' })
export class MarketInsightsApiService {
  private readonly http = inject(HttpClient);

  buildTrendReport(
    account: string,
    payload: MarketTrendReportRequest
  ): Observable<MarketTrendReportResponse> {
    const params = new HttpParams().set('account', account);
    return this.http.post<MarketTrendReportResponse>('/api/market-insights/trend-report', payload, {
      params,
    });
  }
}
