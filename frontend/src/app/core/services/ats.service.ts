import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import {
  ATSScoreRequest,
  ATSScoreResponse,
  AutofixRequest,
  AutofixResponse,
  JobMatch,
  ReindexSummary,
  ResumeParseResult,
} from '../models/ats.model';

@Injectable({ providedIn: 'root' })
export class AtsService {
  private readonly http = inject(HttpClient);

  score(data: ATSScoreRequest): Observable<ATSScoreResponse> {
    return this.http.post<ATSScoreResponse>(`${API_BASE_URL}/ats/score`, data);
  }

  autofix(data: AutofixRequest): Observable<AutofixResponse> {
    return this.http.post<AutofixResponse>(`${API_BASE_URL}/ats/autofix`, data);
  }

  parsePdf(file: File): Observable<ResumeParseResult> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<ResumeParseResult>(`${API_BASE_URL}/resumes/parse-pdf`, form);
  }

  reindex(): Observable<ReindexSummary> {
    return this.http.post<ReindexSummary>(`${API_BASE_URL}/matching/reindex`, {});
  }

  jobMatches(userId: string, limit = 10): Observable<JobMatch[]> {
    const params = new HttpParams().set('limit', String(limit));
    return this.http.get<JobMatch[]>(`${API_BASE_URL}/users/${userId}/job-matches`, { params });
  }
}
