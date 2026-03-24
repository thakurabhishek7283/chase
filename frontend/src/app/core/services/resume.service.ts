import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { Resume, ResumeCreate, ResumeUpdate } from '../models/resume.model';

@Injectable({ providedIn: 'root' })
export class ResumeService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/resumes`;

  list(userId?: string, masterOnly = false): Observable<Resume[]> {
    let params = new HttpParams();
    if (userId) {
      params = params.set('user_id', userId);
    }
    if (masterOnly) {
      params = params.set('master_only', 'true');
    }
    return this.http.get<Resume[]>(this.baseUrl, { params });
  }

  get(id: string): Observable<Resume> {
    return this.http.get<Resume>(`${this.baseUrl}/${id}`);
  }

  versions(id: string): Observable<Resume[]> {
    return this.http.get<Resume[]>(`${this.baseUrl}/${id}/versions`);
  }

  create(data: ResumeCreate): Observable<Resume> {
    return this.http.post<Resume>(this.baseUrl, data);
  }

  update(id: string, data: ResumeUpdate): Observable<Resume> {
    return this.http.patch<Resume>(`${this.baseUrl}/${id}`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
