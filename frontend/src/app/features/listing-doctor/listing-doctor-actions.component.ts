import { CommonModule } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { ListingDoctorAction } from '../../core/models/listing-doctor.models';

@Component({
  selector: 'app-listing-doctor-actions',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './listing-doctor-actions.component.html',
  styleUrl: './listing-doctor-actions.component.scss',
})
export class ListingDoctorActionsComponent {
  readonly actions = input<ListingDoctorAction[]>([]);

  readonly highImpact = computed(() =>
    this.actions().filter((action) => action.priority === 'high').slice(0, 4)
  );

  readonly mediumImpact = computed(() =>
    this.actions()
      .filter((action) => action.priority !== 'high')
      .filter((action) => action.impact !== 'low')
      .slice(0, 4)
  );

  readonly lowEffort = computed(() =>
    this.actions().filter((action) => action.effort === 'low').slice(0, 4)
  );
}
