import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule, CurrencyPipe, DatePipe } from '@angular/common';
import {
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { PostSaleConversationDetail } from '../../core/models/post-sale-messages.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { ReplyAssistantApiService } from '../reply-assistant/reply-assistant-api.service';

@Component({
  selector: 'app-post-sale-message-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe, CurrencyPipe],
  templateUrl: './post-sale-message-detail.component.html',
  styleUrl: './post-sale-message-detail.component.scss'
})
export class PostSaleMessageDetailComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly accountContext = inject(AccountContextService);
  private readonly replyAssistantApi = inject(ReplyAssistantApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly composerTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('composerTextarea');
  private readonly animationKey = 'post-sale-message-detail';

  readonly conversation = input<PostSaleConversationDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly sending = input(false);

  readonly sendReply = output<string>();

  readonly messageText = signal('');
  readonly draftingMessage = signal(false);
  readonly draftError = signal<string | null>(null);
  readonly composerOverflowing = signal(false);
  readonly composerExpanded = signal(false);

  readonly buyerLabel = computed(() => {
    const conversation = this.conversation();
    if (!conversation) return 'Comprador';
    return (
      conversation.buyer_name ||
      conversation.buyer_nickname ||
      (conversation.buyer_user_id ? `Comprador ${conversation.buyer_user_id}` : 'Comprador')
    );
  });

  constructor() {
    this.destroyRef.onDestroy(() => this.typewriter.cancel(this.animationKey));

    effect(
      () => {
        this.conversation();
        this.typewriter.cancel(this.animationKey);
        this.messageText.set('');
        this.draftError.set(null);
        this.composerExpanded.set(false);
        this.composerOverflowing.set(false);
        queueMicrotask(() => this.resizeComposer());
      },
      { allowSignalWrites: true }
    );
  }

  statusLabel(status: string | null | undefined): string {
    if (!status) return 'Sin estado';
    const key = status.toLowerCase().trim();
    const map: Record<string, string> = {
      active: 'Activa',
      blocked: 'Bloqueada'
    };
    return map[key] || status;
  }

  packStatusLabel(status: string | null | undefined): string {
    if (!status) return 'N/D';
    const key = status.toLowerCase().trim();
    const map: Record<string, string> = {
      paid: 'Pagada',
      payment_required: 'Pago requerido',
      payment_in_process: 'Pago en proceso',
      confirmed: 'Confirmada',
      cancelled: 'Cancelada'
    };
    return map[key] || status;
  }

  updateMessageText(value: string): void {
    this.typewriter.cancel(this.animationKey);
    this.messageText.set(value);
    this.draftError.set(null);
    queueMicrotask(() => this.resizeComposer());
  }

  toggleComposerExpanded(): void {
    this.composerExpanded.update((expanded) => !expanded);
    queueMicrotask(() => this.resizeComposer());
  }

  submitMessage(): void {
    this.typewriter.finish(this.animationKey);
    const message = this.messageText().trim();
    if (!message) {
      return;
    }
    this.sendReply.emit(message);
  }

  generateDraft(): void {
    const conversation = this.conversation();
    const account = this.accountContext.selectedAccount();
    if (!conversation || !account || this.draftingMessage() || !conversation.can_reply) {
      return;
    }

    this.draftingMessage.set(true);
    this.draftError.set(null);

    this.replyAssistantApi
      .suggestPostSaleMessage(account, conversation.pack_id, {
        current_draft: this.messageText().trim() || null
      })
      .subscribe({
        next: (response) => {
          this.draftingMessage.set(false);
          this.typewriter.revealText({
            key: this.animationKey,
            text: response.draft_message,
            from: this.messageText(),
            onUpdate: (value) => {
              this.messageText.set(value);
              this.resizeComposer();
            }
          });
        },
        error: (error) => {
          this.draftError.set(this.getErrorMessage(error, 'No se pudo generar el borrador con IA.'));
          this.draftingMessage.set(false);
        }
      });
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

  private resizeComposer(): void {
    const textarea = this.composerTextarea()?.nativeElement;
    if (!textarea) {
      this.composerOverflowing.set(false);
      return;
    }

    textarea.style.height = 'auto';
    const minHeight = 160;
    const maxHeight = this.composerExpanded() ? 520 : 320;
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
    const hasOverflow = textarea.scrollHeight > maxHeight;

    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = hasOverflow ? 'auto' : 'hidden';
    this.composerOverflowing.set(hasOverflow);
  }
}
