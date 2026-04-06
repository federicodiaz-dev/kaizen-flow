import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { finalize } from 'rxjs';

import { AccountsResponse, AccountSummary } from '../models/account.models';

@Injectable({ providedIn: 'root' })
export class AccountContextService {
  private readonly http = inject(HttpClient);

  readonly accounts = signal<AccountSummary[]>([]);
  readonly selectedAccount = signal<string | null>(null);
  readonly defaultAccount = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly currentAccount = computed(
    () => this.accounts().find((account) => account.key === this.selectedAccount()) ?? null
  );
  readonly accountCount = computed(() => this.accounts().length);

  loadAccounts(): void {
    if (this.loading()) {
      return;
    }

    this.loading.set(true);
    this.error.set(null);
    this.http
      .get<AccountsResponse>('/api/accounts')
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (response) => {
          this.accounts.set(response.items);
          this.defaultAccount.set(response.default_account);
          const activeKey =
            this.selectedAccount() && response.items.some((item) => item.key === this.selectedAccount())
              ? this.selectedAccount()
              : response.default_account || response.items[0]?.key || null;
          this.selectedAccount.set(activeKey);
        },
        error: () => {
          this.error.set('No se pudieron cargar las cuentas configuradas.');
        }
      });
  }

  setSelectedAccount(accountKey: string): void {
    this.selectedAccount.set(accountKey);
  }
}
