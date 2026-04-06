import { CommonModule, DatePipe } from '@angular/common';
import { Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { QuestionDetail } from '../../core/models/questions.models';

@Component({
  selector: 'app-question-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './question-detail.component.html',
  styleUrl: './question-detail.component.scss'
})
export class QuestionDetailComponent {
  readonly question = input<QuestionDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly submitting = input(false);

  readonly submitAnswer = output<string>();
  readonly answerText = signal('');

  constructor() {
    effect(() => {
      const currentQuestion = this.question();
      this.answerText.set(currentQuestion?.has_answer ? currentQuestion.answer?.text || '' : '');
    }, { allowSignalWrites: true });
  }

  sendAnswer(): void {
    const value = this.answerText().trim();
    if (!value) {
      return;
    }
    this.submitAnswer.emit(value);
  }
}
