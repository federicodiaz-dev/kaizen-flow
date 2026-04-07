import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';

import {
  PostSaleConversationDetail,
  PostSaleConversationSummary,
} from '../../core/models/post-sale-messages.models';
import { AccountContextService } from '../../core/services/account-context.service';
import {
  PostSaleMessageListComponent,
  PostSaleStatusFilter,
} from './post-sale-message-list.component';
import { PostSaleMessageDetailComponent } from './post-sale-message-detail.component';
import { PostSaleMessagesApiService } from './post-sale-messages-api.service';

@Component({
  selector: 'app-post-sale-messages-page',
  standalone: true,
  imports: [CommonModule, PostSaleMessageListComponent, PostSaleMessageDetailComponent],
  templateUrl: './post-sale-messages-page.component.html',
  styleUrl: './post-sale-messages-page.component.scss'
})
export class PostSaleMessagesPageComponent {
  private readonly api = inject(PostSaleMessagesApiService);
  readonly accountContext = inject(AccountContextService);

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

  readonly filteredConversations = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    return this.conversations().filter((conversation) => {
      const status = (conversation.conversation_status || '').toLowerCase();
      const matchesStatus =
        this.statusFilter() === 'all' ||
        (this.statusFilter() === 'unread'
          ? conversation.unread_count > 0
          : this.statusFilter() === 'blocked'
            ? status === 'blocked'
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
  });
  readonly totalConversations = computed(() => this.conversations().length);
  readonly unreadConversations = computed(() => this.conversations().filter((item) => item.unread_count > 0).length);
  readonly blockedConversations = computed(
    () => this.conversations().filter((item) => (item.conversation_status || '').toLowerCase() === 'blocked').length
  );
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(
      () => {
        const account = this.accountContext.currentAccount();
        if (account?.is_active) {
          untracked(() => this.loadConversations(account.key));
        }
      },
      { allowSignalWrites: true }
    );
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
          items.map((item) => (item.pack_id === response.pack_id ? { ...item, unread_count: response.unread_count } : item))
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
    this.selectedPackId.set(packId);
    this.loadConversationDetail(packId, true);
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
}
