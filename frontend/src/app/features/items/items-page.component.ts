import { CommonModule } from '@angular/common';
import { Component, HostListener, computed, effect, inject, signal, untracked, viewChild } from '@angular/core';

import { ItemDetail, ItemSummary, ItemUpdatePayload } from '../../core/models/items.models';
import { AccountContextService } from '../../core/services/account-context.service';
import { WorkspaceStateService } from '../../core/services/workspace-state.service';
import { isEditableTarget } from '../../core/utils/keyboard.utils';
import { ItemDetailComponent } from './item-detail.component';
import { ItemListComponent, ItemSortOrder, ItemStatusFilter } from './item-list.component';
import { ItemsApiService } from './items-api.service';

type ItemsUiState = {
  searchText: string;
  statusFilter: ItemStatusFilter;
  sortOrder: ItemSortOrder;
  selectedItemId: string | null;
};

@Component({
  selector: 'app-items-page',
  standalone: true,
  imports: [CommonModule, ItemListComponent, ItemDetailComponent],
  templateUrl: './items-page.component.html',
  styleUrl: './items-page.component.scss'
})
export class ItemsPageComponent {
  private readonly api = inject(ItemsApiService);
  private readonly workspaceState = inject(WorkspaceStateService);
  readonly accountContext = inject(AccountContextService);
  private readonly listComponent = viewChild(ItemListComponent);
  private readonly storageKey = 'items-workspace';

  readonly items = signal<ItemSummary[]>([]);
  readonly selectedItemId = signal<string | null>(null);
  readonly selectedItem = signal<ItemDetail | null>(null);
  readonly loadingList = signal(false);
  readonly loadingDetail = signal(false);
  readonly saving = signal(false);
  readonly listError = signal<string | null>(null);
  readonly detailError = signal<string | null>(null);
  readonly searchText = signal('');
  readonly statusFilter = signal<ItemStatusFilter>('all');
  readonly sortOrder = signal<ItemSortOrder>('recent');

  readonly filteredItems = computed(() => {
    const query = this.searchText().trim().toLowerCase();
    const items = [...this.items()].filter((item) => {
      return !query || item.title.toLowerCase().includes(query) || item.id.toLowerCase().includes(query);
    });

    items.sort((left, right) => {
      if (this.sortOrder() === 'sold') {
        return (right.sold_quantity ?? 0) - (left.sold_quantity ?? 0);
      }
      if (this.sortOrder() === 'stock') {
        return (right.available_quantity ?? 0) - (left.available_quantity ?? 0);
      }
      return this.resolveDateValue(right.last_updated) - this.resolveDateValue(left.last_updated);
    });

    return items;
  });
  readonly totalItems = computed(() => this.items().length);
  readonly filteredCount = computed(() => this.filteredItems().length);
  readonly activeItems = computed(() => this.items().filter((item) => item.status === 'active').length);
  readonly pausedItems = computed(() => this.items().filter((item) => item.status === 'paused').length);
  readonly visibleStock = computed(
    () =>
      this.items().reduce((total, item) => total + (typeof item.available_quantity === 'number' ? item.available_quantity : 0), 0)
  );
  readonly activeFilterCount = computed(() => {
    let total = 0;
    if (this.searchText().trim()) total += 1;
    if (this.statusFilter() !== 'all') total += 1;
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
          this.loadItems(account.key);
        });
      }
    }, { allowSignalWrites: true });

    effect(() => {
      const account = this.accountContext.selectedAccount();
      if (!account) {
        return;
      }

      this.workspaceState.saveUiState<ItemsUiState>(this.storageKey, account, {
        searchText: this.searchText(),
        statusFilter: this.statusFilter(),
        sortOrder: this.sortOrder(),
        selectedItemId: this.selectedItemId(),
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

  closeSelectedItem(): void {
    this.selectedItemId.set(null);
    this.selectedItem.set(null);
  }

  onStatusFilterChange(nextStatus: ItemStatusFilter): void {
    this.statusFilter.set(nextStatus);
    const account = this.accountContext.selectedAccount();
    if (account) {
      this.loadItems(account);
    }
  }

  onSortOrderChange(sortOrder: ItemSortOrder): void {
    this.sortOrder.set(sortOrder);
  }

  resetFilters(): void {
    this.searchText.set('');
    if (this.statusFilter() !== 'all') {
      this.onStatusFilterChange('all');
    }
    this.sortOrder.set('recent');
  }

  refreshItems(): void {
    const account = this.accountContext.selectedAccount();
    if (!account) {
      return;
    }
    this.loadItems(account);
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
        this.detailError.set('No se pudo guardar la edicion del producto.');
        this.saving.set(false);
      }
    });
  }

  private restoreUiState(account: string): void {
    const state = this.workspaceState.loadUiState<ItemsUiState>(this.storageKey, account, {
      searchText: '',
      statusFilter: 'all',
      sortOrder: 'recent',
      selectedItemId: null,
    });

    this.searchText.set(state.searchText);
    this.statusFilter.set(state.statusFilter);
    this.sortOrder.set(state.sortOrder);
    this.selectedItemId.set(state.selectedItemId);
  }

  private resolveDateValue(value: string | null): number {
    return value ? new Date(value).getTime() : 0;
  }

  private moveSelection(step: 1 | -1): void {
    const visibleItems = this.filteredItems();
    if (visibleItems.length === 0) {
      return;
    }

    const currentId = this.selectedItemId();
    const currentIndex = visibleItems.findIndex((item) => item.id === currentId);
    const nextIndex =
      currentIndex === -1
        ? step === 1
          ? 0
          : visibleItems.length - 1
        : Math.max(0, Math.min(visibleItems.length - 1, currentIndex + step));
    const nextItem = visibleItems[nextIndex];

    if (nextItem && nextItem.id !== currentId) {
      this.onSelectItem(nextItem.id);
    }
  }
}
