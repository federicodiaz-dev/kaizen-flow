import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';

import { PlanCatalogItem, PlanCatalogResponse } from '../models/plan.models';


@Injectable({ providedIn: 'root' })
export class PlanCatalogService {
  private readonly http = inject(HttpClient);

  readonly plans = signal<PlanCatalogItem[]>([]);
  readonly loading = signal(false);
  readonly loaded = signal(false);
  readonly errorMessage = signal<string | null>(null);

  ensureLoaded(): void {
    if (this.loading() || this.loaded()) {
      return;
    }

    this.loading.set(true);
    this.errorMessage.set(null);
    this.http.get<PlanCatalogResponse>('/api/plans').subscribe({
      next: (response) => {
        this.plans.set(response.plans);
        this.loaded.set(true);
      },
      error: (error: unknown) => {
        this.loading.set(false);
        if (error instanceof HttpErrorResponse && typeof error.error === 'object' && error.error) {
          const payload = error.error as { message?: string };
          this.errorMessage.set(payload.message ?? 'No se pudieron cargar los planes.');
        } else {
          this.errorMessage.set('No se pudieron cargar los planes.');
        }
      },
      complete: () => {
        this.loading.set(false);
      },
    });
  }
}
