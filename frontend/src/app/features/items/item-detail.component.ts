import { CommonModule, CurrencyPipe, DatePipe } from '@angular/common';
import { Component, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ItemDetail, ItemUpdatePayload } from '../../core/models/items.models';

type DraftItemForm = {
  title: string;
  price: number | null;
  available_quantity: number | null;
  status: 'active' | 'paused' | 'closed';
  description: string;
};

@Component({
  selector: 'app-item-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, CurrencyPipe, DatePipe],
  templateUrl: './item-detail.component.html',
  styleUrl: './item-detail.component.scss'
})
export class ItemDetailComponent {
  readonly item = input<ItemDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly saving = input(false);

  readonly save = output<ItemUpdatePayload>();

  readonly form = signal<DraftItemForm>({
    title: '',
    price: null,
    available_quantity: null,
    status: 'active',
    description: ''
  });

  constructor() {
    effect(() => {
      const current = this.item();
      this.form.set({
        title: current?.title || '',
        price: current?.price ?? null,
        available_quantity: current?.available_quantity ?? null,
        status: (current?.status as DraftItemForm['status']) || 'active',
        description: current?.description || ''
      });
    }, { allowSignalWrites: true });
  }

  updateField<K extends keyof DraftItemForm>(key: K, value: DraftItemForm[K]): void {
    this.form.update((current) => ({ ...current, [key]: value }));
  }

  parseNullableNumber(value: string | number | null): number | null {
    if (value === null || value === '') {
      return null;
    }
    return Number(value);
  }

  resolvePrimaryImage(item: ItemDetail): string | null {
    const firstPicture = item.pictures[0];
    if (firstPicture) {
      const secureUrl = firstPicture['secure_url'];
      if (typeof secureUrl === 'string' && secureUrl) {
        return secureUrl;
      }

      const url = firstPicture['url'];
      if (typeof url === 'string' && url) {
        return url;
      }
    }

    return item.thumbnail;
  }

  buildPayload(): ItemUpdatePayload {
    const currentItem = this.item();
    if (!currentItem) {
      return {};
    }

    const next = this.form();
    const payload: ItemUpdatePayload = {};

    if (next.title.trim() && next.title.trim() !== currentItem.title) {
      payload.title = next.title.trim();
    }
    if (next.price !== null && next.price !== currentItem.price) {
      payload.price = Number(next.price);
    }
    if (next.available_quantity !== null && next.available_quantity !== currentItem.available_quantity) {
      payload.available_quantity = Number(next.available_quantity);
    }
    if (next.status && next.status !== currentItem.status) {
      payload.status = next.status;
    }
    
    // Description check
    if (next.description !== (currentItem.description || '')) {
      payload.description = next.description;
    }

    return payload;
  }

  hasPendingChanges(): boolean {
    return Object.keys(this.buildPayload()).length > 0;
  }

  submit(): void {
    this.save.emit(this.buildPayload());
  }
}
