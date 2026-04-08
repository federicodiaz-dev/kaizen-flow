import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Component, HostListener, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';

import { ClaimDetail, ClaimSummary } from '../../core/models/claims.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
import { isEditableTarget } from '../../core/utils/keyboard.utils';
import { ClaimDetailComponent } from './claim-detail.component';
import {
  ClaimActionFilter,
  ClaimListComponent,
  ClaimStageFilter,
  ClaimStatusFilter,
} from './claim-list.component';
import { ClaimsApiService } from './claims-api.service';

type ClaimsUiState = {
  searchText: string;
  statusFilter: ClaimStatusFilter;
  stageFilter: ClaimStageFilter;
  actionFilter: ClaimActionFilter;
  selectedClaimId: number | null;
};

@Component({
  selector: 'app-claims-page',
  standalone: true,
  imports: [CommonModule, ClaimListComponent, ClaimDetailComponent],
  templateUrl: './claims-page.component.html',
  styleUrl: './claims-page.component.scss'
})
export class ClaimsPageComponent {
  private readonly api = inject(ClaimsApiService);
  private readonly workspaceState = inject(WorkspaceStateService);
  readonly accountContext = inject(AccountContextService);
  private readonly listComponent = viewChild(ClaimListComponent);
  private readonly storageKey = 'claims-workspace';

  readonly claims = signal<ClaimSummary[]>([]);
  readonly selectedClaimId = signal<number | null>(null);
  readonly selectedClaim = signal<ClaimDetail | null>(null);
  readonly loadingList = signal(false);
  readonly loadingDetail = signal(false);
  readonly sending = signal(false);
  readonly listError = signal<string | null>(null);
  readonly detailError = signal<string | null>(null);
  readonly searchText = signal('');
  readonly statusFilter = signal<ClaimStatusFilter>('all');
  readonly stageFilter = signal<ClaimStageFilter>('all');
  readonly actionFilter = signal<ClaimActionFilter>('all');
  readonly nextPendingClaimId = signal<number | null>(null);
  readonly followUpMessage = signal<string | null>(null);
  readonly clearDraftToken = signal(0);

  readonly filteredClaims = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    const statusFilter = this.statusFilter();
    const stageFilter = this.stageFilter();
    const actionFilter = this.actionFilter();

    return [...this.claims()].filter((claim) => {
      const normalizedStatus = (claim.status || '').toLowerCase();
      const normalizedStage = (claim.stage || '').toLowerCase();
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'closed' ? normalizedStatus === 'closed' : normalizedStatus !== 'closed');
      const matchesStage = stageFilter === 'all' || normalizedStage === stageFilter;
      const matchesAction = actionFilter === 'all' || claim.available_actions.length > 0;
      const matchesQuery =
        !query ||
        claim.id.toString().includes(query) ||
        (claim.reason_id || '').toLowerCase().includes(query) ||
        `${claim.resource || ''} ${claim.resource_id || ''}`.toLowerCase().includes(query);

      return matchesStatus && matchesStage && matchesAction && matchesQuery;
    });
  });
  readonly totalClaims = computed(() => this.claims().length);
  readonly filteredCount = computed(() => this.filteredClaims().length);
  readonly openClaims = computed(
    () => this.claims().filter((claim) => (claim.status || '').toLowerCase() !== 'closed').length
  );
  readonly actionableClaims = computed(
    () => this.claims().filter((claim) => (claim.available_actions || []).length > 0).length
  );
  readonly activeFilterCount = computed(() => {
    let total = 0;
    if (this.searchText().trim()) total += 1;
    if (this.statusFilter() !== 'all') total += 1;
    if (this.stageFilter() !== 'all') total += 1;
    if (this.actionFilter() !== 'all') total += 1;
    return total;
  });
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(() => {
      const account = this.accountContext.currentAccount();
      if (account?.is_active) {
        untracked(() => {
          this.restoreUiState(account.key);
          this.loadClaims(account.key);
        });
      }
    }, { allowSignalWrites: true });

    effect(() => {
      const account = this.accountContext.selectedAccount();
      if (!account) {
        return;
      }

      this.workspaceState.saveUiState<ClaimsUiState>(this.storageKey, account, {
        searchText: this.searchText(),
        statusFilter: this.statusFilter(),
        stageFilter: this.stageFilter(),
        actionFilter: this.actionFilter(),
        selectedClaimId: this.selectedClaimId(),
      });
    }, { allowSignalWrites: true });
  }

  @HostListener('window:keydown', ['$event'])
  handleKeyboardShortcuts(event: KeyboardEvent): void {
    if (event.defaultPrevented) {
      return;
    }

    if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !isEditableTarget(event.target)) {
      event.preventDefault();
      this.listComponent()?.focusSearch();
      return;
    }

    if (isEditableTarget(event.target)) {
      return;
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      this.moveSelection(event.key === 'ArrowDown' ? 1 : -1);
    }
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
    this.resetFollowUpState();
    this.selectedClaimId.set(claimId);
    this.loadClaimDetail(claimId);
  }

  closeSelectedClaim(): void {
    this.selectedClaimId.set(null);
    this.selectedClaim.set(null);
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
        const nextClaimId = this.findNextPendingClaim(claimId);
        this.nextPendingClaimId.set(nextClaimId);
        this.followUpMessage.set(
          nextClaimId
            ? 'Mensaje enviado. Puedes continuar con el siguiente reclamo que requiere atencion.'
            : 'Mensaje enviado. No quedan reclamos pendientes en esta vista.'
        );
        this.clearDraftToken.update((value) => value + 1);
        this.loadClaimDetail(claimId);
        this.sending.set(false);
      },
      error: (error) => {
        this.detailError.set(this.getErrorMessage(error, 'No se pudo enviar el mensaje del reclamo.'));
        this.sending.set(false);
      }
    });
  }

  resetFilters(): void {
    this.searchText.set('');
    this.statusFilter.set('all');
    this.stageFilter.set('all');
    this.actionFilter.set('all');
  }

  refreshClaims(): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.resetFollowUpState();
    this.loadClaims(account);
  }

  goToNextPendingClaim(): void {
    const nextClaimId = this.nextPendingClaimId();
    if (!nextClaimId) {
      return;
    }

    this.onSelectClaim(nextClaimId);
  }

  private restoreUiState(account: string): void {
    const state = this.workspaceState.loadUiState<ClaimsUiState>(this.storageKey, account, {
      searchText: '',
      statusFilter: 'all',
      stageFilter: 'all',
      actionFilter: 'all',
      selectedClaimId: null,
    });

    this.searchText.set(state.searchText);
    this.statusFilter.set(state.statusFilter);
    this.stageFilter.set(state.stageFilter);
    this.actionFilter.set(state.actionFilter);
    this.selectedClaimId.set(state.selectedClaimId);
    this.resetFollowUpState();
  }

  private moveSelection(step: 1 | -1): void {
    const visibleItems = this.filteredClaims();
    if (visibleItems.length === 0) {
      return;
    }

    const currentId = this.selectedClaimId();
    const currentIndex = visibleItems.findIndex((claim) => claim.id === currentId);
    const nextIndex =
      currentIndex === -1
        ? step === 1
          ? 0
          : visibleItems.length - 1
        : Math.max(0, Math.min(visibleItems.length - 1, currentIndex + step));
    const nextClaim = visibleItems[nextIndex];

    if (nextClaim && nextClaim.id !== currentId) {
      this.onSelectClaim(nextClaim.id);
    }
  }

  private findNextPendingClaim(currentId: number): number | null {
    return (
      this.filteredClaims().find(
        (claim) => claim.id !== currentId && claim.available_actions.length > 0 && (claim.status || '').toLowerCase() !== 'closed'
      )?.id ?? null
    );
  }

  private resetFollowUpState(): void {
    this.nextPendingClaimId.set(null);
    this.followUpMessage.set(null);
  }
}
