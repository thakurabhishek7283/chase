import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import {
  JobProfile,
  JobProfileCreate,
  JobProfileUpdate,
  JobProfileWithTechnologies,
} from '../models/job-profile.model';
import { JobProfileTechnologyAttach, Technology } from '../models/technology.model';

@Injectable({ providedIn: 'root' })
export class JobProfileService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/job-profiles`;

  list(companyId?: string): Observable<JobProfile[]> {
    let params = new HttpParams();
    if (companyId) {
      params = params.set('company_id', companyId);
    }
    return this.http.get<JobProfile[]>(this.baseUrl, { params });
  }

  get(id: string): Observable<JobProfileWithTechnologies> {
    return this.http.get<JobProfileWithTechnologies>(`${this.baseUrl}/${id}`);
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

  attachTechnology(jobProfileId: string, data: JobProfileTechnologyAttach): Observable<Technology> {
    return this.http.post<Technology>(`${this.baseUrl}/${jobProfileId}/technologies`, data);
  }

  detachTechnology(jobProfileId: string, technologyId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${jobProfileId}/technologies/${technologyId}`);
  }
}
