import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';

import { QuestionFilter, QuestionDetail, QuestionSummary } from '../../core/models/questions.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { QuestionDetailComponent } from './question-detail.component';
import { QuestionListComponent } from './question-list.component';
import { QuestionsApiService } from './questions-api.service';

@Component({
  selector: 'app-questions-page',
  standalone: true,
  imports: [CommonModule, QuestionListComponent, QuestionDetailComponent],
  templateUrl: './questions-page.component.html',
  styleUrl: './questions-page.component.scss'
})
export class QuestionsPageComponent {
  private readonly api = inject(QuestionsApiService);
  readonly accountContext = inject(AccountContextService);

  readonly questions = signal<QuestionSummary[]>([]);
  readonly selectedQuestionId = signal<number | null>(null);
  readonly selectedQuestion = signal<QuestionDetail | null>(null);
  readonly loadingList = signal(false);
  readonly loadingDetail = signal(false);
  readonly submitting = signal(false);
  readonly listError = signal<string | null>(null);
  readonly detailError = signal<string | null>(null);
  readonly searchText = signal('');
  readonly statusFilter = signal<QuestionFilter>('all');

  readonly filteredQuestions = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    return this.questions().filter((question) => {
      const matchesStatus =
        this.statusFilter() === 'all' ||
        (this.statusFilter() === 'answered' ? question.has_answer : !question.has_answer);
      const matchesQuery =
        !query ||
        question.text.toLowerCase().includes(query) ||
        (question.item?.title || '').toLowerCase().includes(query) ||
        question.id.toString().includes(query);
      return matchesStatus && matchesQuery;
    });
  });
  readonly totalQuestions = computed(() => this.questions().length);
  readonly pendingQuestions = computed(() => this.questions().filter((question) => !question.has_answer).length);
  readonly answeredQuestions = computed(() => this.questions().filter((question) => question.has_answer).length);
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(() => {
      const account = this.accountContext.currentAccount();
      if (account?.is_active) {
        untracked(() => this.loadQuestions(account.key));
      }
    }, { allowSignalWrites: true });
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

  loadQuestions(account: string): void {
    this.loadingList.set(true);
    this.listError.set(null);
    this.api.list(account).subscribe({
      next: (response) => {
        this.questions.set(response.items);
        const currentId = this.selectedQuestionId();
        const fallbackId = response.items[0]?.id ?? null;
        const nextId = response.items.some((item) => item.id === currentId) ? currentId : fallbackId;
        this.selectedQuestionId.set(nextId);
        if (nextId) {
          this.loadQuestionDetail(nextId);
        } else {
          this.selectedQuestion.set(null);
        }
        this.loadingList.set(false);
      },
      error: (error) => {
        this.listError.set(this.getErrorMessage(error, 'No se pudieron cargar las preguntas.'));
        this.loadingList.set(false);
      }
    });
  }

  loadQuestionDetail(questionId: number): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.loadingDetail.set(true);
    this.detailError.set(null);
    this.api.detail(account, questionId).subscribe({
      next: (response) => {
        this.selectedQuestion.set(response);
        this.loadingDetail.set(false);
      },
      error: (error) => {
        this.detailError.set(this.getErrorMessage(error, 'No se pudo cargar el detalle de la pregunta.'));
        this.loadingDetail.set(false);
      }
    });
  }

  onSelectQuestion(questionId: number): void {
    this.selectedQuestionId.set(questionId);
    this.loadQuestionDetail(questionId);
  }

  onSubmitAnswer(text: string): void {
    const account = this.accountContext.selectedAccount();
    const questionId = this.selectedQuestionId();
    if (!account || !questionId) {
      return;
    }

    this.submitting.set(true);
    this.detailError.set(null);
    this.api.answer(account, questionId, text).subscribe({
      next: (response) => {
        this.selectedQuestion.set(response);
        this.questions.update((questions) =>
          questions.map((question) => (question.id === response.id ? response : question))
        );
        this.submitting.set(false);
      },
      error: (error) => {
        this.detailError.set(
          this.getErrorMessage(error, 'No se pudo enviar la respuesta a Mercado Libre.')
        );
        this.submitting.set(false);
      }
    });
  }
}
