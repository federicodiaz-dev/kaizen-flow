import { CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { OnboardingTourService } from '../../core/services/onboarding-tour.service';
import { AccountContextService } from '../../core/services/account-context.service';
import { AuthService } from '../../core/services/auth.service';


@Component({
  selector: 'app-mercadolibre-callback',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './mercadolibre-callback.component.html',
  styleUrl: './mercadolibre-callback.component.scss',
})
export class MercadoLibreCallbackComponent {
  private readonly router = inject(Router);
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
    const status = query.get('status') === 'error' ? 'error' : 'success';
    const message = query.get('message');

    this.status.set(status);
    this.message.set(
      message ||
        (status === 'success'
          ? 'La cuenta de Mercado Libre quedó conectada correctamente.'
          : 'No se pudo completar la vinculación con Mercado Libre.')
    );

    await this.auth.ensureInitialized();

    if (!this.auth.isAuthenticated()) {
      this.status.set('error');
      this.message.set('La cuenta se procesó, pero tu sesión local ya no es válida. Volvé a ingresar para continuar.');
      return;
    }

    this.accountContext.loadAccounts();

    if (status === 'success' && this.auth.user()?.is_first_visit) {
      this.message.set('Cuenta conectada. Ahora te mostramos rápidamente cómo usar el agente IA.');
      this.onboardingTour.requestWelcomeTour();
    }
  }
}
