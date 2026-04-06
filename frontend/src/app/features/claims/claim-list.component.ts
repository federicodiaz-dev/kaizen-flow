import { CommonModule, DatePipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ClaimSummary } from '../../core/models/claims.models';

@Component({
  selector: 'app-claim-list',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './claim-list.component.html',
  styleUrl: './claim-list.component.scss'
})
export class ClaimListComponent {
  readonly claims = input<ClaimSummary[]>([]);
  readonly selectedId = input<number | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly searchText = input('');
  readonly statusFilter = input('all');

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<string>();
  readonly refresh = output<void>();
  readonly selectClaim = output<number>();
}
