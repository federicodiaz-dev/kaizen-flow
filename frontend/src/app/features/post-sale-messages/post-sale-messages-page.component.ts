import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Component, HostListener, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';

import {
  PostSaleConversationDetail,
  PostSaleConversationSummary,
} from '../../core/models/post-sale-messages.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
import { isEditableTarget } from '../../core/utils/keyboard.utils';
import { PostSaleMessageDetailComponent } from './post-sale-message-detail.component';
import {
  PostSaleMessageListComponent,
  PostSaleSortOrder,
  PostSaleStatusFilter,
} from './post-sale-message-list.component';
import { PostSaleMessagesApiService } from './post-sale-messages-api.service';

type PostSaleUiState = {
  searchText: string;
  statusFilter: PostSaleStatusFilter;
  sortOrder: PostSaleSortOrder;
  selectedPackId: string | null;
};

@Component({
  selector: 'app-post-sale-messages-page',
  standalone: true,
  imports: [CommonModule, PostSaleMessageListComponent, PostSaleMessageDetailComponent],
  templateUrl: './post-sale-messages-page.component.html',
  styleUrl: './post-sale-messages-page.component.scss'
})
export class PostSaleMessagesPageComponent {
  private readonly api = inject(PostSaleMessagesApiService);
  private readonly workspaceState = inject(WorkspaceStateService);
  readonly accountContext = inject(AccountContextService);
  private readonly listComponent = viewChild(PostSaleMessageListComponent);
  private readonly storageKey = 'post-sale-workspace';

  readonly conversations = signal<PostSaleConversationSummary[]>([]);
  readonly selectedPackId = signal<string | null>(null);
  readonly selectedConversation = signal<PostSaleConversationDetail | null>(null);
  readonly loadingList = signal(false);
  readonly loadingDetail = signal(false);
  readonly sending = signal(false);
  readonly listError = signal<string | null>(null);
  readonly detailError = signal<string | null>(null);
  readonly searchText = signal('');
  readonly statusFilter = signal<PostSaleStatusFilter>('all');
  readonly sortOrder = signal<PostSaleSortOrder>('recent');
  readonly nextPendingPackId = signal<string | null>(null);
  readonly followUpMessage = signal<string | null>(null);
  readonly clearDraftToken = signal(0);

  readonly filteredConversations = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    const statusFilter = this.statusFilter();
    const conversations = [...this.conversations()].filter((conversation) => {
      const status = (conversation.conversation_status || '').toLowerCase();
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'unread'
          ? conversation.unread_count > 0
          : statusFilter === 'blocked'
            ? status === 'blocked'
            : statusFilter === 'claim'
              ? conversation.claim_ids.length > 0
              : status === 'active');
      const matchesQuery =
        !query ||
        conversation.pack_id.toLowerCase().includes(query) ||
        (conversation.buyer_name || '').toLowerCase().includes(query) ||
        (conversation.buyer_nickname || '').toLowerCase().includes(query) ||
        (conversation.primary_item_title || '').toLowerCase().includes(query) ||
        conversation.order_ids.some((orderId) => orderId.toString().includes(query));

      return matchesStatus && matchesQuery;
    });

    conversations.sort((left, right) => {
      const leftDate = this.resolveDateValue(left.last_updated || left.date_created);
      const rightDate = this.resolveDateValue(right.last_updated || right.date_created);
      return this.sortOrder() === 'oldest' ? leftDate - rightDate : rightDate - leftDate;
    });
    return conversations;
  });
  readonly totalConversations = computed(() => this.conversations().length);
  readonly filteredCount = computed(() => this.filteredConversations().length);
  readonly unreadConversations = computed(() => this.conversations().filter((item) => item.unread_count > 0).length);
  readonly blockedConversations = computed(
    () => this.conversations().filter((item) => (item.conversation_status || '').toLowerCase() === 'blocked').length
  );
  readonly activeFilterCount = computed(() => {
    let total = 0;
    if (this.searchText().trim()) total += 1;
    if (this.statusFilter() !== 'all') total += 1;
    if (this.sortOrder() !== 'recent') total += 1;
    return total;
  });
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(
      () => {
        const account = this.accountContext.currentAccount();
        if (account?.is_active) {
          untracked(() => {
            this.restoreUiState(account.key);
            this.loadConversations(account.key);
          });
        }
      },
      { allowSignalWrites: true }
    );

    effect(() => {
      const account = this.accountContext.selectedAccount();
      if (!account) {
        return;
      }

      this.workspaceState.saveUiState<PostSaleUiState>(this.storageKey, account, {
        searchText: this.searchText(),
        statusFilter: this.statusFilter(),
        sortOrder: this.sortOrder(),
        selectedPackId: this.selectedPackId(),
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

  loadConversations(account: string): void {
    this.loadingList.set(true);
    this.listError.set(null);
    this.api.list(account).subscribe({
      next: (response) => {
        this.conversations.set(response.items);
        const currentPack = this.selectedPackId();
        const fallbackPack = response.items[0]?.pack_id ?? null;
        const nextPack = response.items.some((item) => item.pack_id === currentPack) ? currentPack : fallbackPack;
        this.selectedPackId.set(nextPack);
        if (nextPack) {
          this.loadConversationDetail(nextPack, false);
        } else {
          this.selectedConversation.set(null);
        }
        this.loadingList.set(false);
      },
      error: (error) => {
        this.listError.set(this.getErrorMessage(error, 'No se pudieron cargar los mensajes post venta.'));
        this.loadingList.set(false);
      }
    });
  }

  loadConversationDetail(packId: string, markAsRead = false): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.loadingDetail.set(true);
    this.detailError.set(null);
    this.api.detail(account, packId, markAsRead).subscribe({
      next: (response) => {
        this.selectedConversation.set(response);
        this.conversations.update((items) =>
          items.map((item) =>
            item.pack_id === response.pack_id
              ? { ...item, unread_count: response.unread_count, claim_ids: response.claim_ids }
              : item
          )
        );
        this.loadingDetail.set(false);
      },
      error: (error) => {
        this.detailError.set(this.getErrorMessage(error, 'No se pudo cargar la conversacion del pack.'));
        this.loadingDetail.set(false);
      }
    });
  }

  onSelectConversation(packId: string): void {
    this.resetFollowUpState();
    this.selectedPackId.set(packId);
    this.loadConversationDetail(packId, true);
  }

  closeSelected(): void {
    this.selectedPackId.set(null);
    this.selectedConversation.set(null);
  }

  onSendReply(text: string): void {
    const account = this.accountContext.selectedAccount();
    const packId = this.selectedPackId();
    if (!account || !packId) {
      return;
    }

    this.sending.set(true);
    this.detailError.set(null);
    this.api.reply(account, packId, text).subscribe({
      next: () => {
        const nextPackId = this.findNextPendingConversation(packId);
        this.nextPendingPackId.set(nextPackId);
        this.followUpMessage.set(
          nextPackId
            ? 'Mensaje enviado. Puedes avanzar a la siguiente conversacion pendiente.'
            : 'Mensaje enviado. No quedan conversaciones pendientes en esta vista.'
        );
        this.clearDraftToken.update((value) => value + 1);
        this.loadConversationDetail(packId, true);
        this.loadConversations(account);
        this.sending.set(false);
      },
      error: (error) => {
        this.detailError.set(this.getErrorMessage(error, 'No se pudo responder el mensaje post venta.'));
        this.sending.set(false);
      }
    });
  }

  onSortOrderChange(order: PostSaleSortOrder): void {
    this.sortOrder.set(order);
    this.resetFollowUpState();
  }

  resetFilters(): void {
    this.searchText.set('');
    this.statusFilter.set('all');
    this.sortOrder.set('recent');
  }

  refreshConversations(): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.resetFollowUpState();
    this.loadConversations(account);
  }

  goToNextPendingConversation(): void {
    const nextPackId = this.nextPendingPackId();
    if (!nextPackId) {
      return;
    }

    this.onSelectConversation(nextPackId);
  }

  private restoreUiState(account: string): void {
    const state = this.workspaceState.loadUiState<PostSaleUiState>(this.storageKey, account, {
      searchText: '',
      statusFilter: 'all',
      sortOrder: 'recent',
      selectedPackId: null,
    });

    this.searchText.set(state.searchText);
    this.statusFilter.set(state.statusFilter);
    this.sortOrder.set(state.sortOrder);
    this.selectedPackId.set(state.selectedPackId);
    this.resetFollowUpState();
  }

  private resolveDateValue(value: string | null): number {
    return value ? new Date(value).getTime() : 0;
  }

  private moveSelection(step: 1 | -1): void {
    const visibleItems = this.filteredConversations();
    if (visibleItems.length === 0) {
      return;
    }

    const currentId = this.selectedPackId();
    const currentIndex = visibleItems.findIndex((conversation) => conversation.pack_id === currentId);
    const nextIndex =
      currentIndex === -1
        ? step === 1
          ? 0
          : visibleItems.length - 1
        : Math.max(0, Math.min(visibleItems.length - 1, currentIndex + step));
    const nextConversation = visibleItems[nextIndex];

    if (nextConversation && nextConversation.pack_id !== currentId) {
      this.onSelectConversation(nextConversation.pack_id);
    }
  }

  private findNextPendingConversation(currentPackId: string): string | null {
    return (
      this.filteredConversations().find(
        (conversation) =>
          conversation.pack_id !== currentPackId &&
          (conversation.unread_count > 0 ||
            conversation.claim_ids.length > 0 ||
            ((conversation.conversation_status || '').toLowerCase() === 'active' && conversation.can_reply))
      )?.pack_id ?? null
    );
  }

  private resetFollowUpState(): void {
    this.nextPendingPackId.set(null);
    this.followUpMessage.set(null);
  }
}
