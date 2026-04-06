import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';

import { ItemDetail, ItemSummary, ItemUpdatePayload } from '../../core/models/items.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { ItemDetailComponent } from './item-detail.component';
import { ItemListComponent } from './item-list.component';
import { ItemsApiService } from './items-api.service';

@Component({
  selector: 'app-items-page',
  standalone: true,
  imports: [CommonModule, ItemListComponent, ItemDetailComponent],
  templateUrl: './items-page.component.html',
  styleUrl: './items-page.component.scss'
})
export class ItemsPageComponent {
  private readonly api = inject(ItemsApiService);
  readonly accountContext = inject(AccountContextService);

  readonly items = signal<ItemSummary[]>([]);
  readonly selectedItemId = signal<string | null>(null);
  readonly selectedItem = signal<ItemDetail | null>(null);
  readonly loadingList = signal(false);
  readonly loadingDetail = signal(false);
  readonly saving = signal(false);
  readonly listError = signal<string | null>(null);
  readonly detailError = signal<string | null>(null);
  readonly searchText = signal('');
  readonly statusFilter = signal('all');

  readonly filteredItems = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    return this.items().filter((item) => {
      const matchesQuery =
        !query || item.title.toLowerCase().includes(query) || item.id.toLowerCase().includes(query);
      return matchesQuery;
    });
  });
  readonly totalItems = computed(() => this.items().length);
  readonly activeItems = computed(() => this.items().filter((item) => item.status === 'active').length);
  readonly pausedItems = computed(() => this.items().filter((item) => item.status === 'paused').length);
  readonly visibleStock = computed(
    () =>
      this.items().reduce((total, item) => total + (typeof item.available_quantity === 'number' ? item.available_quantity : 0), 0)
  );
  readonly activeAccountLabel = computed(
    () => this.accountContext.currentAccount()?.label ?? this.accountContext.selectedAccount() ?? 'Seller'
  );

  constructor() {
    effect(() => {
      const account = this.accountContext.selectedAccount();
      if (account) {
        this.loadItems(account);
      }
    }, { allowSignalWrites: true });
  }

  loadItems(account: string): void {
    this.loadingList.set(true);
    this.listError.set(null);
    this.api.list(account, this.statusFilter()).subscribe({
      next: (response) => {
        this.items.set(response.items);
        const currentId = this.selectedItemId();
        const fallbackId = response.items[0]?.id ?? null;
        const nextId = response.items.some((item) => item.id === currentId) ? currentId : fallbackId;
        this.selectedItemId.set(nextId);
        if (nextId) {
          this.loadItemDetail(nextId);
        } else {
          this.selectedItem.set(null);
        }
        this.loadingList.set(false);
      },
      error: () => {
        this.listError.set('No se pudieron cargar los productos.');
        this.loadingList.set(false);
      }
    });
  }

  loadItemDetail(itemId: string): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }

    this.loadingDetail.set(true);
    this.detailError.set(null);
    this.api.detail(account, itemId).subscribe({
      next: (response) => {
        this.selectedItem.set(response);
        this.loadingDetail.set(false);
      },
      error: () => {
        this.detailError.set('No se pudo cargar el detalle del producto.');
        this.loadingDetail.set(false);
      }
    });
  }

  onSelectItem(itemId: string): void {
    this.selectedItemId.set(itemId);
    this.loadItemDetail(itemId);
  }

  onStatusFilterChange(nextStatus: string): void {
    this.statusFilter.set(nextStatus);
    const account = this.accountContext.selectedAccount();
    if (account) {
      this.loadItems(account);
    }
  }

  onSave(payload: ItemUpdatePayload): void {
    const account = this.accountContext.selectedAccount();
    const itemId = this.selectedItemId();
    if (!account || !itemId || Object.keys(payload).length === 0) {
      return;
    }

    this.saving.set(true);
    this.api.update(account, itemId, payload).subscribe({
      next: (response) => {
        this.selectedItem.set(response);
        this.items.update((items) => items.map((item) => (item.id === response.id ? response : item)));
        this.saving.set(false);
      },
      error: () => {
        this.detailError.set('No se pudo guardar la edición del producto.');
        this.saving.set(false);
      }
    });
  }
}
