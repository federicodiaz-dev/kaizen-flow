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

  translateType(val: string | null | undefined): string {
    if (!val) return 'Desconocido';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = { mediations: 'Mediación con ML', claims: 'Reclamo de Comprador', disputes: 'Disputa', return: 'Devolución', cancel: 'Cancelación' };
    return map[key] || val;
  }

  translateStage(val: string | null | undefined): string {
    if (!val) return 'N/D';
    const key = val.toLowerCase().trim();
    const map: Record<string, string> = { dispute: 'En Disputa', mediation: 'En Mediación', claim: 'En Reclamo' };
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
