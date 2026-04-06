import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, firstValueFrom, map, of, tap } from 'rxjs';

import { SessionResponse, UserProfile } from '../models/auth.models';


@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  readonly user = signal<UserProfile | null>(null);
  readonly initialized = signal(false);
  readonly initializing = signal(false);
  readonly submitting = signal(false);
  readonly isAuthenticated = computed(() => this.user() !== null);

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
        tap((response) => this.user.set(response.user)),
        catchError((error: unknown) => {
          if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
            console.error('No se pudo restaurar la sesión.', error);
          }
          this.user.set(null);
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

  register(email: string, password: string) {
    this.submitting.set(true);
    return this.http.post<SessionResponse>('/api/auth/register', { email, password }).pipe(
      map((response) => response.user),
      tap((user) => {
        this.user.set(user);
        this.initialized.set(true);
      }),
      finalize(() => this.submitting.set(false)),
    );
  }

  login(email: string, password: string) {
    this.submitting.set(true);
    return this.http.post<SessionResponse>('/api/auth/login', { email, password }).pipe(
      map((response) => response.user),
      tap((user) => {
        this.user.set(user);
        this.initialized.set(true);
      }),
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
    this.initialized.set(true);
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
}
