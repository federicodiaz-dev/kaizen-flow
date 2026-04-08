import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { OnboardingTourComponent } from './core/components/onboarding-tour.component';
import { AccountContextService } from './core/services/account-context.service';
import { AuthService } from './core/services/auth.service';
import { OnboardingTourService } from './core/services/onboarding-tour.service';


@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule, RouterLink, RouterLinkActive, RouterOutlet, OnboardingTourComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
  readonly accountContext = inject(AccountContextService);
  readonly auth = inject(AuthService);
  readonly onboardingTour = inject(OnboardingTourService);
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router);

  readonly currentUrl = signal(this.router.url);
  readonly currentAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Sin cuenta'
  );
  readonly currentAccountIsActive = computed(() => this.accountContext.currentAccount()?.is_active ?? false);
  readonly showInactiveGate = computed(
    () =>
      this.accountContext.accountCount() > 0 &&
      this.accountContext.currentAccount() !== null &&
      !this.accountContext.hasActiveAccess()
  );
  readonly inactiveGateTitle = computed(() =>
    this.accountContext.activeAccountCount() > 0 ? 'Esta cuenta está inactiva' : 'Tu membresía está inactiva'
  );
  readonly inactiveGateMessage = computed(() =>
    this.accountContext.activeAccountCount() > 0
      ? 'La cuenta seleccionada está creada, pero no tiene una membresía activa. Elegí una cuenta activa o habilitá el acceso para continuar.'
      : 'La cuenta quedó vinculada correctamente, pero su membresía todavía no está activa. Cuando acredites el pago y la actives en la base de datos, el panel se habilitará.'
  );
  readonly currentUserEmail = computed(() => this.auth.user()?.email ?? 'Sin sesión');
  readonly isAuthScreen = computed(() => {
    const url = this.currentUrl();
    return url.startsWith('/login') || url.startsWith('/register') || url.startsWith('/auth/');
  });

  readonly isDarkMode = signal(false);
  readonly isMobileMenuOpen = signal(false);

  constructor() {
    void this.auth.ensureInitialized();

    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    this.isDarkMode.set(prefersDark);

    this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe((event) => {
        this.currentUrl.set(event.urlAfterRedirects);
        this.isMobileMenuOpen.set(false);
      });

    effect(() => {
      const dark = this.isDarkMode();
      if (dark) {
        this.document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        this.document.documentElement.setAttribute('data-theme', 'light');
      }
    });

    effect(() => {
      const userId = this.auth.user()?.id ?? null;
      if (userId !== null) {
        untracked(() => this.accountContext.loadAccounts());
      } else {
        untracked(() => this.accountContext.clear());
      }
    });

    effect(() => {
      const isFirstVisit = this.auth.user()?.is_first_visit ?? false;
      const accountCount = this.accountContext.accountCount();
      const hasActiveAccess = this.accountContext.hasActiveAccess();
      const isAuthScreen = this.isAuthScreen();

      if (isFirstVisit && accountCount > 0 && hasActiveAccess && !isAuthScreen) {
        untracked(() => this.onboardingTour.requestWelcomeTour());
      }
    });
  }

  onAccountChange(accountKey: string): void {
    this.accountContext.setSelectedAccount(accountKey);
  }

  connectMercadoLibre(): void {
    this.auth.connectMercadoLibre();
  }

  useFirstActiveAccount(): void {
    this.accountContext.selectFirstActiveAccount();
  }

  logout(): void {
    this.auth.logout().subscribe({
      next: () => {
        void this.router.navigate(['/login']);
      },
      error: () => {
        this.auth.clearSession();
        void this.router.navigate(['/login']);
      },
    });
  }
  
  toggleTheme(): void {
    this.isDarkMode.update(v => !v);
  }

  toggleMobileMenu(): void {
    this.isMobileMenuOpen.update(v => !v);
  }
}
