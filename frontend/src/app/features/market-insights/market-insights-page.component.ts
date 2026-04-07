import { CommonModule } from '@angular/common';
import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  MarketPriceStats,
  MarketResolvedCategory,
  MarketTrendReportResponse,
  MarketValidatedOpportunity,
} from '../../core/models/market-insights.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { MarketInsightsApiService } from './market-insights-api.service';

@Component({
  selector: 'app-market-insights-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './market-insights-page.component.html',
  styleUrl: './market-insights-page.component.scss',
})
export class MarketInsightsPageComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly api = inject(MarketInsightsApiService);
  private readonly typewriter = inject(AiTypewriterService);
  readonly accountContext = inject(AccountContextService);

  private readonly animationPrefix = 'market-insights';

  readonly naturalQuery = signal('');
  readonly limit = signal(5);
  readonly loading = signal(false);
  readonly result = signal<MarketTrendReportResponse | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly displayedSummary = signal('');

  readonly currentAccountKey = computed(() => this.accountContext.selectedAccount());
  readonly currentAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Cuenta'
  );
  readonly validatedCount = computed(
    () => this.result()?.validated_opportunities.length ?? 0
  );
  readonly canGenerate = computed(
    () =>
      this.naturalQuery().trim().length >= 2 &&
      !!this.currentAccountKey() &&
      !this.loading() &&
      this.accountContext.hasActiveAccess()
  );

  readonly examples = [
    'cartucheras escolares',
    'rimel',
    'mascaras de pestañas',
    'productos para hombres',
    'sabanas',
    'mochilas urbanas',
  ];

  private readonly thinkingLabels = [
    'Resolviendo categoria natural...',
    'Consultando tendencias del sitio...',
    'Validando productos concretos...',
    'Armando el reporte accionable...',
  ];
  readonly thinkingLabel = signal(this.thinkingLabels[0]);
  private thinkingInterval: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.destroyRef.onDestroy(() => {
      this.typewriter.cancelPrefix(this.animationPrefix);
      this.stopThinking();
    });

    effect(
      () => {
        const account = this.currentAccountKey();
        untracked(() => this.handleAccountChange(account));
      },
      { allowSignalWrites: true }
    );
  }

  applyExample(example: string): void {
    this.naturalQuery.set(example);
  }

  buildReport(): void {
    const account = this.currentAccountKey();
    if (!account || !this.canGenerate()) {
      return;
    }

    this.loading.set(true);
    this.errorMessage.set(null);
    this.result.set(null);
    this.displayedSummary.set('');
    this.typewriter.cancelPrefix(this.animationPrefix);
    this.startThinking();

    this.api
      .buildTrendReport(account, {
        natural_query: this.naturalQuery().trim(),
        limit: this.limit(),
      })
      .subscribe({
        next: (response) => {
          this.stopThinking();
          this.loading.set(false);
          this.result.set(response);
          this.revealSummary(response);
        },
        error: (err) => {
          this.stopThinking();
          this.loading.set(false);
          const detail = err?.error?.message ?? err?.error?.detail;
          this.errorMessage.set(
            typeof detail === 'string'
              ? detail
              : 'No se pudo generar el reporte de tendencias en este momento.'
          );
        },
      });
  }

  handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.buildReport();
    }
  }

  categoryTrail(category: MarketResolvedCategory | MarketValidatedOpportunity): string {
    if (category.category_path?.length) {
      return category.category_path.join(' / ');
    }
    return category.category_name || category.category_id || 'Categoria no resuelta';
  }

  formatPriceRange(stats: MarketPriceStats | null | undefined, currency = 'ARS'): string {
    if (!stats?.min && !stats?.max) {
      return 'Sin rango visible';
    }
    const formatter = new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    });
    if (stats.min != null && stats.max != null) {
      return `${formatter.format(stats.min)} - ${formatter.format(stats.max)}`;
    }
    const value = stats.min ?? stats.max;
    return value != null ? formatter.format(value) : 'Sin rango visible';
  }

  formatAverageSold(value: number | null | undefined): string {
    if (value == null) {
      return 'Sin dato visible';
    }
    return `${value.toFixed(1)} u.`;
  }

  formatScore(score: number): string {
    return score.toFixed(1);
  }

  resolutionLabel(resolvedBy: string): string {
    return resolvedBy === 'category_predictor' ? 'Predictor ML' : 'Fallback por busqueda';
  }

  private startThinking(): void {
    let index = 0;
    this.thinkingLabel.set(this.thinkingLabels[0]);
    this.thinkingInterval = setInterval(() => {
      index = (index + 1) % this.thinkingLabels.length;
      this.thinkingLabel.set(this.thinkingLabels[index]);
    }, 2200);
  }

  private stopThinking(): void {
    if (this.thinkingInterval) {
      clearInterval(this.thinkingInterval);
      this.thinkingInterval = null;
    }
  }

  private revealSummary(report: MarketTrendReportResponse): void {
    const text = this.summaryText(report);
    this.typewriter.revealText({
      key: `${this.animationPrefix}:summary`,
      text,
      onUpdate: (value) => this.displayedSummary.set(value),
    });
  }

  private summaryText(report: MarketTrendReportResponse): string {
    const opportunities = report.validated_opportunities.length;
    const categories = report.resolved_categories.length;
    if (opportunities === 0) {
      return `No encontré productos suficientemente específicos y validados para "${report.input_query}". Resolví ${categories} categorias, pero las señales visibles todavía no alcanzan para una recomendación fuerte.`;
    }
    const top = report.validated_opportunities[0];
    return `Encontré ${opportunities} oportunidades validadas para "${report.input_query}" en ${categories} categorias resueltas. La señal más fuerte ahora es "${top.keyword}", con evidencia concreta de búsqueda y tendencia dentro de Mercado Libre.`;
  }

  private handleAccountChange(account: string | null): void {
    this.typewriter.cancelPrefix(this.animationPrefix);
    this.stopThinking();
    this.loading.set(false);
    this.result.set(null);
    this.errorMessage.set(null);
    this.displayedSummary.set('');
    if (!account) {
      this.naturalQuery.set('');
    }
  }
}
