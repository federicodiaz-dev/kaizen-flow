import { CommonModule, CurrencyPipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { ListingDoctorResult } from '../../core/models/listing-doctor.models';

@Component({
  selector: 'app-listing-doctor-scoreboard',
  standalone: true,
  imports: [CommonModule, CurrencyPipe],
  templateUrl: './listing-doctor-scoreboard.component.html',
  styleUrl: './listing-doctor-scoreboard.component.scss',
})
export class ListingDoctorScoreboardComponent {
  readonly result = input<ListingDoctorResult | null>(null);
  readonly executiveSummary = input('');
  readonly positioningStrategy = input('');

  readonly scoreCards = [
    { key: 'title', label: 'Titulo' },
    { key: 'price', label: 'Precio' },
    { key: 'attributes', label: 'Atributos' },
    { key: 'description', label: 'Descripcion' },
    { key: 'competitiveness', label: 'Competitividad' },
    { key: 'opportunity', label: 'Oportunidad' },
  ] as const;
}
