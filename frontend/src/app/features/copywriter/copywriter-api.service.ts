import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface CopywriterGenerateRequest {
  product: string;
  brand?: string | null;
  country?: string;
  confirmed_data?: string | null;
  commercial_objective?: string | null;
}

export interface CopywriterGenerateResponse {
  titles: string[];
  description: string;
}

export interface DescriptionEnhanceRequest {
  product_title: string;
  current_description?: string;
  brand?: string | null;
  category?: string | null;
  price?: number | null;
  currency?: string | null;
  condition?: string | null;
  attributes?: Record<string, unknown>[];
}

export interface DescriptionEnhanceResponse {
  enhanced_description: string;
}

@Injectable({ providedIn: 'root' })
export class CopywriterApiService {
  private readonly http = inject(HttpClient);

  generate(payload: CopywriterGenerateRequest): Observable<CopywriterGenerateResponse> {
    return this.http.post<CopywriterGenerateResponse>('/api/copywriter/generate', payload);
  }

  enhanceDescription(payload: DescriptionEnhanceRequest): Observable<DescriptionEnhanceResponse> {
    return this.http.post<DescriptionEnhanceResponse>('/api/copywriter/enhance-description', payload);
  }
}
