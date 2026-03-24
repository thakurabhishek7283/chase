import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { API_BASE_URL } from '../api-config';
import { User, UserCreate, UserUpdate } from '../models/user.model';

@Injectable({ providedIn: 'root' })
export class UserService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${API_BASE_URL}/users`;

  list(): Observable<User[]> {
    return this.http.get<User[]>(this.baseUrl);
  }

  get(id: string): Observable<User> {
    return this.http.get<User>(`${this.baseUrl}/${id}`);
  }

  create(data: UserCreate): Observable<User> {
    return this.http.post<User>(this.baseUrl, data);
  }

  update(id: string, data: UserUpdate): Observable<User> {
    return this.http.patch<User>(`${this.baseUrl}/${id}`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }
}
