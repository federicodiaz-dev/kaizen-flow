import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule, DatePipe } from '@angular/common';
import { Component, DestroyRef, ElementRef, effect, input, output, signal, computed, inject, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { ClaimDetail } from '../../core/models/claims.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { ReplyAssistantApiService } from '../reply-assistant/reply-assistant-api.service';

@Component({
  selector: 'app-claim-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './claim-detail.component.html',
  styleUrl: './claim-detail.component.scss'
})
export class ClaimDetailComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly accountContext = inject(AccountContextService);
  private readonly replyAssistantApi = inject(ReplyAssistantApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly composerTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('composerTextarea');
  private readonly animationKey = 'claim-detail-message';

  readonly claim = input<ClaimDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly sending = input(false);

  readonly sendMessage = output<{ message: string; receiverRole?: string }>();

  readonly messageText = signal('');
  readonly receiverRoleOptions = signal<string[]>([]);
  readonly draftingMessage = signal(false);
  readonly draftError = signal<string | null>(null);
  readonly composerOverflowing = signal(false);
  readonly composerExpanded = signal(false);
  
  readonly activeChatTab = signal<'buyer' | 'ml'>('buyer');

  readonly buyerMessages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    return claim.messages
      .filter(m => m.sender_role !== 'mediator' && m.receiver_role !== 'mediator')
      .sort((a, b) => new Date(a.date_created || 0).getTime() - new Date(b.date_created || 0).getTime());
  });

  readonly mlMessages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    return claim.messages
      .filter(m => m.sender_role === 'mediator' || m.receiver_role === 'mediator')
      .sort((a, b) => new Date(a.date_created || 0).getTime() - new Date(b.date_created || 0).getTime());
  });

  readonly isMLIntervened = computed(() => {
    const claim = this.claim();
    if (!claim) return false;
    return this.isMLClaim(claim.type) || claim.stage !== 'claim';
  });

  constructor() {
    this.destroyRef.onDestroy(() => this.typewriter.cancel(this.animationKey));

    effect(() => {
      const currentClaim = this.claim();
      this.typewriter.cancel(this.animationKey);
      this.messageText.set('');
      this.draftError.set(null);
      this.composerExpanded.set(false);
      this.composerOverflowing.set(false);
      const roles = currentClaim?.allowed_receiver_roles ?? [];
      this.receiverRoleOptions.set(roles);
      
      if (this.isMLIntervened()) {
        this.activeChatTab.set('ml');
      } else {
        this.activeChatTab.set('buyer');
      }

      queueMicrotask(() => this.resizeComposer());
    }, { allowSignalWrites: true });
  }

  setTab(tab: 'buyer' | 'ml') {
    this.typewriter.cancel(this.animationKey);
    this.activeChatTab.set(tab);
    this.messageText.set('');
    this.draftError.set(null);
    this.composerExpanded.set(false);
    this.composerOverflowing.set(false);
    queueMicrotask(() => this.resizeComposer());
  }

  submitMessage(): void {
    this.typewriter.finish(this.animationKey);
    const message = this.messageText().trim();
    if (!message) {
      return;
    }

    const receiverRole = this.activeChatTab() === 'buyer' ? 'complainant' : 'mediator';
    this.sendMessage.emit({ message, receiverRole });
  }

  generateDraft(): void {
    const claim = this.claim();
    const account = this.accountContext.selectedAccount();
    if (!claim || !account || this.draftingMessage() || !claim.can_message) {
      return;
    }

    const receiverRole = this.activeChatTab() === 'buyer' ? 'complainant' : 'mediator';
    if (!claim.allowed_receiver_roles.includes(receiverRole)) {
      return;
    }

    this.draftingMessage.set(true);
    this.draftError.set(null);

    this.replyAssistantApi
      .suggestClaimMessage(account, claim.id, {
        receiver_role: receiverRole,
        current_draft: this.messageText().trim() || null,
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
            },
          });
        },
        error: (error) => {
          this.draftError.set(this.getErrorMessage(error, 'No se pudo generar el borrador con IA.'));
          this.draftingMessage.set(false);
        },
      });
  }

  roleLabel(role: string | null | undefined): string {
    if (!role) return 'Desconocido';
    const r = role.toLowerCase().trim();
    if (r === 'complainant' || r === 'buyer') return 'Comprador';
    if (r === 'respondent' || r === 'seller') return 'Vendedor';
    if (r === 'mediator' || r === 'internal') return 'Mercado Libre';
    return role;
  }

  translateType(val: string | null | undefined): string {
    if (!val) return 'Desconocido';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = { mediations: 'Mediación con ML', claims: 'Reclamo de Comprador', disputes: 'Disputa', return: 'Devolución', cancel: 'Cancelación' };
    return map[key] || val;
  }

  translateStage(val: string | null | undefined): string {
    if (!val) return 'N/D';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = { dispute: 'En Disputa', mediation: 'En Mediación', claim: 'En Reclamo' };
    return map[key] || val;
  }

  translateStatus(val: string | null | undefined): string {
    if (!val) return 'N/D';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = { opened: 'Abierto', closed: 'Cerrado', pending: 'Pendiente' };
    return map[key] || val;
  }

  isMLClaim(val: string | null | undefined): boolean {
    if (!val) return false;
    const key = val.toLowerCase().trim();
    return key === 'mediations' || key === 'disputes';
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
    const maxHeight = this.composerExpanded() ? 560 : 360;
    const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
    const hasOverflow = textarea.scrollHeight > maxHeight;

    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = hasOverflow ? 'auto' : 'hidden';
    this.composerOverflowing.set(hasOverflow);
  }
}
