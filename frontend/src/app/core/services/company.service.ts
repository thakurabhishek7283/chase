import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { Company, CompanyCreate, CompanyUpdate, CompanyWithTechnologies } from '../models/company.model';
import { Technology, TechnologyAttach } from '../models/technology.model';

@Injectable({ providedIn: 'root' })
export class CompanyService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/companies`;

  list(): Observable<Company[]> {
    return this.http.get<Company[]>(this.baseUrl);
  }

  get(id: string): Observable<CompanyWithTechnologies> {
    return this.http.get<CompanyWithTechnologies>(`${this.baseUrl}/${id}`);
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

  attachTechnology(companyId: string, data: TechnologyAttach): Observable<Technology> {
    return this.http.post<Technology>(`${this.baseUrl}/${companyId}/technologies`, data);
  }

  detachTechnology(companyId: string, technologyId: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${companyId}/technologies/${technologyId}`);
  }
}
