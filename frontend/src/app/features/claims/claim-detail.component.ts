import { CommonModule, DatePipe } from '@angular/common';
import { Component, effect, input, output, signal } from '@angular/core';
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
  readonly receiverRole = signal('default');
  readonly receiverRoleOptions = signal<string[]>([]);
  readonly receiverRoleCatalog = ['complainant', 'respondent', 'mediator'] as const;

  constructor() {
    effect(() => {
      const currentClaim = this.claim();
      this.messageText.set('');
      const roles = currentClaim?.allowed_receiver_roles ?? [];
      this.receiverRoleOptions.set(roles);
      this.receiverRole.set(roles.length > 1 ? 'default' : roles[0] ?? 'default');
    }, { allowSignalWrites: true });
  }

  submitMessage(): void {
    const message = this.messageText().trim();
    if (!message) {
      return;
    }

    const receiverRole = this.receiverRole() === 'default' ? undefined : this.receiverRole();
    this.sendMessage.emit({ message, receiverRole });
  }

  roleLabel(role: string): string {
    if (role === 'complainant') {
      return 'Comprador / complainant';
    }
    if (role === 'respondent') {
      return 'Vendedor / respondent';
    }
    if (role === 'mediator') {
      return 'Mercado Libre / mediator';
    }
    return role;
  }
}
