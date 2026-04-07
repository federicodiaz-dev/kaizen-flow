import { CommonModule, CurrencyPipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { ListingDoctorCompetitorSnapshot } from '../../core/models/listing-doctor.models';

@Component({
  selector: 'app-listing-doctor-competitors',
  standalone: true,
  imports: [CommonModule, CurrencyPipe],
  templateUrl: './listing-doctor-competitors.component.html',
  styleUrl: './listing-doctor-competitors.component.scss',
})
export class ListingDoctorCompetitorsComponent {
  readonly competitors = input<ListingDoctorCompetitorSnapshot[]>([]);
}
