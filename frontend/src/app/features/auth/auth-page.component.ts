import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';


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

  readonly email = signal('');
  readonly password = signal('');
  readonly confirmPassword = signal('');
  readonly errorMessage = signal<string | null>(null);

  readonly mode = computed<'login' | 'register'>(() => {
    const rawMode = this.route.snapshot.data['mode'];
    return rawMode === 'register' ? 'register' : 'login';
  });
  readonly pageTitle = computed(() =>
    this.mode() === 'register' ? 'Crear cuenta segura' : 'Ingresar a Kaizen Flow'
  );
  readonly pageSubtitle = computed(() =>
    this.mode() === 'register'
      ? 'Registrate para conectar tus cuentas de Mercado Libre y aislar tus datos.'
      : 'Accedé a tu workspace privado y seguí operando cada cuenta con aislamiento total.'
  );

  submit(): void {
    const email = this.email().trim();
    const password = this.password();

    this.errorMessage.set(null);

    if (!email || !password) {
      this.errorMessage.set('Completá tu email y contraseña.');
      return;
    }

    if (this.mode() === 'register') {
      if (password !== this.confirmPassword()) {
        this.errorMessage.set('Las contraseñas no coinciden.');
        return;
      }

      this.auth.register(email, password).subscribe({
        next: () => {
          void this.router.navigate(['/questions']);
        },
        error: (error) => this.errorMessage.set(this.getErrorMessage(error)),
      });
      return;
    }

    this.auth.login(email, password).subscribe({
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
        return message || nestedMessage || 'No se pudo completar la operación.';
      }
    }
    return 'No se pudo completar la operación.';
  }
}
