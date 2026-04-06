import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, computed, inject, signal, effect } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AccountContextService } from './core/services/account-context.service';

@Component({
  selector: 'app-root',
  imports: [CommonModule, FormsModule, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
  readonly accountContext = inject(AccountContextService);
  private document = inject(DOCUMENT);

  readonly currentAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Sin cuenta'
  );

  readonly isDarkMode = signal(false);

  constructor() {
    this.accountContext.loadAccounts();
    
    // Check initial preference
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    this.isDarkMode.set(prefersDark);
    
    effect(() => {
      const dark = this.isDarkMode();
      if (dark) {
        this.document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        this.document.documentElement.setAttribute('data-theme', 'light');
      }
    });
  }

  onAccountChange(accountKey: string): void {
    this.accountContext.setSelectedAccount(accountKey);
  }
  
  toggleTheme(): void {
    this.isDarkMode.update(v => !v);
  }
}
