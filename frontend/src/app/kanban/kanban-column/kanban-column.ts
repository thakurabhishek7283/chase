import { CdkDragDrop, DragDropModule } from '@angular/cdk/drag-drop';
import { Component, input, output } from '@angular/core';

import { ApplicationWithDetails, Stage, STAGE_LABELS } from '../../core/models/application.model';
import { KanbanCard } from '../kanban-card/kanban-card';

@Component({
  selector: 'app-kanban-column',
  standalone: true,
  imports: [DragDropModule, KanbanCard],
  templateUrl: './kanban-column.html',
  styleUrl: './kanban-column.scss',
})
export class KanbanColumn {
  stage = input.required<Stage>();
  applications = input.required<ApplicationWithDetails[]>();
  connectedStageIds = input.required<string[]>();

  dropped = output<{ event: CdkDragDrop<ApplicationWithDetails[]>; targetStage: Stage }>();

  readonly stageLabels = STAGE_LABELS;

  onDrop(event: CdkDragDrop<ApplicationWithDetails[]>): void {
    this.dropped.emit({ event, targetStage: this.stage() });
  }
}
