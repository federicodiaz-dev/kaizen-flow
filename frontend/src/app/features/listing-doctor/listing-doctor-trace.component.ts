import { CommonModule } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { ListingDoctorTraceEntry } from '../../core/models/listing-doctor.models';

@Component({
  selector: 'app-listing-doctor-trace',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './listing-doctor-trace.component.html',
  styleUrl: './listing-doctor-trace.component.scss',
})
export class ListingDoctorTraceComponent {
  readonly trace = input<ListingDoctorTraceEntry[]>([]);
  readonly logFilePath = input<string | null>(null);

  readonly groupedTrace = computed(() => {
    const groups: Array<{ agent: string; entries: ListingDoctorTraceEntry[] }> = [];
    const byAgent = new Map<string, ListingDoctorTraceEntry[]>();

    for (const entry of this.trace()) {
      if (!byAgent.has(entry.agent)) {
        byAgent.set(entry.agent, []);
        groups.push({ agent: entry.agent, entries: byAgent.get(entry.agent)! });
      }
      byAgent.get(entry.agent)!.push(entry);
    }

    return groups;
  });

  phaseLabel(phase: ListingDoctorTraceEntry['phase']): string {
    const labels: Record<ListingDoctorTraceEntry['phase'], string> = {
      started: 'Inicio',
      completed: 'OK',
      failed: 'Error',
      info: 'Info',
    };
    return labels[phase];
  }

  agentLabel(agent: string): string {
    return agent
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  formatDetails(details: ListingDoctorTraceEntry['details']): string {
    if (details === null || details === undefined) {
      return '';
    }
    if (typeof details === 'string') {
      return details;
    }
    try {
      return JSON.stringify(details, null, 2);
    } catch {
      return String(details);
    }
  }
}
