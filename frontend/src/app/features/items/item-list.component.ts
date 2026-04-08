import { CommonModule, CurrencyPipe, DatePipe } from '@angular/common';
import { Component, ElementRef, input, output, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ItemSummary } from '../../core/models/items.models';

export type ItemStatusFilter = 'all' | 'active' | 'paused' | 'closed';
export type ItemSortOrder = 'recent' | 'sold' | 'stock';

@Component({
  selector: 'app-item-list',
  standalone: true,
  imports: [CommonModule, FormsModule, CurrencyPipe, DatePipe],
  templateUrl: './item-list.component.html',
  styleUrl: './item-list.component.scss'
})
export class ItemListComponent {
  readonly items = input<ItemSummary[]>([]);
  readonly selectedId = input<string | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly searchText = input('');
  readonly statusFilter = input<ItemStatusFilter>('all');
  readonly sortOrder = input<ItemSortOrder>('recent');
  readonly resultCount = input(0);
  readonly totalCount = input(0);
  readonly activeFilterCount = input(0);

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<ItemStatusFilter>();
  readonly sortOrderChange = output<ItemSortOrder>();
  readonly resetFilters = output<void>();
  readonly refresh = output<void>();
  readonly selectItem = output<string>();

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
