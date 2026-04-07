import { CommonModule, CurrencyPipe } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ItemSummary } from '../../core/models/items.models';

@Component({
  selector: 'app-listing-doctor-form',
  standalone: true,
  imports: [CommonModule, FormsModule, CurrencyPipe],
  templateUrl: './listing-doctor-form.component.html',
  styleUrl: './listing-doctor-form.component.scss',
})
export class ListingDoctorFormComponent {
  readonly itemId = input('');
  readonly includeCopywriter = input(true);
  readonly loading = input(false);
  readonly selectedItem = input<ItemSummary | null>(null);
  readonly pickerOpen = input(false);
  readonly recentItems = input<ItemSummary[]>([]);
  readonly recentItemsLoading = input(false);
  readonly recentItemsError = input<string | null>(null);
  readonly recentItemsQuery = input('');
  readonly accountLabel = input('Cuenta activa');

  readonly itemIdChange = output<string>();
  readonly includeCopywriterChange = output<boolean>();
  readonly analyze = output<void>();
  readonly openPicker = output<void>();
  readonly closePicker = output<void>();
  readonly refreshRecentItems = output<void>();
  readonly selectRecentItem = output<ItemSummary>();
  readonly recentItemsQueryChange = output<string>();

  readonly filteredItems = computed(() => {
    const query = this.recentItemsQuery().trim().toLowerCase();
    if (!query) {
      return this.recentItems();
    }
    return this.recentItems().filter(
      (item) =>
        item.title.toLowerCase().includes(query) || item.id.toLowerCase().includes(query)
    );
  });

  readonly canAnalyze = computed(() => this.itemId().trim().length > 0 && !this.loading());
}
