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

import { ItemSummary } from '../../core/models/items.models';
import {
  ListingDoctorJobAccepted,
  ListingDoctorJobRequest,
  ListingDoctorJobStatus,
  ListingDoctorResult,
} from '../../core/models/listing-doctor.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { AiTypewriterService } from '../../core/services/ai-typewriter.service';
import { ItemsApiService } from '../items/items-api.service';
import { ListingDoctorActionsComponent } from './listing-doctor-actions.component';
import { ListingDoctorApiService } from './listing-doctor-api.service';
import { ListingDoctorCompetitorsComponent } from './listing-doctor-competitors.component';
import { ListingDoctorEvidenceComponent } from './listing-doctor-evidence.component';
import { ListingDoctorFormComponent } from './listing-doctor-form.component';
import { ListingDoctorProgressComponent } from './listing-doctor-progress.component';
import { ListingDoctorScoreboardComponent } from './listing-doctor-scoreboard.component';
import { ListingDoctorTraceComponent } from './listing-doctor-trace.component';

@Component({
  selector: 'app-listing-doctor-page',
  standalone: true,
  imports: [
    CommonModule,
    ListingDoctorFormComponent,
    ListingDoctorProgressComponent,
    ListingDoctorScoreboardComponent,
    ListingDoctorCompetitorsComponent,
    ListingDoctorActionsComponent,
    ListingDoctorEvidenceComponent,
    ListingDoctorTraceComponent,
  ],
  templateUrl: './listing-doctor-page.component.html',
  styleUrl: './listing-doctor-page.component.scss',
})
export class ListingDoctorPageComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly api = inject(ListingDoctorApiService);
  private readonly itemsApi = inject(ItemsApiService);
  private readonly typewriter = inject(AiTypewriterService);
  readonly accountContext = inject(AccountContextService);

  private readonly animationPrefix = 'listing-doctor';
  private readonly pollIntervalMs = 1500;
  private pollingHandle: ReturnType<typeof setTimeout> | null = null;

  readonly itemId = signal('');
  readonly includeCopywriter = signal(true);
  readonly pickerOpen = signal(false);
  readonly recentItems = signal<ItemSummary[]>([]);
  readonly recentItemsLoading = signal(false);
  readonly recentItemsError = signal<string | null>(null);
  readonly recentItemsQuery = signal('');
  readonly recentItemsLoadedFor = signal<string | null>(null);
  readonly job = signal<ListingDoctorJobStatus | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly copiedKey = signal<string | null>(null);
  readonly displayedExecutiveSummary = signal('');
  readonly displayedPositioning = signal('');
  readonly displayedDescription = signal('');
  readonly displayedTitleSuggestions = signal<string[]>([]);
  readonly lastRevealKey = signal<string | null>(null);

  readonly result = computed(() => this.job()?.result ?? null);
  readonly loading = computed(() => {
    const status = this.job()?.status;
    return status === 'queued' || status === 'running';
  });
  readonly currentAccountKey = computed(() => this.accountContext.selectedAccount());
  readonly currentAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Cuenta'
  );
  readonly selectedItem = computed(() => {
    const currentItemId = this.itemId().trim().toUpperCase();
    return this.recentItems().find((item) => item.id.toUpperCase() === currentItemId) ?? null;
  });
  readonly activeStepMessage = computed(
    () =>
      this.job()?.steps.find((step) => step.status === 'running')?.message ??
      this.job()?.steps.find((step) => step.status === 'running')?.label ??
      'Esperando ejecucion...'
  );
  readonly canAnalyze = computed(
    () =>
      this.itemId().trim().length > 0 &&
      !!this.currentAccountKey() &&
      !this.loading() &&
      this.accountContext.hasActiveAccess()
  );

  constructor() {
    this.destroyRef.onDestroy(() => {
      this.clearPolling();
      this.typewriter.cancelPrefix(this.animationPrefix);
    });

    effect(
      () => {
        const account = this.currentAccountKey();
        untracked(() => this.handleAccountChange(account));
      },
      { allowSignalWrites: true }
    );
  }

  openPicker(): void {
    this.pickerOpen.set(true);
    this.loadRecentItems();
  }

  closePicker(): void {
    this.pickerOpen.set(false);
  }

  selectRecentItem(item: ItemSummary): void {
    this.itemId.set(item.id);
    this.pickerOpen.set(false);
  }

  analyze(): void {
    const account = this.currentAccountKey();
    if (!account || !this.canAnalyze()) {
      return;
    }

    this.errorMessage.set(null);
    this.clearPolling();
    this.typewriter.cancelPrefix(this.animationPrefix);
    this.resetRevealedContent();

    const payload: ListingDoctorJobRequest = {
      item_id: this.itemId().trim().toUpperCase(),
      include_copywriter: this.includeCopywriter(),
      competitor_limit: 8,
      search_depth: 2,
    };

    this.api.createJob(account, payload).subscribe({
      next: (response) => {
        const status = this.acceptedJobToStatus(response, payload);
        this.itemId.set(status.item_id);
        this.job.set(status);
        this.persistJobId(account, status.job_id);
        this.startPolling(status.job_id);
      },
      error: (err) => {
        const detail = err?.error?.message ?? err?.error?.detail;
        this.errorMessage.set(
          typeof detail === 'string' ? detail : 'No se pudo iniciar el analisis de Listing Doctor.'
        );
      },
    });
  }

  refreshRecentItems(): void {
    this.loadRecentItems(true);
  }

  copyText(text: string, key: string): void {
    if (!text) {
      return;
    }
    navigator.clipboard.writeText(text).then(() => {
      this.copiedKey.set(key);
      setTimeout(() => this.copiedKey.set(null), 1600);
    });
  }

  private loadRecentItems(force = false): void {
    const account = this.currentAccountKey();
    if (!account) {
      return;
    }
    if (!force && this.recentItemsLoadedFor() === account && this.recentItems().length > 0) {
      return;
    }

    this.recentItemsLoading.set(true);
    this.recentItemsError.set(null);
    this.itemsApi.list(account, 'active', 100).subscribe({
      next: (response) => {
        this.recentItems.set(response.items);
        this.recentItemsLoadedFor.set(account);
        this.recentItemsLoading.set(false);
      },
      error: () => {
        this.recentItemsError.set('No se pudieron cargar las publicaciones recientes.');
        this.recentItemsLoading.set(false);
      },
    });
  }

  private startPolling(jobId: string): void {
    this.clearPolling();
    const tick = () => {
      this.api.getJob(jobId).subscribe({
        next: (job) => {
          this.job.set(job);
          this.itemId.set(job.item_id);
          const account = this.currentAccountKey();
          if (account) {
            this.persistJobId(account, job.job_id);
          }
          if (job.result) {
            this.revealResult(job.result);
          }
          if (job.status === 'failed' || job.status === 'interrupted') {
            this.errorMessage.set(job.error_message || 'El analisis no pudo completarse.');
            this.clearPolling();
            return;
          }
          if (job.status === 'completed' || job.status === 'partial') {
            this.clearPolling();
            return;
          }
          this.pollingHandle = setTimeout(tick, this.pollIntervalMs);
        },
        error: (err) => {
          const detail = err?.error?.message ?? err?.error?.detail;
          this.errorMessage.set(
            typeof detail === 'string' ? detail : 'No se pudo actualizar el progreso del analisis.'
          );
          this.clearPolling();
        },
      });
    };
    tick();
  }

  private clearPolling(): void {
    if (this.pollingHandle) {
      clearTimeout(this.pollingHandle);
      this.pollingHandle = null;
    }
  }

  private handleAccountChange(account: string | null): void {
    this.clearPolling();
    this.job.set(null);
    this.errorMessage.set(null);
    this.recentItems.set([]);
    this.recentItemsLoadedFor.set(null);
    this.recentItemsError.set(null);
    this.recentItemsQuery.set('');
    this.resetRevealedContent();

    if (!account) {
      this.itemId.set('');
      return;
    }

    const savedJobId = sessionStorage.getItem(this.storageKey(account));
    if (!savedJobId) {
      this.itemId.set('');
      return;
    }
    this.api.getJob(savedJobId).subscribe({
      next: (job) => {
        this.job.set(job);
        this.itemId.set(job.item_id);
        if (job.result) {
          this.revealResult(job.result);
        }
        if (job.status === 'queued' || job.status === 'running') {
          this.startPolling(job.job_id);
        }
      },
      error: () => {
        sessionStorage.removeItem(this.storageKey(account));
      },
    });
  }

  private acceptedJobToStatus(
    response: ListingDoctorJobAccepted,
    payload: ListingDoctorJobRequest
  ): ListingDoctorJobStatus {
    return {
      ...response,
      include_copywriter: !!payload.include_copywriter,
      competitor_limit: payload.competitor_limit ?? 8,
      search_depth: payload.search_depth ?? 2,
      error_message: null,
      warnings: [],
      result: null,
    };
  }

  private persistJobId(account: string, jobId: string): void {
    sessionStorage.setItem(this.storageKey(account), jobId);
  }

  private storageKey(account: string): string {
    return `listing-doctor:job:${account}`;
  }

  private revealResult(result: ListingDoctorResult): void {
    const revealKey = `${result.generated_at}:${result.listing.item_id}`;
    if (this.lastRevealKey() === revealKey) {
      return;
    }
    this.lastRevealKey.set(revealKey);
    this.resetRevealedContent();
    this.typewriter.cancelPrefix(this.animationPrefix);

    this.displayedTitleSuggestions.set(result.ai_suggestions.suggested_titles.map(() => ''));
    result.ai_suggestions.suggested_titles.forEach((title, index) => {
      this.typewriter.revealText({
        key: `${this.animationPrefix}:title:${index}`,
        text: title,
        initialDelayMs: index * 60,
        onUpdate: (value) => {
          this.displayedTitleSuggestions.update((current) => {
            const next = [...current];
            next[index] = value;
            return next;
          });
        },
      });
    });

    this.typewriter.revealText({
      key: `${this.animationPrefix}:summary`,
      text: result.executive_summary,
      onUpdate: (value) => this.displayedExecutiveSummary.set(value),
    });

    this.typewriter.revealText({
      key: `${this.animationPrefix}:positioning`,
      text: result.ai_suggestions.positioning_strategy || '',
      initialDelayMs: 120,
      onUpdate: (value) => this.displayedPositioning.set(value),
    });

    this.typewriter.revealText({
      key: `${this.animationPrefix}:description`,
      text: result.ai_suggestions.suggested_description || '',
      initialDelayMs: 180,
      onUpdate: (value) => this.displayedDescription.set(value),
    });
  }

  private resetRevealedContent(): void {
    this.displayedExecutiveSummary.set('');
    this.displayedPositioning.set('');
    this.displayedDescription.set('');
    this.displayedTitleSuggestions.set([]);
    this.lastRevealKey.set(null);
  }
}
