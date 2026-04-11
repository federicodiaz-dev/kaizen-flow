import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { PlanCatalogService } from '../../core/services/plan-catalog.service';


@Component({
  selector: 'app-auth-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './auth-page.component.html',
  styleUrl: './auth-page.component.scss',
})
export class AuthPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  readonly auth = inject(AuthService);
  readonly planCatalog = inject(PlanCatalogService);

  readonly identifier = signal('');
  readonly email = signal('');
  readonly username = signal('');
  readonly password = signal('');
  readonly confirmPassword = signal('');
  readonly selectedPlanCode = signal('');
  readonly errorMessage = signal<string | null>(null);

  readonly mode = computed<'login' | 'register'>(() => {
    const rawMode = this.route.snapshot.data['mode'];
    return rawMode === 'register' ? 'register' : 'login';
  });
  readonly pageTitle = computed(() =>
    this.mode() === 'register' ? 'Crea tu workspace profesional' : 'Ingresa a Kaizen Flow'
  );
  readonly pageSubtitle = computed(() =>
    this.mode() === 'register'
      ? 'Registra tu equipo, elige un plan y deja listo el acceso para conectar Mercado Libre y operar en serio.'
      : 'Accede con tu email o username para retomar tu operacion y seguir trabajando con el plan que ya contrataste.'
  );
  readonly recommendedPlanCode = computed(() => {
    const recommended = this.planCatalog.plans().find((plan) => plan.code === 'growth');
    return recommended?.code ?? this.planCatalog.plans()[0]?.code ?? '';
  });

  constructor() {
    this.planCatalog.ensureLoaded();

    effect(() => {
      const currentSelection = this.selectedPlanCode();
      if (currentSelection) {
        return;
      }

      const recommended = this.recommendedPlanCode();
      if (recommended) {
        this.selectedPlanCode.set(recommended);
      }
    });
  }

  submit(): void {
    this.errorMessage.set(null);

    if (this.mode() === 'register') {
      const email = this.email().trim();
      const username = this.username().trim();
      const password = this.password();
      const selectedPlanCode = this.selectedPlanCode();

      if (!email || !username || !password) {
        this.errorMessage.set('Completa email, username y contrasena.');
        return;
      }

      if (!selectedPlanCode) {
        this.errorMessage.set('Selecciona el plan que quieres activar.');
        return;
      }

      const passwordStrengthError = this.getPasswordStrengthError(password);
      if (passwordStrengthError) {
        this.errorMessage.set(passwordStrengthError);
        return;
      }

      if (password !== this.confirmPassword()) {
        this.errorMessage.set('Las contrasenas no coinciden.');
        return;
      }

      this.auth.register(email, username, password, selectedPlanCode).subscribe({
        next: () => {
          void this.router.navigate(['/questions']);
        },
        error: (error) => this.errorMessage.set(this.getErrorMessage(error)),
      });
      return;
    }

    const identifier = this.identifier().trim();
    const password = this.password();
    if (!identifier || !password) {
      this.errorMessage.set('Completa tu email o username y la contrasena.');
      return;
    }

    this.auth.login(identifier, password).subscribe({
      next: () => {
        void this.router.navigate(['/questions']);
      },
      error: (error) => this.errorMessage.set(this.getErrorMessage(error)),
    });
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
        return message || nestedMessage || 'No se pudo completar la operacion.';
      }
    }
    return 'No se pudo completar la operacion.';
  }

  private getPasswordStrengthError(password: string): string | null {
    if (password.length < 12) {
      return 'La contrasena debe tener al menos 12 caracteres.';
    }
    if (!/[a-z]/.test(password)) {
      return 'La contrasena debe incluir al menos una letra minuscula.';
    }
    if (!/[A-Z]/.test(password)) {
      return 'La contrasena debe incluir al menos una letra mayuscula.';
    }
    if (!/\d/.test(password)) {
      return 'La contrasena debe incluir al menos un numero.';
    }
    if (!/[^A-Za-z0-9]/.test(password)) {
      return 'La contrasena debe incluir al menos un simbolo.';
    }
    return null;
  }
}
