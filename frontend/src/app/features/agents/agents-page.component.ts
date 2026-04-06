import { CommonModule, DatePipe } from '@angular/common';
import {
  AfterViewChecked,
  Component,
  DestroyRef,
  ElementRef,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import {
  AgentChatMessage,
  AgentMessageResponse,
  AgentThreadSummary,
} from '../../core/models/agent-chat.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { AgentsApiService } from './agents-api.service';

@Component({
  selector: 'app-agents-page',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './agents-page.component.html',
  styleUrl: './agents-page.component.scss',
})
export class AgentsPageComponent implements OnInit, AfterViewChecked {
  private readonly destroyRef = inject(DestroyRef);
  private readonly api = inject(AgentsApiService);
  private readonly typewriter = inject(AiTypewriterService);
  readonly accountContext = inject(AccountContextService);

  @ViewChild('scrollContainer') scrollContainer!: ElementRef<HTMLDivElement>;

  /* ── Reactive state ── */
  readonly threads = signal<AgentThreadSummary[]>([]);
  readonly activeThreadId = signal<string | null>(null);
  readonly activeMessages = signal<AgentChatMessage[]>([]);
  readonly loading = signal(false);
  readonly sidebarLoading = signal(false);
  readonly draft = signal('');
  readonly errorMessage = signal<string | null>(null);
  readonly showSidebar = signal(true);
  readonly assistantTyping = signal(false);

  private shouldScrollToBottom = false;
  private readonly assistantAnimationPrefix = 'agents-assistant-message';

  /* ── Computed ── */
  readonly activeThread = computed(() =>
    this.threads().find((t) => t.thread_id === this.activeThreadId()) ?? null
  );
  readonly activeTitle = computed(() => this.activeThread()?.title ?? 'Nuevo hilo');
  readonly canSend = computed(() => this.draft().trim().length > 0 && !this.loading());
  readonly statusLabel = computed(() =>
    this.loading()
      ? this.thinkingLabel()
      : this.assistantTyping()
        ? 'Escribiendo respuesta...'
        : 'Listo'
  );
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? 'Sin cuenta'
  );

  /* ── Quick prompts ── */
  readonly quickPrompts = [
    '¿Qué reclamos abiertos tengo y qué acciones puedo tomar?',
    '¿Cuáles son mis publicaciones activas con menos stock?',
    'Dame un resumen general del estado de mi cuenta',
    '¿Hay preguntas sin responder en mis publicaciones?',
  ];

  /* ── Thinking labels ── */
  private readonly thinkingLabels = [
    'Analizando tu consulta...',
    'Clasificando intención...',
    'Consultando herramientas...',
    'Componiendo respuesta...',
  ];
  readonly thinkingLabel = signal(this.thinkingLabels[0]);
  private thinkingInterval: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => this.typewriter.cancelPrefix(this.assistantAnimationPrefix));
    this.loadThreads();
  }

  ngAfterViewChecked(): void {
    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  /* ── Thread management ── */
  loadThreads(): void {
    this.sidebarLoading.set(true);
    this.api.listThreads().subscribe({
      next: (threads) => {
        this.threads.set(threads);
        this.sidebarLoading.set(false);
      },
      error: () => {
        this.errorMessage.set('No se pudieron cargar los hilos.');
        this.sidebarLoading.set(false);
      },
    });
  }

  startNewThread(): void {
    this.api.createThread().subscribe({
      next: (thread) => {
        this.threads.update((prev) => [
          {
            thread_id: thread.thread_id,
            title: thread.title,
            created_at: thread.created_at,
            updated_at: thread.updated_at,
            message_count: thread.message_count,
            last_message_preview: thread.last_message_preview,
          },
          ...prev,
        ]);
        this.selectThread(thread.thread_id);
      },
      error: () => this.errorMessage.set('Error al crear el hilo.'),
    });
  }

  selectThread(threadId: string): void {
    if (this.activeThreadId() === threadId) return;
    this.typewriter.cancelPrefix(this.assistantAnimationPrefix);
    this.assistantTyping.set(false);
    this.activeThreadId.set(threadId);
    this.activeMessages.set([]);
    this.errorMessage.set(null);

    this.api.getThread(threadId).subscribe({
      next: (detail) => {
        this.activeMessages.set(detail.messages);
        this.shouldScrollToBottom = true;
      },
      error: () => this.errorMessage.set('Error al cargar el hilo.'),
    });
  }

  isActiveThread(id: string): boolean {
    return this.activeThreadId() === id;
  }

  /* ── Messaging ── */
  sendMessage(): void {
    const activeThreadId = this.activeThreadId();
    if (activeThreadId) {
      this.typewriter.finish(this.getAssistantAnimationKey(activeThreadId));
      this.assistantTyping.set(false);
    }

    const content = this.draft().trim();
    const account = this.accountContext.selectedAccount();
    const threadId = this.activeThreadId();

    if (!content || !account || this.loading()) return;

    if (!threadId) {
      this.api.createThread().subscribe({
        next: (thread) => {
          this.threads.update((prev) => [
            {
              thread_id: thread.thread_id,
              title: thread.title,
              created_at: thread.created_at,
              updated_at: thread.updated_at,
              message_count: thread.message_count,
              last_message_preview: thread.last_message_preview,
            },
            ...prev,
          ]);
          this.activeThreadId.set(thread.thread_id);
          this.dispatchMessage(thread.thread_id, content, account);
        },
        error: () => this.errorMessage.set('Error al crear hilo automáticamente.'),
      });
      return;
    }

    this.dispatchMessage(threadId, content, account);
  }

  private dispatchMessage(threadId: string, content: string, account: string): void {
    // Optimistic user message
    const userMsg: AgentChatMessage = {
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    };
    this.activeMessages.update((prev) => [...prev, userMsg]);
    this.draft.set('');
    this.loading.set(true);
    this.startThinkingAnimation();
    this.shouldScrollToBottom = true;

    this.api.sendMessage(threadId, content, account).subscribe({
      next: (response: AgentMessageResponse) => {
        this.stopThinkingAnimation();
        this.loading.set(false);
        this.renderAssistantResponse(threadId, response);

        // Update sidebar
        this.threads.update((prev) =>
          prev.map((t) =>
            t.thread_id === threadId
              ? {
                  ...t,
                  title: response.thread.title,
                  updated_at: response.thread.updated_at,
                  message_count: response.thread.message_count,
                  last_message_preview: response.thread.last_message_preview,
                }
              : t
          )
        );
      },
      error: (err) => {
        this.stopThinkingAnimation();
        this.loading.set(false);
        this.assistantTyping.set(false);
        const detail = err?.error?.detail;
        this.errorMessage.set(
          typeof detail === 'string' ? detail : 'El agente no pudo procesar tu mensaje.'
        );
      },
    });
  }

  /* ── Thinking animation ── */
  private startThinkingAnimation(): void {
    let idx = 0;
    this.thinkingLabel.set(this.thinkingLabels[0]);
    this.thinkingInterval = setInterval(() => {
      idx = (idx + 1) % this.thinkingLabels.length;
      this.thinkingLabel.set(this.thinkingLabels[idx]);
    }, 2400);
  }

  private stopThinkingAnimation(): void {
    if (this.thinkingInterval) {
      clearInterval(this.thinkingInterval);
      this.thinkingInterval = null;
    }
  }

  /* ── Keyboard handling ── */
  handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  /* ── Quick prompt ── */
  applyQuickPrompt(prompt: string): void {
    this.draft.set(prompt);
    this.sendMessage();
  }

  /* ── Scroll ── */
  private scrollToBottom(): void {
    try {
      const el = this.scrollContainer?.nativeElement;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    } catch {}
  }

  /* ── Formatting ── */
  formatMessage(raw: string): string {
    if (!raw) return '';
    let html = this.escapeHtml(raw);

    // Bold **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Inline code `text`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers ### text
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');

    // Bullet lists
    html = html.replace(/^[-•] (.+)$/gm, '<div class="md-bullet">• $1</div>');

    // Numbered lists
    html = html.replace(/^(\d+)\. (.+)$/gm, '<div class="md-bullet"><strong>$1.</strong> $2</div>');

    // Paragraphs (double newline)
    html = html.replace(/\n\n/g, '</p><p>');
    // Single newlines
    html = html.replace(/\n/g, '<br>');

    return `<p>${html}</p>`;
  }

  private escapeHtml(text: string): string {
    const map: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };
    return text.replace(/[&<>]/g, (char) => map[char] || char);
  }

  formatTimestamp(iso: string): string {
    if (!iso) return '';
    const date = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Ahora';
    if (diffMins < 60) return `Hace ${diffMins}m`;
    if (diffMins < 1440) return `Hace ${Math.floor(diffMins / 60)}h`;
    return date.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' });
  }

  /* ── Metadata helpers ── */
  getMessageRoute(msg: AgentChatMessage): string | null {
    return (msg.metadata?.['route'] as string) ?? null;
  }

  getRouteLabel(route: string): string {
    const map: Record<string, string> = {
      mercadolibre_account: 'Cuenta ML',
      market_intelligence: 'Inteligencia de Mercado',
      clarification: 'Aclaración',
    };
    return map[route] ?? route;
  }

  toggleSidebar(): void {
    this.showSidebar.update((v) => !v);
  }

  private renderAssistantResponse(threadId: string, response: AgentMessageResponse): void {
    this.typewriter.cancelPrefix(this.assistantAnimationPrefix);

    const messages = response.thread.messages.map((message) => ({ ...message }));
    const assistantIndex = this.findAssistantMessageIndex(messages, response.assistant_message);

    if (assistantIndex < 0) {
      this.assistantTyping.set(false);
      this.activeMessages.set(messages);
      this.shouldScrollToBottom = true;
      return;
    }

    messages[assistantIndex] = {
      ...messages[assistantIndex],
      content: '',
    };

    this.activeMessages.set(messages);
    this.assistantTyping.set(true);
    this.shouldScrollToBottom = true;

    this.typewriter.revealText({
      key: this.getAssistantAnimationKey(threadId),
      text: response.assistant_message.content,
      onUpdate: (value) => {
        this.activeMessages.update((current) => {
          if (!current[assistantIndex]) {
            return current;
          }

          const next = [...current];
          next[assistantIndex] = {
            ...next[assistantIndex],
            content: value,
          };
          return next;
        });
        this.shouldScrollToBottom = true;
      },
      onDone: () => {
        this.assistantTyping.set(false);
        this.shouldScrollToBottom = true;
      },
    });
  }

  private findAssistantMessageIndex(
    messages: AgentChatMessage[],
    assistantMessage: AgentChatMessage
  ): number {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const current = messages[index];
      if (
        current.role !== 'user' &&
        current.created_at === assistantMessage.created_at
      ) {
        return index;
      }
    }

    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const current = messages[index];
      if (
        current.role !== 'user' &&
        current.content === assistantMessage.content
      ) {
        return index;
      }
    }

    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role !== 'user') {
        return index;
      }
    }

    return -1;
  }

  private getAssistantAnimationKey(threadId: string): string {
    return `${this.assistantAnimationPrefix}:${threadId}`;
  }
}
