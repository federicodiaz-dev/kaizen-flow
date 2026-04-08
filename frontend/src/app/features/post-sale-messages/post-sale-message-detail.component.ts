import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule, CurrencyPipe, DatePipe } from '@angular/common';
import {
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
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
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
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
  private readonly workspaceState = inject(WorkspaceStateService);
  private readonly replyAssistantApi = inject(ReplyAssistantApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly composerTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('composerTextarea');
  private readonly animationKey = 'post-sale-message-detail';
  private readonly storageKey = 'post-sale-detail';
  private lastClearDraftToken = 0;

  readonly conversation = input<PostSaleConversationDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly sending = input(false);
  readonly nextPendingMessage = input<string | null>(null);
  readonly hasNextPending = input(false);
  readonly clearDraftToken = input(0);

  readonly sendReply = output<string>();
  readonly resolveBlock = output<{ message: string }>();
  readonly closeDetail = output<void>();
  readonly jumpToNextPending = output<void>();

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
        const conversation = this.conversation();
        const account = this.accountContext.selectedAccount();
        const clearDraftToken = this.clearDraftToken();

        this.typewriter.cancel(this.animationKey);
        this.draftError.set(null);

        if (!conversation) {
          this.messageText.set('');
          this.composerExpanded.set(false);
          this.composerOverflowing.set(false);
          queueMicrotask(() => this.resizeComposer());
          return;
        }

        if (account && clearDraftToken !== this.lastClearDraftToken) {
          this.workspaceState.removeDraft(this.storageKey, account, this.draftKey(conversation.pack_id));
          this.lastClearDraftToken = clearDraftToken;
        }

        const nextText = account
          ? this.workspaceState.loadDraft<{ text: string; expanded: boolean }>(
              this.storageKey,
              account,
              this.draftKey(conversation.pack_id),
              { text: '', expanded: false }
            )
          : { text: '', expanded: false };

        this.messageText.set(nextText.text || '');
        this.composerExpanded.set(Boolean(nextText.expanded));
        this.composerOverflowing.set(false);
        queueMicrotask(() => this.resizeComposer());
      },
      { allowSignalWrites: true }
    );

    effect(() => {
      const conversation = this.conversation();
      const account = this.accountContext.selectedAccount();
      const text = this.messageText();
      const expanded = this.composerExpanded();
      if (!conversation || !account) {
        return;
      }

      if (text.trim()) {
        this.workspaceState.saveDraft(this.storageKey, account, this.draftKey(conversation.pack_id), {
          text,
          expanded,
        });
      } else {
        this.workspaceState.removeDraft(this.storageKey, account, this.draftKey(conversation.pack_id));
      }
    }, { allowSignalWrites: true });
  }

  @HostListener('window:keydown', ['$event'])
  handleKeyboardShortcut(event: KeyboardEvent): void {
    const textarea = this.composerTextarea()?.nativeElement;
    if (!textarea || document.activeElement !== textarea) {
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      this.submitMessage();
    }
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

  private draftKey(packId: string): string {
    return `pack:${packId}`;
  }
}
