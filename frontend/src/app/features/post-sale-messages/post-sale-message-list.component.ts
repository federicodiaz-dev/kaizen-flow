import { CommonModule, DatePipe, CurrencyPipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { PostSaleConversationSummary } from '../../core/models/post-sale-messages.models';

export type PostSaleStatusFilter = 'all' | 'unread' | 'active' | 'blocked';

@Component({
  selector: 'app-post-sale-message-list',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe, CurrencyPipe],
  templateUrl: './post-sale-message-list.component.html',
  styleUrl: './post-sale-message-list.component.scss'
})
export class PostSaleMessageListComponent {
  readonly conversations = input<PostSaleConversationSummary[]>([]);
  readonly selectedId = input<string | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly searchText = input('');
  readonly statusFilter = input<PostSaleStatusFilter>('all');

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<PostSaleStatusFilter>();
  readonly refresh = output<void>();
  readonly selectConversation = output<string>();

  statusLabel(status: string | null | undefined): string {
    if (!status) return 'Sin estado';
    const key = status.toLowerCase().trim();
    const map: Record<string, string> = {
      active: 'Activa',
      blocked: 'Bloqueada'
    };
    return map[key] || status;
  }

  statusTone(conversation: PostSaleConversationSummary): 'blocked' | 'active' | 'unread' {
    if ((conversation.conversation_status || '').toLowerCase() === 'blocked') {
      return 'blocked';
    }
    if (conversation.unread_count > 0) {
      return 'unread';
    }
    return 'active';
  }

  buyerLabel(conversation: PostSaleConversationSummary): string {
    return (
      conversation.buyer_name ||
      conversation.buyer_nickname ||
      (conversation.buyer_user_id ? `Comprador ${conversation.buyer_user_id}` : 'Comprador sin identificar')
    );
  }
}
