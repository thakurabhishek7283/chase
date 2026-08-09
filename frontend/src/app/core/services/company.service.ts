import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { ModerationStatus } from '../models/auth.model';
import { Company, CompanyCreate, CompanyUpdate } from '../models/company.model';

@Injectable({ providedIn: 'root' })
export class CompanyService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/companies`;

  list(filters?: { search?: string; status?: ModerationStatus }): Observable<Company[]> {
    let params = new HttpParams();
    if (filters?.search) {
      params = params.set('q', filters.search);
    }
    if (filters?.status) {
      params = params.set('status', filters.status);
    }
    return this.http.get<Company[]>(this.baseUrl, { params });
  }

  /**
   * Resolve a typed name to the company it would collide with.
   *
   * Lets the form warn before submitting, rather than after the user has
   * filled in every field and earned a 409.
   */
  lookup(name: string): Observable<Company | null> {
    const params = new HttpParams().set('name', name);
    return this.http.get<Company | null>(`${this.baseUrl}/lookup`, { params });
  }

  approve(id: string): Observable<Company> {
    return this.http.post<Company>(`${this.baseUrl}/${id}/approve`, {});
  }

  reject(id: string, reason: string): Observable<Company> {
    return this.http.post<Company>(`${this.baseUrl}/${id}/reject`, { reason });
  }

  get(id: string): Observable<Company> {
    return this.http.get<Company>(`${this.baseUrl}/${id}`);
  }

  create(data: CompanyCreate): Observable<Company> {
    return this.http.post<Company>(this.baseUrl, data);
  }

  update(id: string, data: CompanyUpdate): Observable<Company> {
    return this.http.patch<Company>(`${this.baseUrl}/${id}`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
