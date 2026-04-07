import { CommonModule } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import {
  ListingDoctorJobState,
  ListingDoctorProgressStep,
} from '../../core/models/listing-doctor.models';

@Component({
  selector: 'app-listing-doctor-progress',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './listing-doctor-progress.component.html',
  styleUrl: './listing-doctor-progress.component.scss',
})
export class ListingDoctorProgressComponent {
  readonly steps = input<ListingDoctorProgressStep[]>([]);
  readonly jobStatus = input<ListingDoctorJobState>('queued');

  readonly runningStep = computed(
    () => this.steps().find((step) => step.status === 'running') ?? null
  );

  statusLabel(status: ListingDoctorProgressStep['status']): string {
    const labels: Record<ListingDoctorProgressStep['status'], string> = {
      pending: 'Pendiente',
      running: 'En curso',
      completed: 'Listo',
      skipped: 'Omitido',
      failed: 'Con alerta',
    };
    return labels[status];
  }
}
