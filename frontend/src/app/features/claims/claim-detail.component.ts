import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule, DatePipe } from '@angular/common';
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

import { ClaimDetail } from '../../core/models/claims.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
import { ReplyAssistantApiService } from '../reply-assistant/reply-assistant-api.service';

type ClaimChatTab = 'buyer' | 'ml';

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
  private readonly workspaceState = inject(WorkspaceStateService);
  private readonly replyAssistantApi = inject(ReplyAssistantApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly composerTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('composerTextarea');
  private readonly animationKey = 'claim-detail-message';
  private readonly storageKey = 'claims-detail';
  private lastClearDraftToken = 0;

  readonly claim = input<ClaimDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly sending = input(false);
  readonly nextPendingMessage = input<string | null>(null);
  readonly hasNextPending = input(false);
  readonly clearDraftToken = input(0);

  readonly sendMessage = output<{ message: string; receiverRole?: string }>();
  readonly jumpToNextPending = output<void>();

  readonly messageText = signal('');
  readonly draftingMessage = signal(false);
  readonly draftError = signal<string | null>(null);
  readonly composerOverflowing = signal(false);
  readonly composerExpanded = signal(false);
  readonly activeChatTab = signal<ClaimChatTab>('buyer');

  readonly buyerMessages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    return claim.messages
      .filter((message) => message.sender_role !== 'mediator' && message.receiver_role !== 'mediator')
      .sort((left, right) => this.resolveDate(left.date_created) - this.resolveDate(right.date_created));
  });

  readonly mlMessages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    return claim.messages
      .filter((message) => message.sender_role === 'mediator' || message.receiver_role === 'mediator')
      .sort((left, right) => this.resolveDate(left.date_created) - this.resolveDate(right.date_created));
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
      const account = this.accountContext.selectedAccount();
      const clearDraftToken = this.clearDraftToken();

      this.typewriter.cancel(this.animationKey);
      this.draftError.set(null);

      if (!currentClaim) {
        this.messageText.set('');
        this.composerExpanded.set(false);
        this.composerOverflowing.set(false);
        this.activeChatTab.set('buyer');
        queueMicrotask(() => this.resizeComposer());
        return;
      }

      if (account && clearDraftToken !== this.lastClearDraftToken) {
        this.workspaceState.removeDraft(
          this.storageKey,
          account,
          this.draftKey(currentClaim.id, this.activeChatTab())
        );
        this.lastClearDraftToken = clearDraftToken;
      }

      const defaultTab = this.defaultTabForClaim(currentClaim);
      const restoredTab = account
        ? this.workspaceState.loadUiState<{ activeChatTab: ClaimChatTab }>(
            this.tabStorageKey(currentClaim.id),
            account,
            { activeChatTab: defaultTab }
          ).activeChatTab
        : defaultTab;

      this.activeChatTab.set(restoredTab);
      this.loadDraftForTab(currentClaim, account, restoredTab);
    }, { allowSignalWrites: true });

    effect(() => {
      const currentClaim = this.claim();
      const account = this.accountContext.selectedAccount();
      const activeTab = this.activeChatTab();
      if (!currentClaim) {
        return;
      }

      if (account) {
        this.workspaceState.saveUiState(this.tabStorageKey(currentClaim.id), account, {
          activeChatTab: activeTab,
        });
      }

      this.loadDraftForTab(currentClaim, account, activeTab);
    }, { allowSignalWrites: true });

    effect(() => {
      const currentClaim = this.claim();
      const account = this.accountContext.selectedAccount();
      const activeTab = this.activeChatTab();
      const text = this.messageText();
      const expanded = this.composerExpanded();
      if (!currentClaim || !account) {
        return;
      }

      if (text.trim()) {
        this.workspaceState.saveDraft(this.storageKey, account, this.draftKey(currentClaim.id, activeTab), {
          text,
          expanded,
        });
      } else {
        this.workspaceState.removeDraft(this.storageKey, account, this.draftKey(currentClaim.id, activeTab));
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

  setTab(tab: ClaimChatTab): void {
    this.typewriter.cancel(this.animationKey);
    this.activeChatTab.set(tab);
    this.draftError.set(null);
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
    const normalized = role.toLowerCase().trim();
    if (normalized === 'complainant' || normalized === 'buyer') return 'Comprador';
    if (normalized === 'respondent' || normalized === 'seller') return 'Vendedor';
    if (normalized === 'mediator' || normalized === 'internal') return 'Mercado Libre';
    return role;
  }

  translateType(value: string | null | undefined): string {
    if (!value) return 'Desconocido';
    const key = value.toLowerCase().trim();
    const map: Record<string, string> = {
      mediations: 'Mediacion con ML',
      claims: 'Reclamo de Comprador',
      disputes: 'Disputa',
      return: 'Devolucion',
      cancel: 'Cancelacion'
    };
    return map[key] || value;
  }

  translateStage(value: string | null | undefined): string {
    if (!value) return 'N/D';
    const key = value.toLowerCase().trim();
    const map: Record<string, string> = { dispute: 'En Disputa', mediation: 'En Mediacion', claim: 'En Reclamo' };
    return map[key] || value;
  }

  translateStatus(value: string | null | undefined): string {
    if (!value) return 'N/D';
    const key = value.toLowerCase().trim();
    const map: Record<string, string> = { opened: 'Abierto', closed: 'Cerrado', pending: 'Pendiente' };
    return map[key] || value;
  }

  isMLClaim(value: string | null | undefined): boolean {
    if (!value) return false;
    const key = value.toLowerCase().trim();
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

  private resolveDate(value: string | null): number {
    return value ? new Date(value).getTime() : 0;
  }

  private defaultTabForClaim(claim: ClaimDetail): ClaimChatTab {
    return this.isMLClaim(claim.type) || claim.stage !== 'claim' ? 'ml' : 'buyer';
  }

  private loadDraftForTab(claim: ClaimDetail, account: string | null, tab: ClaimChatTab): void {
    const draft = account
      ? this.workspaceState.loadDraft<{ text: string; expanded: boolean }>(
          this.storageKey,
          account,
          this.draftKey(claim.id, tab),
          { text: '', expanded: false }
        )
      : { text: '', expanded: false };

    this.messageText.set(draft.text || '');
    this.composerExpanded.set(Boolean(draft.expanded));
    this.composerOverflowing.set(false);
    queueMicrotask(() => this.resizeComposer());
  }

  private draftKey(claimId: number, tab: ClaimChatTab): string {
    return `claim:${claimId}:${tab}`;
  }

  private tabStorageKey(claimId: number): string {
    return `claims-tab:${claimId}`;
  }
}
