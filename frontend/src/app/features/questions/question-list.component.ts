import { CommonModule, DatePipe } from '@angular/common';
import { Component, ElementRef, input, output, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { QuestionFilter, QuestionSummary } from '../../core/models/questions.models';

export type QuestionRespondableFilter = 'all' | 'respondable' | 'limited';
export type QuestionSortOrder = 'recent' | 'oldest' | 'pending';

@Component({
  selector: 'app-question-list',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './question-list.component.html',
  styleUrl: './question-list.component.scss'
})
export class QuestionListComponent {
  readonly questions = input<QuestionSummary[]>([]);
  readonly selectedId = input<number | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly searchText = input('');
  readonly statusFilter = input<QuestionFilter>('all');
  readonly respondableFilter = input<QuestionRespondableFilter>('all');
  readonly sortOrder = input<QuestionSortOrder>('recent');
  readonly resultCount = input(0);
  readonly totalCount = input(0);
  readonly activeFilterCount = input(0);

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<QuestionFilter>();
  readonly respondableFilterChange = output<QuestionRespondableFilter>();
  readonly sortOrderChange = output<QuestionSortOrder>();
  readonly resetFilters = output<void>();
  readonly refresh = output<void>();
  readonly selectQuestion = output<number>();

  private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  focusSearch(): void {
    const input = this.searchInput()?.nativeElement;
    if (!input) {
      return;
    }

    input.focus();
    input.select();
  }
}
