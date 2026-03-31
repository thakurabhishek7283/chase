import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

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

  readonly companies = signal<Company[]>([]);
  readonly loading = signal(true);

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
