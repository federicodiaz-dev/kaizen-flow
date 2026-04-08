import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule, DatePipe } from '@angular/common';
import { Component, DestroyRef, ElementRef, HostListener, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { QuestionDetail } from '../../core/models/questions.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
import { ReplyAssistantApiService } from '../reply-assistant/reply-assistant-api.service';

@Component({
  selector: 'app-question-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './question-detail.component.html',
  styleUrl: './question-detail.component.scss'
})
export class QuestionDetailComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly accountContext = inject(AccountContextService);
  private readonly workspaceState = inject(WorkspaceStateService);
  private readonly replyAssistantApi = inject(ReplyAssistantApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly answerTextarea = viewChild<ElementRef<HTMLTextAreaElement>>('answerTextarea');
  private readonly animationKey = 'question-detail-answer';
  private readonly storageKey = 'questions-detail';
  private lastClearDraftToken = 0;

  readonly question = input<QuestionDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly submitting = input(false);
  readonly nextPendingMessage = input<string | null>(null);
  readonly hasNextPending = input(false);
  readonly clearDraftToken = input(0);

  readonly submitAnswer = output<string>();
  readonly jumpToNextPending = output<void>();
  readonly answerText = signal('');
  readonly draftingAnswer = signal(false);
  readonly draftError = signal<string | null>(null);

  constructor() {
    this.destroyRef.onDestroy(() => this.typewriter.cancel(this.animationKey));

    effect(() => {
      const currentQuestion = this.question();
      const account = this.accountContext.selectedAccount();
      const clearDraftToken = this.clearDraftToken();

      this.typewriter.cancel(this.animationKey);
      this.draftError.set(null);

      if (!currentQuestion) {
        this.answerText.set('');
        return;
      }

      if (account && clearDraftToken !== this.lastClearDraftToken) {
        this.workspaceState.removeDraft(this.storageKey, account, this.draftKey(currentQuestion.id));
        this.lastClearDraftToken = clearDraftToken;
      }

      if (currentQuestion.has_answer) {
        if (account) {
          this.workspaceState.removeDraft(this.storageKey, account, this.draftKey(currentQuestion.id));
        }
        this.answerText.set(currentQuestion.answer?.text || '');
        return;
      }

      const nextText = account
        ? this.workspaceState.loadDraft<{ text: string }>(
            this.storageKey,
            account,
            this.draftKey(currentQuestion.id),
            { text: currentQuestion.answer?.text || '' }
          ).text
        : currentQuestion.answer?.text || '';
      this.answerText.set(nextText);
    }, { allowSignalWrites: true });

    effect(() => {
      const currentQuestion = this.question();
      const account = this.accountContext.selectedAccount();
      const text = this.answerText();
      if (!currentQuestion || !account || currentQuestion.has_answer) {
        return;
      }

      if (text.trim()) {
        this.workspaceState.saveDraft(this.storageKey, account, this.draftKey(currentQuestion.id), { text });
      } else {
        this.workspaceState.removeDraft(this.storageKey, account, this.draftKey(currentQuestion.id));
      }
    }, { allowSignalWrites: true });
  }

  @HostListener('window:keydown', ['$event'])
  handleKeyboardShortcut(event: KeyboardEvent): void {
    const textarea = this.answerTextarea()?.nativeElement;
    if (!textarea || document.activeElement !== textarea) {
      return;
    }

    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      this.sendAnswer();
    }
  }

  sendAnswer(): void {
    this.typewriter.finish(this.animationKey);
    const value = this.answerText().trim();
    if (!value) {
      return;
    }
    this.submitAnswer.emit(value);
  }

  updateAnswerText(value: string): void {
    this.typewriter.cancel(this.animationKey);
    this.answerText.set(value);
    this.draftError.set(null);
  }

  generateDraft(): void {
    const question = this.question();
    const account = this.accountContext.selectedAccount();
    if (!question || !account || this.draftingAnswer() || question.has_answer || !question.can_answer) {
      return;
    }

    this.draftingAnswer.set(true);
    this.draftError.set(null);

    this.replyAssistantApi
      .suggestQuestionAnswer(account, question.id, {
        current_draft: this.answerText().trim() || null,
      })
      .subscribe({
        next: (response) => {
          this.draftingAnswer.set(false);
          this.typewriter.revealText({
            key: this.animationKey,
            text: response.draft_answer,
            from: this.answerText(),
            onUpdate: (value) => this.answerText.set(value),
          });
        },
        error: (error) => {
          this.draftError.set(this.getErrorMessage(error, 'No se pudo generar el borrador con IA.'));
          this.draftingAnswer.set(false);
        },
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

  private draftKey(questionId: number): string {
    return `question:${questionId}`;
  }
}
