import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import {
  Application,
  ApplicationCreate,
  ApplicationStageUpdate,
  ApplicationWithDetails,
  Stage,
} from '../models/application.model';

@Injectable({ providedIn: 'root' })
export class ApplicationService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/applications`;

  list(filters?: { userId?: string; stage?: Stage; companyId?: string }): Observable<ApplicationWithDetails[]> {
    let params = new HttpParams();
    if (filters?.userId) {
      params = params.set('user_id', filters.userId);
    }
    if (filters?.stage) {
      params = params.set('stage', filters.stage);
    }
    if (filters?.companyId) {
      params = params.set('company_id', filters.companyId);
    }
    return this.http.get<ApplicationWithDetails[]>(this.baseUrl, { params });
  }

  get(id: string): Observable<ApplicationWithDetails> {
    return this.http.get<ApplicationWithDetails>(`${this.baseUrl}/${id}`);
  }

  create(data: ApplicationCreate): Observable<Application> {
    return this.http.post<Application>(this.baseUrl, data);
  }

  updateStage(id: string, data: ApplicationStageUpdate): Observable<Application> {
    return this.http.patch<Application>(`${this.baseUrl}/${id}/stage`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
