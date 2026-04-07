import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  ListingDoctorJobAccepted,
  ListingDoctorJobRequest,
  ListingDoctorJobStatus,
} from '../../core/models/listing-doctor.models';

@Injectable({ providedIn: 'root' })
export class ListingDoctorApiService {
  private readonly http = inject(HttpClient);

  createJob(account: string, payload: ListingDoctorJobRequest): Observable<ListingDoctorJobAccepted> {
    const params = new HttpParams().set('account', account);
    return this.http.post<ListingDoctorJobAccepted>('/api/listing-doctor/jobs', payload, { params });
  }

  getJob(jobId: string): Observable<ListingDoctorJobStatus> {
    return this.http.get<ListingDoctorJobStatus>(`/api/listing-doctor/jobs/${jobId}`);
  }
}
