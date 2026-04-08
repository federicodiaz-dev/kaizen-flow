import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { Component, HostListener, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';

import { QuestionDetail, QuestionFilter, QuestionSummary } from '../../core/models/questions.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
import { isEditableTarget } from '../../core/utils/keyboard.utils';
import { QuestionDetailComponent } from './question-detail.component';
import {
  QuestionListComponent,
  QuestionRespondableFilter,
  QuestionSortOrder,
} from './question-list.component';
import { QuestionsApiService } from './questions-api.service';

type QuestionsUiState = {
  searchText: string;
  statusFilter: QuestionFilter;
  respondableFilter: QuestionRespondableFilter;
  sortOrder: QuestionSortOrder;
  selectedQuestionId: number | null;
};

@Component({
  selector: 'app-questions-page',
  standalone: true,
  imports: [CommonModule, QuestionListComponent, QuestionDetailComponent],
  templateUrl: './questions-page.component.html',
  styleUrl: './questions-page.component.scss'
})
export class QuestionsPageComponent {
  private readonly api = inject(QuestionsApiService);
  private readonly workspaceState = inject(WorkspaceStateService);
  readonly accountContext = inject(AccountContextService);
  private readonly listComponent = viewChild(QuestionListComponent);
  private readonly storageKey = 'questions-workspace';

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
  readonly respondableFilter = signal<QuestionRespondableFilter>('all');
  readonly sortOrder = signal<QuestionSortOrder>('recent');
  readonly nextPendingQuestionId = signal<number | null>(null);
  readonly followUpMessage = signal<string | null>(null);

  readonly filteredQuestions = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    const statusFilter = this.statusFilter();
    const respondableFilter = this.respondableFilter();

    const items = [...this.questions()].filter((question) => {
      const matchesStatus =
        statusFilter === 'all' ||
        (statusFilter === 'answered' ? question.has_answer : !question.has_answer);
      const matchesRespondable =
        respondableFilter === 'all' ||
        (respondableFilter === 'respondable' ? question.can_answer : !question.can_answer);
      const matchesQuery =
        !query ||
        question.text.toLowerCase().includes(query) ||
        (question.item?.title || '').toLowerCase().includes(query) ||
        question.id.toString().includes(query);

      return matchesStatus && matchesRespondable && matchesQuery;
    });

    items.sort((left, right) => this.compareQuestions(left, right));
    return items;
  });
  readonly totalQuestions = computed(() => this.questions().length);
  readonly filteredCount = computed(() => this.filteredQuestions().length);
  readonly pendingQuestions = computed(() => this.questions().filter((question) => !question.has_answer).length);
  readonly answeredQuestions = computed(() => this.questions().filter((question) => question.has_answer).length);
  readonly activeFilterCount = computed(() => {
    let total = 0;
    if (this.searchText().trim()) total += 1;
    if (this.statusFilter() !== 'all') total += 1;
    if (this.respondableFilter() !== 'all') total += 1;
    if (this.sortOrder() !== 'recent') total += 1;
    return total;
  });
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(() => {
      const account = this.accountContext.currentAccount();
      if (account?.is_active) {
        untracked(() => {
          this.restoreUiState(account.key);
          this.loadQuestions(account.key);
        });
      }
    }, { allowSignalWrites: true });

    effect(() => {
      const account = this.accountContext.selectedAccount();
      if (!account) {
        return;
      }

      this.workspaceState.saveUiState<QuestionsUiState>(this.storageKey, account, {
        searchText: this.searchText(),
        statusFilter: this.statusFilter(),
        respondableFilter: this.respondableFilter(),
        sortOrder: this.sortOrder(),
        selectedQuestionId: this.selectedQuestionId(),
      });
    }, { allowSignalWrites: true });
  }

  @HostListener('window:keydown', ['$event'])
  handleKeyboardShortcuts(event: KeyboardEvent): void {
    if (event.defaultPrevented) {
      return;
    }

    if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !isEditableTarget(event.target)) {
      event.preventDefault();
      this.listComponent()?.focusSearch();
      return;
    }

    if (isEditableTarget(event.target)) {
      return;
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      this.moveSelection(event.key === 'ArrowDown' ? 1 : -1);
    }
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
    this.resetFollowUpState();
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

        const nextPendingId = this.findNextPendingQuestion(response.id);
        this.nextPendingQuestionId.set(nextPendingId);
        this.followUpMessage.set(
          nextPendingId
            ? 'Respuesta enviada. Puedes seguir con la siguiente pendiente.'
            : 'Respuesta enviada. No quedan preguntas pendientes en esta bandeja.'
        );
        this.submitting.set(false);
      },
      error: (error) => {
        this.detailError.set(this.getErrorMessage(error, 'No se pudo enviar la respuesta a Mercado Libre.'));
        this.submitting.set(false);
      }
    });
  }

  onRespondableFilterChange(filter: QuestionRespondableFilter): void {
    this.respondableFilter.set(filter);
    this.resetFollowUpState();
  }

  onSortOrderChange(order: QuestionSortOrder): void {
    this.sortOrder.set(order);
    this.resetFollowUpState();
  }

  resetFilters(): void {
    this.searchText.set('');
    this.statusFilter.set('all');
    this.respondableFilter.set('all');
    this.sortOrder.set('recent');
  }

  refreshQuestions(): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.resetFollowUpState();
    this.loadQuestions(account);
  }

  goToNextPendingQuestion(): void {
    const nextId = this.nextPendingQuestionId();
    if (!nextId) {
      return;
    }

    this.onSelectQuestion(nextId);
  }

  private restoreUiState(account: string): void {
    const state = this.workspaceState.loadUiState<QuestionsUiState>(this.storageKey, account, {
      searchText: '',
      statusFilter: 'all',
      respondableFilter: 'all',
      sortOrder: 'recent',
      selectedQuestionId: null,
    });

    this.searchText.set(state.searchText);
    this.statusFilter.set(state.statusFilter);
    this.respondableFilter.set(state.respondableFilter);
    this.sortOrder.set(state.sortOrder);
    this.selectedQuestionId.set(state.selectedQuestionId);
    this.resetFollowUpState();
  }

  private compareQuestions(left: QuestionSummary, right: QuestionSummary): number {
    if (this.sortOrder() === 'pending') {
      const leftPriority = Number(!left.has_answer && left.can_answer);
      const rightPriority = Number(!right.has_answer && right.can_answer);
      if (leftPriority !== rightPriority) {
        return rightPriority - leftPriority;
      }
    }

    const leftDate = this.resolveDateValue(left.date_created);
    const rightDate = this.resolveDateValue(right.date_created);
    if (this.sortOrder() === 'oldest') {
      return leftDate - rightDate;
    }
    return rightDate - leftDate;
  }

  private resolveDateValue(value: string | null): number {
    return value ? new Date(value).getTime() : 0;
  }

  private moveSelection(step: 1 | -1): void {
    const visibleItems = this.filteredQuestions();
    if (visibleItems.length === 0) {
      return;
    }

    const currentId = this.selectedQuestionId();
    const currentIndex = visibleItems.findIndex((question) => question.id === currentId);
    const nextIndex =
      currentIndex === -1
        ? step === 1
          ? 0
          : visibleItems.length - 1
        : Math.max(0, Math.min(visibleItems.length - 1, currentIndex + step));
    const nextQuestion = visibleItems[nextIndex];

    if (nextQuestion && nextQuestion.id !== currentId) {
      this.onSelectQuestion(nextQuestion.id);
    }
  }

  private findNextPendingQuestion(currentId: number): number | null {
    return (
      this.filteredQuestions().find(
        (question) => question.id !== currentId && !question.has_answer && question.can_answer
      )?.id ?? null
    );
  }

  private resetFollowUpState(): void {
    this.nextPendingQuestionId.set(null);
    this.followUpMessage.set(null);
  }
}
