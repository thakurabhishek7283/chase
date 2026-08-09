import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { JobMatch, ReindexSummary } from '../models/matching.model';

/** Semantic job matching. Nothing to do with resumes — it reads career goals. */
@Injectable({ providedIn: 'root' })
export class MatchingService {
  private readonly http = inject(HttpClient);

  reindex(): Observable<ReindexSummary> {
    return this.http.post<ReindexSummary>(`${API_BASE_URL}/matching/reindex`, {});
  }

  jobMatches(userId: string, limit = 10): Observable<JobMatch[]> {
    const params = new HttpParams().set('limit', String(limit));
    return this.http.get<JobMatch[]>(`${API_BASE_URL}/users/${userId}/job-matches`, { params });
  }
}
