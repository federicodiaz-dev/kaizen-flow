import { CommonModule } from '@angular/common';
import { Component, computed, inject } from '@angular/core';
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
  readonly currentAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Sin cuenta'
  );

  constructor() {
    this.accountContext.loadAccounts();
  }

  onAccountChange(accountKey: string): void {
    this.accountContext.setSelectedAccount(accountKey);
  }
}
