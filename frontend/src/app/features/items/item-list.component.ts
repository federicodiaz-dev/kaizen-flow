import { CommonModule, CurrencyPipe, DatePipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ItemSummary } from '../../core/models/items.models';

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
  readonly statusFilter = input('all');

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<string>();
  readonly refresh = output<void>();
  readonly selectItem = output<string>();
}
