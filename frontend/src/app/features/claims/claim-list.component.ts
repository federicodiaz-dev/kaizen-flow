import { CommonModule, DatePipe } from '@angular/common';
import { Component, ElementRef, input, output, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ClaimSummary } from '../../core/models/claims.models';

export type ClaimStatusFilter = 'all' | 'opened' | 'closed';
export type ClaimStageFilter = 'all' | 'claim' | 'mediation' | 'dispute';
export type ClaimActionFilter = 'all' | 'requires_action';

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
  readonly statusFilter = input<ClaimStatusFilter>('all');
  readonly stageFilter = input<ClaimStageFilter>('all');
  readonly actionFilter = input<ClaimActionFilter>('all');
  readonly resultCount = input(0);
  readonly totalCount = input(0);
  readonly activeFilterCount = input(0);

  readonly searchTextChange = output<string>();
  readonly statusFilterChange = output<ClaimStatusFilter>();
  readonly stageFilterChange = output<ClaimStageFilter>();
  readonly actionFilterChange = output<ClaimActionFilter>();
  readonly resetFilters = output<void>();
  readonly refresh = output<void>();
  readonly selectClaim = output<number>();

  private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  focusSearch(): void {
    const input = this.searchInput()?.nativeElement;
    if (!input) {
      return;
    }

    input.focus();
    input.select();
  }

  translateType(val: string | null | undefined): string {
    if (!val) return 'Desconocido';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = {
      mediations: 'Mediacion con ML',
      claims: 'Reclamo de Comprador',
      disputes: 'Disputa',
      return: 'Devolucion',
      cancel: 'Cancelacion'
    };
    return map[key] || val;
  }

  translateStage(val: string | null | undefined): string {
    if (!val) return 'N/D';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = {
      dispute: 'En Disputa',
      mediation: 'En Mediacion',
      claim: 'En Reclamo'
    };
    return map[key] || val;
  }

  translateStatus(val: string | null | undefined): string {
    if (!val) return 'N/D';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = { opened: 'Abierto', closed: 'Cerrado', pending: 'Pendiente' };
    return map[key] || val;
  }

  isMLClaim(val: string | null | undefined): boolean {
    if (!val) return false;
    const key = val.toLowerCase().trim();
    return key === 'mediations' || key === 'disputes';
  }
}
