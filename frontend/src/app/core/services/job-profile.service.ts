import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { ModerationStatus } from '../models/auth.model';
import { JobProfile, JobProfileCreate, JobProfileUpdate } from '../models/job-profile.model';

@Injectable({ providedIn: 'root' })
export class JobProfileService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/job-profiles`;

  list(filters?: { companyId?: string; status?: ModerationStatus }): Observable<JobProfile[]> {
    let params = new HttpParams();
    if (filters?.companyId) {
      params = params.set('company_id', filters.companyId);
    }
    if (filters?.status) {
      params = params.set('status', filters.status);
    }
    return this.http.get<JobProfile[]>(this.baseUrl, { params });
  }

  approve(id: string): Observable<JobProfile> {
    return this.http.post<JobProfile>(`${this.baseUrl}/${id}/approve`, {});
  }

  reject(id: string, reason: string): Observable<JobProfile> {
    return this.http.post<JobProfile>(`${this.baseUrl}/${id}/reject`, { reason });
  }

  get(id: string): Observable<JobProfile> {
    return this.http.get<JobProfile>(`${this.baseUrl}/${id}`);
  }

  create(data: JobProfileCreate): Observable<JobProfile> {
    return this.http.post<JobProfile>(this.baseUrl, data);
  }

  update(id: string, data: JobProfileUpdate): Observable<JobProfile> {
    return this.http.patch<JobProfile>(`${this.baseUrl}/${id}`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
