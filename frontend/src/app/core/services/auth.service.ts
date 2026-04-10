import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, firstValueFrom, map, of, tap } from 'rxjs';

import { SessionResponse, SubscriptionProfile, UserProfile, WorkspaceProfile } from '../models/auth.models';


@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  readonly user = signal<UserProfile | null>(null);
  readonly workspace = signal<WorkspaceProfile | null>(null);
  readonly subscription = signal<SubscriptionProfile | null>(null);
  readonly initialized = signal(false);
  readonly initializing = signal(false);
  readonly submitting = signal(false);
  readonly isAuthenticated = computed(() => this.user() !== null);
  readonly hasActiveSubscription = computed(() => this.subscription()?.is_active ?? false);
  readonly currentPlanCode = computed(() => this.subscription()?.plan_code ?? null);
  readonly currentPlanName = computed(() => this.subscription()?.plan_name ?? null);

  private bootstrapPromise: Promise<void> | null = null;

  ensureInitialized(): Promise<void> {
    if (this.initialized()) {
      return Promise.resolve();
    }
    if (this.bootstrapPromise) {
      return this.bootstrapPromise;
    }

    this.initializing.set(true);
    this.bootstrapPromise = firstValueFrom(
      this.http.get<SessionResponse>('/api/auth/me').pipe(
        tap((response) => this.applySession(response)),
        catchError((error: unknown) => {
          if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
            console.error('No se pudo restaurar la sesion.', error);
          }
          this.clearSession();
          return of(null);
        }),
        finalize(() => {
          this.initialized.set(true);
          this.initializing.set(false);
          this.bootstrapPromise = null;
        }),
      ),
    ).then(() => undefined);

    return this.bootstrapPromise;
  }

  register(email: string, password: string, workspaceName?: string) {
    this.submitting.set(true);
    return this.http.post<SessionResponse>('/api/auth/register', {
      email,
      password,
      workspace_name: workspaceName?.trim() || null,
    }).pipe(
      tap((response) => {
        this.applySession(response);
        this.initialized.set(true);
      }),
      map((response) => response.user),
      finalize(() => this.submitting.set(false)),
    );
  }

  login(email: string, password: string) {
    this.submitting.set(true);
    return this.http.post<SessionResponse>('/api/auth/login', { email, password }).pipe(
      tap((response) => {
        this.applySession(response);
        this.initialized.set(true);
      }),
      map((response) => response.user),
      finalize(() => this.submitting.set(false)),
    );
  }

  logout() {
    return this.http.post<void>('/api/auth/logout', {}).pipe(
      tap(() => this.clearSession()),
    );
  }

  clearSession(): void {
    this.user.set(null);
    this.workspace.set(null);
    this.subscription.set(null);
    this.initialized.set(true);
  }

  completeOnboarding() {
    return this.http.post<SessionResponse>('/api/auth/onboarding/complete', {}).pipe(
      tap((response) => this.applySession(response)),
      map((response) => response.user),
    );
  }

  handleUnauthorized(): void {
    this.clearSession();
    const currentUrl = this.router.url;
    if (!currentUrl.startsWith('/login') && !currentUrl.startsWith('/register')) {
      void this.router.navigate(['/login']);
    }
  }

  connectMercadoLibre(accountKey?: string, label?: string): void {
    let params = new HttpParams();
    if (accountKey?.trim()) {
      params = params.set('account_key', accountKey.trim());
    }
    if (label?.trim()) {
      params = params.set('label', label.trim());
    }
    const query = params.toString();
    const url = query ? `/api/auth/mercadolibre/connect?${query}` : '/api/auth/mercadolibre/connect';
    window.location.assign(url);
  }

  private applySession(response: SessionResponse): void {
    this.user.set(response.user);
    this.workspace.set(response.workspace);
    this.subscription.set(response.subscription);
  }
}
