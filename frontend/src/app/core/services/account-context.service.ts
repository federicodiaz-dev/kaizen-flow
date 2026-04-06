import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { finalize } from 'rxjs';

import { AccountSummary, AccountsResponse, DefaultAccountResponse } from '../models/account.models';

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
  readonly activeAccountCount = computed(() => this.accounts().filter((account) => account.is_active).length);
  readonly firstActiveAccount = computed(() => this.accounts().find((account) => account.is_active) ?? null);
  readonly hasActiveAccess = computed(() => this.currentAccount()?.is_active ?? false);

  clear(): void {
    this.accounts.set([]);
    this.selectedAccount.set(null);
    this.defaultAccount.set(null);
    this.loading.set(false);
    this.error.set(null);
  }

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
          const currentKey = this.selectedAccount();
          const selectedIfActive =
            currentKey && response.items.some((item) => item.key === currentKey && item.is_active)
              ? currentKey
              : null;
          const defaultIfActive =
            response.default_account && response.items.some((item) => item.key === response.default_account && item.is_active)
              ? response.default_account
              : null;
          const firstActive = response.items.find((item) => item.is_active)?.key ?? null;
          const selectedIfPresent =
            currentKey && response.items.some((item) => item.key === currentKey) ? currentKey : null;
          const defaultIfPresent =
            response.default_account && response.items.some((item) => item.key === response.default_account)
              ? response.default_account
              : null;
          this.selectedAccount.set(
            selectedIfActive || defaultIfActive || firstActive || selectedIfPresent || defaultIfPresent || response.items[0]?.key || null
          );
        },
        error: () => {
          this.error.set('No se pudieron cargar las cuentas configuradas.');
        }
      });
  }

  setSelectedAccount(accountKey: string): void {
    if (this.selectedAccount() === accountKey) {
      return;
    }
    this.selectedAccount.set(accountKey);
    this.defaultAccount.set(accountKey);
    this.http
      .patch<DefaultAccountResponse>('/api/accounts/default', { account_key: accountKey })
      .subscribe({
        error: () => {
          // Keep the local selection even if the persistence request fails.
        },
      });
  }

  selectFirstActiveAccount(): void {
    const account = this.firstActiveAccount();
    if (account) {
      this.setSelectedAccount(account.key);
    }
  }
}
