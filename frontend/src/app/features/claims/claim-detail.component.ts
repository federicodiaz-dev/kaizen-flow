import { CommonModule, DatePipe } from '@angular/common';
import { Component, effect, input, output, signal, computed } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ClaimDetail } from '../../core/models/claims.models';

@Component({
  selector: 'app-claim-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe],
  templateUrl: './claim-detail.component.html',
  styleUrl: './claim-detail.component.scss'
})
export class ClaimDetailComponent {
  readonly claim = input<ClaimDetail | null>(null);
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly sending = input(false);

  readonly sendMessage = output<{ message: string; receiverRole?: string }>();

  readonly messageText = signal('');
  readonly receiverRoleOptions = signal<string[]>([]);
  
  readonly activeChatTab = signal<'buyer' | 'ml'>('buyer');

  readonly buyerMessages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    return claim.messages
      .filter(m => m.sender_role !== 'mediator' && m.receiver_role !== 'mediator')
      .sort((a, b) => new Date(a.date_created || 0).getTime() - new Date(b.date_created || 0).getTime());
  });

  readonly mlMessages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    return claim.messages
      .filter(m => m.sender_role === 'mediator' || m.receiver_role === 'mediator')
      .sort((a, b) => new Date(a.date_created || 0).getTime() - new Date(b.date_created || 0).getTime());
  });

  readonly isMLIntervened = computed(() => {
    const claim = this.claim();
    if (!claim) return false;
    return this.isMLClaim(claim.type) || claim.stage !== 'claim';
  });

  constructor() {
    effect(() => {
      const currentClaim = this.claim();
      this.messageText.set('');
      const roles = currentClaim?.allowed_receiver_roles ?? [];
      this.receiverRoleOptions.set(roles);
      
      if (this.isMLIntervened()) {
        this.activeChatTab.set('ml');
      } else {
        this.activeChatTab.set('buyer');
      }
    }, { allowSignalWrites: true });
  }

  setTab(tab: 'buyer' | 'ml') {
    this.activeChatTab.set(tab);
    this.messageText.set(''); // Clear input on tab switch
  }

  submitMessage(): void {
    const message = this.messageText().trim();
    if (!message) {
      return;
    }

    const receiverRole = this.activeChatTab() === 'buyer' ? 'complainant' : 'mediator';
    this.sendMessage.emit({ message, receiverRole });
  }

  roleLabel(role: string | null | undefined): string {
    if (!role) return 'Desconocido';
    const r = role.toLowerCase().trim();
    if (r === 'complainant' || r === 'buyer') return 'Comprador';
    if (r === 'respondent' || r === 'seller') return 'Vendedor';
    if (r === 'mediator' || r === 'internal') return 'Mercado Libre';
    return role;
  }

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
