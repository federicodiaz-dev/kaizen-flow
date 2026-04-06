import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';

import { ClaimDetail, ClaimSummary } from '../../core/models/claims.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { ClaimDetailComponent } from './claim-detail.component';
import { ClaimListComponent } from './claim-list.component';
import { ClaimsApiService } from './claims-api.service';

@Component({
  selector: 'app-claims-page',
  standalone: true,
  imports: [CommonModule, ClaimListComponent, ClaimDetailComponent],
  templateUrl: './claims-page.component.html',
  styleUrl: './claims-page.component.scss'
})
export class ClaimsPageComponent {
  private readonly api = inject(ClaimsApiService);
  readonly accountContext = inject(AccountContextService);

  readonly claims = signal<ClaimSummary[]>([]);
  readonly selectedClaimId = signal<number | null>(null);
  readonly selectedClaim = signal<ClaimDetail | null>(null);
  readonly loadingList = signal(false);
  readonly loadingDetail = signal(false);
  readonly sending = signal(false);
  readonly listError = signal<string | null>(null);
  readonly detailError = signal<string | null>(null);
  readonly searchText = signal('');
  readonly statusFilter = signal('all');

  readonly filteredClaims = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    return this.claims().filter((claim) => {
      const matchesStatus =
        this.statusFilter() === 'all' ||
        (this.statusFilter() === 'closed'
          ? (claim.status || '').toLowerCase() === 'closed'
          : (claim.status || '').toLowerCase() !== 'closed');
      const matchesQuery =
        !query ||
        claim.id.toString().includes(query) ||
        (claim.reason_id || '').toLowerCase().includes(query) ||
        `${claim.resource || ''} ${claim.resource_id || ''}`.toLowerCase().includes(query);
      return matchesStatus && matchesQuery;
    });
  });
  readonly totalClaims = computed(() => this.claims().length);
  readonly openClaims = computed(
    () => this.claims().filter((claim) => (claim.status || '').toLowerCase() !== 'closed').length
  );
  readonly actionableClaims = computed(
    () => this.claims().filter((claim) => (claim.available_actions || []).length > 0).length
  );
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(() => {
      const account = this.accountContext.selectedAccount();
      if (account) {
        this.loadClaims(account);
      }
    }, { allowSignalWrites: true });
  }

  private getErrorMessage(error: unknown, fallback: string): string {
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
        return message || nestedMessage || fallback;
      }
    }
    return fallback;
  }

  loadClaims(account: string): void {
    this.loadingList.set(true);
    this.listError.set(null);
    this.api.list(account).subscribe({
      next: (response) => {
        this.claims.set(response.items);
        const currentId = this.selectedClaimId();
        const fallbackId = response.items[0]?.id ?? null;
        const nextId = response.items.some((item) => item.id === currentId) ? currentId : fallbackId;
        this.selectedClaimId.set(nextId);
        if (nextId) {
          this.loadClaimDetail(nextId);
        } else {
          this.selectedClaim.set(null);
        }
        this.loadingList.set(false);
      },
      error: (error) => {
        this.listError.set(this.getErrorMessage(error, 'No se pudieron cargar los reclamos.'));
        this.loadingList.set(false);
      }
    });
  }

  loadClaimDetail(claimId: number): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.loadingDetail.set(true);
    this.detailError.set(null);
    this.api.detail(account, claimId).subscribe({
      next: (response) => {
        this.selectedClaim.set(response);
        this.loadingDetail.set(false);
      },
      error: (error) => {
        this.detailError.set(this.getErrorMessage(error, 'No se pudo cargar el detalle del reclamo.'));
        this.loadingDetail.set(false);
      }
    });
  }

  onSelectClaim(claimId: number): void {
    this.selectedClaimId.set(claimId);
    this.loadClaimDetail(claimId);
  }

  onSendMessage(payload: { message: string; receiverRole?: string }): void {
    const account = this.accountContext.selectedAccount();
    const claimId = this.selectedClaimId();
    if (!account || !claimId) {
      return;
    }

    this.sending.set(true);
    this.detailError.set(null);
    this.api.sendMessage(account, claimId, payload.message, payload.receiverRole).subscribe({
      next: () => {
        this.loadClaimDetail(claimId);
        this.sending.set(false);
      },
      error: (error) => {
        this.detailError.set(
          this.getErrorMessage(error, 'No se pudo enviar el mensaje del reclamo.')
        );
        this.sending.set(false);
      }
    });
  }
}
