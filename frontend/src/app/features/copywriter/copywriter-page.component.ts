import { CommonModule } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { CopywriterApiService, CopywriterGenerateResponse } from './copywriter-api.service';

@Component({
  selector: 'app-copywriter-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './copywriter-page.component.html',
  styleUrl: './copywriter-page.component.scss',
})
export class CopywriterPageComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly api = inject(CopywriterApiService);
  private readonly typewriter = inject(AiTypewriterService);
  private readonly animationPrefix = 'copywriter-result';

  /* ── Form fields ── */
  readonly product = signal('');
  readonly brand = signal('');
  readonly country = signal('Argentina');
  readonly confirmedData = signal('');
  readonly commercialObjective = signal('Mercado Libre');

  /* ── State ── */
  readonly loading = signal(false);
  readonly result = signal<CopywriterGenerateResponse | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly copiedIndex = signal<number | null>(null);
  readonly copiedDesc = signal(false);
  readonly displayedTitles = signal<string[]>([]);
  readonly displayedDescription = signal('');

  /* ── Thinking labels ── */
  private readonly thinkingLabels = [
    'Investigando palabras clave...',
    'Analizando competencia...',
    'Generando títulos SEO...',
    'Redactando descripción...',
  ];
  readonly thinkingLabel = signal(this.thinkingLabels[0]);
  private thinkingInterval: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => this.typewriter.cancelPrefix(this.animationPrefix));
  }

  get canGenerate(): boolean {
    return this.product().trim().length > 0 && !this.loading();
  }

  generate(): void {
    if (!this.canGenerate) return;

    this.loading.set(true);
    this.errorMessage.set(null);
    this.result.set(null);
    this.displayedTitles.set([]);
    this.displayedDescription.set('');
    this.typewriter.cancelPrefix(this.animationPrefix);
    this.startThinking();

    this.api
      .generate({
        product: this.product().trim(),
        brand: this.brand().trim() || null,
        country: this.country().trim() || 'Argentina',
        confirmed_data: this.confirmedData().trim() || null,
        commercial_objective: this.commercialObjective().trim() || null,
      })
      .subscribe({
        next: (res) => {
          this.stopThinking();
          this.loading.set(false);
          this.result.set(res);
          this.revealResult(res);
        },
        error: (err) => {
          this.stopThinking();
          this.loading.set(false);
          const detail = err?.error?.detail;
          this.errorMessage.set(
            typeof detail === 'string' ? detail : 'No se pudo generar. Intentá de nuevo.'
          );
        },
      });
  }

  copyTitle(title: string, index: number): void {
    navigator.clipboard.writeText(title).then(() => {
      this.copiedIndex.set(index);
      setTimeout(() => this.copiedIndex.set(null), 1500);
    });
  }

  copyDescription(): void {
    const desc = this.result()?.description;
    if (!desc) return;
    navigator.clipboard.writeText(desc).then(() => {
      this.copiedDesc.set(true);
      setTimeout(() => this.copiedDesc.set(false), 1500);
    });
  }

  handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.generate();
    }
  }

  private startThinking(): void {
    let idx = 0;
    this.thinkingLabel.set(this.thinkingLabels[0]);
    this.thinkingInterval = setInterval(() => {
      idx = (idx + 1) % this.thinkingLabels.length;
      this.thinkingLabel.set(this.thinkingLabels[idx]);
    }, 2400);
  }

  private stopThinking(): void {
    if (this.thinkingInterval) {
      clearInterval(this.thinkingInterval);
      this.thinkingInterval = null;
    }
  }

  private revealResult(result: CopywriterGenerateResponse): void {
    this.typewriter.cancelPrefix(this.animationPrefix);
    this.displayedTitles.set(result.titles.map(() => ''));
    this.displayedDescription.set('');

    result.titles.forEach((title, index) => {
      this.typewriter.revealText({
        key: `${this.animationPrefix}:title:${index}`,
        text: title,
        initialDelayMs: index * 70,
        onUpdate: (value) => {
          this.displayedTitles.update((current) => {
            const next = [...current];
            next[index] = value;
            return next;
          });
        },
      });
    });

    this.typewriter.revealText({
      key: `${this.animationPrefix}:description`,
      text: result.description,
      initialDelayMs: 160,
      onUpdate: (value) => this.displayedDescription.set(value),
    });
  }
}
