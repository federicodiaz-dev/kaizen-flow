import { CommonModule, DatePipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { QuestionFilter, QuestionSummary } from '../../core/models/questions.models';

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

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<QuestionFilter>();
  readonly refresh = output<void>();
  readonly selectQuestion = output<number>();
}
