import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import {
  LatexEngineStatus,
  Resume,
  ResumeOutline,
  ResumeSummary,
  ResumeUploadResponse,
  SlotConfigOut,
} from '../models/resume.model';

@Injectable({ providedIn: 'root' })
export class ResumeService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_BASE_URL}/resumes`;

  /** Which engines this deployment can run, so the form offers only usable ones. */
  engineStatus(): Observable<LatexEngineStatus> {
    return this.http.get<LatexEngineStatus>(`${this.base}/engine-status`);
  }

  /**
   * The only way content enters the app.
   *
   * Slow by nature: one model call to validate and read the template, then a
   * real compile to prove the result works. Callers should show progress.
   */
  upload(title: string, file: File, engine?: string | null): Observable<ResumeUploadResponse> {
    const form = new FormData();
    form.append('title', title);
    form.append('file', file);
    if (engine) {
      form.append('latex_engine', engine);
    }
    return this.http.post<ResumeUploadResponse>(`${this.base}/upload`, form);
  }

  /**
   * The signed-in user's resumes.
   *
   * There is no `userId` parameter: the API scopes by bearer token, and a
   * client-supplied owner id was exactly the hole that let one account read
   * another's documents.
   */
  list(): Observable<ResumeSummary[]> {
    return this.http.get<ResumeSummary[]>(this.base);
  }

  get(id: string): Observable<Resume> {
    return this.http.get<Resume>(`${this.base}/${id}`);
  }

  versions(id: string): Observable<ResumeSummary[]> {
    return this.http.get<ResumeSummary[]>(`${this.base}/${id}/versions`);
  }

  outline(id: string): Observable<ResumeOutline> {
    return this.http.get<ResumeOutline>(`${this.base}/${id}/outline`);
  }

  /** The author's override on the frozen/editable boundary. `null` resets it. */
  setSlotConfig(id: string, config: SlotConfigOut | null): Observable<ResumeOutline> {
    return this.http.put<ResumeOutline>(`${this.base}/${id}/slots`, { config });
  }

  /**
   * Fetched as a blob rather than pointed at with an `<a href>` or an
   * `<iframe src>`: those requests carry no `Authorization` header, and a failed
   * compile would render as a blank tab instead of the reason it failed.
   */
  download(id: string, output: 'pdf' | 'tex'): Observable<Blob> {
    return this.http.get(`${this.base}/${id}/${output}`, { responseType: 'blob' });
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`);
  }
}
