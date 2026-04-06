import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule, DatePipe } from '@angular/common';
import { Component, DestroyRef, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { QuestionDetail } from '../../core/models/questions.models';
import { AccountContextService } from '../../core/services/account-context.service';
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
  private readonly replyAssistantApi = inject(ReplyAssistantApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly animationKey = 'question-detail-answer';

  readonly question = input<QuestionDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly submitting = input(false);

  readonly submitAnswer = output<string>();
  readonly answerText = signal('');
  readonly draftingAnswer = signal(false);
  readonly draftError = signal<string | null>(null);

  constructor() {
    this.destroyRef.onDestroy(() => this.typewriter.cancel(this.animationKey));

    effect(() => {
      const currentQuestion = this.question();
      this.typewriter.cancel(this.animationKey);
      this.answerText.set(currentQuestion?.has_answer ? currentQuestion.answer?.text || '' : '');
      this.draftError.set(null);
    }, { allowSignalWrites: true });
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
}
