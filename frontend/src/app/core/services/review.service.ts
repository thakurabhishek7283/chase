import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { FinalizeResponse, Patch, Review, ReviewSummary } from '../models/review.model';

/**
 * The reviewed-tailoring flow.
 *
 * Only three of these cost anything: `create`, `sendBack`, and nothing else.
 * Deciding a patch and rendering a preview are deterministic and free, which is
 * what makes it reasonable for the screen to re-render after every click.
 */
@Injectable({ providedIn: 'root' })
export class ReviewService {
  private readonly http = inject(HttpClient);
  private readonly base = `${API_BASE_URL}/reviews`;

  /** One model call: the score and every proposed change at once. */
  create(resumeId: string, jobProfileId: string): Observable<Review> {
    return this.http.post<Review>(`${API_BASE_URL}/resumes/${resumeId}/reviews`, {
      job_profile_id: jobProfileId,
    });
  }

  listFor(resumeId: string): Observable<ReviewSummary[]> {
    return this.http.get<ReviewSummary[]>(`${API_BASE_URL}/resumes/${resumeId}/reviews`);
  }

  get(reviewId: string): Observable<Review> {
    return this.http.get<Review>(`${this.base}/${reviewId}`);
  }

  decide(reviewId: string, patchId: string, action: 'accept' | 'reject'): Observable<Patch> {
    return this.http.patch<Patch>(`${this.base}/${reviewId}/patches/${patchId}`, { action });
  }

  /** The only per-patch model call: revise this one proposal to a brief. */
  sendBack(reviewId: string, patchId: string, feedback: string): Observable<Patch> {
    return this.http.post<Patch>(`${this.base}/${reviewId}/patches/${patchId}/feedback`, {
      feedback,
    });
  }

  /** Discard revisions and restore what the review first proposed. Free. */
  revert(reviewId: string, patchId: string): Observable<Patch> {
    return this.http.post<Patch>(`${this.base}/${reviewId}/patches/${patchId}/revert`, {});
  }

  /**
   * Render without keeping anything. Refused by the server with a 409 while any
   * patch is still pending — the UI disables the button, but the rule lives
   * there, not here.
   */
  preview(reviewId: string, output: 'pdf' | 'tex'): Observable<Blob> {
    const params = new HttpParams().set('output', output);
    return this.http.get(`${this.base}/${reviewId}/preview`, {
      params,
      responseType: 'blob',
    });
  }

  finalize(reviewId: string, versionLabel?: string | null): Observable<FinalizeResponse> {
    return this.http.post<FinalizeResponse>(`${this.base}/${reviewId}/finalize`, {
      version_label: versionLabel || null,
    });
  }

  delete(reviewId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${reviewId}`);
  }
}
