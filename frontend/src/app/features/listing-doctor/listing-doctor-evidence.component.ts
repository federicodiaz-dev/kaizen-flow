import { CommonModule } from '@angular/common';
import { Component, input, signal } from '@angular/core';

import { ListingDoctorEvidence } from '../../core/models/listing-doctor.models';

@Component({
  selector: 'app-listing-doctor-evidence',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './listing-doctor-evidence.component.html',
  styleUrl: './listing-doctor-evidence.component.scss',
})
export class ListingDoctorEvidenceComponent {
  readonly evidence = input<ListingDoctorEvidence | null>(null);
  readonly activeTab = signal<'facts' | 'proxies' | 'uncertainties'>('facts');
}
