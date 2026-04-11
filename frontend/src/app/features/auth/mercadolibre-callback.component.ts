import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { AccountContextService } from '../../core/services/account-context.service';
import { AuthService } from '../../core/services/auth.service';
import { OnboardingTourService } from '../../core/services/onboarding-tour.service';


@Component({
  selector: 'app-mercadolibre-callback',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './mercadolibre-callback.component.html',
  styleUrl: './mercadolibre-callback.component.scss',
})
export class MercadoLibreCallbackComponent {
  private readonly router = inject(Router);
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly accountContext = inject(AccountContextService);
  private readonly onboardingTour = inject(OnboardingTourService);

  readonly status = signal<'success' | 'error'>('success');
  readonly message = signal('Preparando tu workspace...');

  constructor() {
    void this.resolveCallback();
  }

  async continue(): Promise<void> {
    const destination = this.auth.user()?.is_first_visit ? '/agents' : '/questions';
    await this.router.navigate([destination]);
  }

  private async resolveCallback(): Promise<void> {
    const query = new URLSearchParams(window.location.search);
    const code = query.get('code');
    const state = query.get('state');
    const oauthError = query.get('error');
    const oauthErrorDescription = query.get('error_description');

    if (code || oauthError) {
      await this.completeOAuthInBackend({
        code,
        state,
        error: oauthError,
        error_description: oauthErrorDescription,
      });
      return;
    }

    const status = query.get('status') === 'error' ? 'error' : 'success';
    const message = query.get('message');

    this.status.set(status);
    this.message.set(
      message ||
        (status === 'success'
          ? 'La cuenta de Mercado Libre quedo conectada correctamente.'
          : 'No se pudo completar la vinculacion con Mercado Libre.'),
    );

    await this.auth.ensureInitialized();

    if (!this.auth.isAuthenticated()) {
      this.status.set('error');
      this.message.set('La cuenta se proceso, pero tu sesion local ya no es valida. Vuelve a ingresar para continuar.');
      return;
    }

    this.accountContext.loadAccounts();

    if (status === 'success' && this.auth.user()?.is_first_visit) {
      this.message.set('Cuenta conectada. Ahora te mostramos rapidamente como usar el agente IA.');
      this.onboardingTour.requestWelcomeTour();
    }
  }

  private async completeOAuthInBackend(payload: {
    code: string | null;
    state: string | null;
    error: string | null;
    error_description: string | null;
  }): Promise<void> {
    try {
      await firstValueFrom(
        this.http.post('/api/auth/mercadolibre/complete', {
          code: payload.code,
          state: payload.state,
          error: payload.error,
          error_description: payload.error_description,
        }),
      );

      this.status.set('success');
      this.message.set('La cuenta de Mercado Libre quedo conectada correctamente.');

      await this.auth.ensureInitialized();

      if (!this.auth.isAuthenticated()) {
        this.status.set('error');
        this.message.set('La autorizacion termino bien, pero tu sesion local no esta activa. Vuelve a ingresar.');
        return;
      }

      this.accountContext.loadAccounts();

      if (this.auth.user()?.is_first_visit) {
        this.message.set('Cuenta conectada. Ahora te mostramos rapidamente como usar el agente IA.');
        this.onboardingTour.requestWelcomeTour();
      }
    } catch (error) {
      this.status.set('error');
      this.message.set(this.getErrorMessage(error));
    }
  }

  private getErrorMessage(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const payload = error.error;
      if (typeof payload === 'string' && payload.trim()) {
        return payload;
      }
      if (payload && typeof payload === 'object') {
        const message = 'message' in payload && typeof payload.message === 'string' ? payload.message : null;
        const details =
          'details' in payload && payload.details && typeof payload.details === 'object'
            ? payload.details
            : null;
        const nestedMessage =
          details && 'message' in details && typeof details.message === 'string' ? details.message : null;
        return message || nestedMessage || 'No se pudo completar la vinculacion con Mercado Libre.';
      }
    }
    return 'No se pudo completar la vinculacion con Mercado Libre.';
  }
}
