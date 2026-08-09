import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { Score } from '../models/score.model';

/**
 * ATS scores for a resume — masters and tailored versions alike.
 *
 * `list` is free and is what the resume screen opens on: one request returns
 * every score the document already has, so a page never blocks on a provider to
 * render. `score` is the only call here that can be slow, and the server
 * declines to be whenever the stored answer still describes the document.
 */
@Injectable({ providedIn: 'root' })
export class ScoreService {
  private readonly http = inject(HttpClient);

  /** Every stored score for one resume. Free — never scores anything. */
  list(resumeId: string): Observable<Score[]> {
    return this.http.get<Score[]>(`${API_BASE_URL}/resumes/${resumeId}/scores`);
  }

  /**
   * Score against one job. Returns the stored answer untouched when it is still
   * current; `refresh` forces a recount for the change the fingerprint cannot
   * see, which is the job description being edited underneath it.
   */
  score(resumeId: string, jobProfileId: string, refresh = false): Observable<Score> {
    return this.http.post<Score>(`${API_BASE_URL}/resumes/${resumeId}/scores`, {
      job_profile_id: jobProfileId,
      refresh,
    });
  }
}
