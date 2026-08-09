import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { CompanyService } from '../../core/services/company.service';
import { Company } from '../../core/models/company.model';

@Component({
  selector: 'app-company-list',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './company-list.html',
  styleUrl: './company-list.scss',
})
export class CompanyList implements OnInit {
  private readonly companyService = inject(CompanyService);
  private readonly auth = inject(AuthService);

  readonly companies = signal<Company[]>([]);
  readonly loading = signal(true);
  /** Deleting a public row is admin-only; editing one is not. */
  readonly isAdmin = this.auth.isAdmin;
  readonly isModerator = this.auth.isModerator;

  /**
   * Mirrors the server's `can_edit`: moderators and admins always,
   * contributors only while their own submission is still pending. Purely
   * cosmetic — the API enforces the same rule and would answer 403 regardless.
   */
  canEdit(company: Company): boolean {
    if (this.isModerator()) return true;
    return company.status === 'pending' && company.created_by === this.auth.currentUser()?.id;
  }

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.companyService.list().subscribe((companies) => {
      this.companies.set(companies);
      this.loading.set(false);
    });
  }

  remove(id: string): void {
    this.companyService.delete(id).subscribe(() => this.reload());
  }
}
