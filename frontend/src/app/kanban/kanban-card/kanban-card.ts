import { Component, input } from '@angular/core';

import { ApplicationWithDetails } from '../../core/models/application.model';

@Component({
  selector: 'app-kanban-card',
  standalone: true,
  templateUrl: './kanban-card.html',
  styleUrl: './kanban-card.scss',
})
export class KanbanCard {
  application = input.required<ApplicationWithDetails>();
}
