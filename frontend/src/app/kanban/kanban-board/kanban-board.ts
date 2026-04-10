import { CdkDragDrop, moveItemInArray, transferArrayItem } from '@angular/cdk/drag-drop';
import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApplicationService } from '../../core/services/application.service';
import { ApplicationWithDetails, STAGES, Stage } from '../../core/models/application.model';
import { KanbanColumn } from '../kanban-column/kanban-column';

@Component({
  selector: 'app-kanban-board',
  standalone: true,
  imports: [KanbanColumn],
  templateUrl: './kanban-board.html',
  styleUrl: './kanban-board.scss',
})
export class KanbanBoard implements OnInit {
  private readonly applicationService = inject(ApplicationService);

  readonly stages = STAGES;
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  private readonly applications = signal<ApplicationWithDetails[]>([]);

  readonly columns = computed(() => {
    const grouped: Record<Stage, ApplicationWithDetails[]> = {
      applied: [],
      interviewing: [],
      offer: [],
      archive: [],
    };
    for (const application of this.applications()) {
      grouped[application.stage].push(application);
    }
    for (const stage of this.stages) {
      grouped[stage].sort((a, b) => a.board_position - b.board_position);
    }
    return grouped;
  });

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.loading.set(true);
    this.applicationService.list().subscribe({
      next: (applications) => {
        this.applications.set(applications);
        this.loading.set(false);
        this.error.set(null);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Failed to load applications.');
      },
    });
  }

  onDrop(event: CdkDragDrop<ApplicationWithDetails[]>, targetStage: Stage): void {
    const application = event.item.data as ApplicationWithDetails;
    const grouped = this.columns();
    const sourceList = [...grouped[event.previousContainer.id as Stage]];
    const targetList =
      event.previousContainer === event.container ? sourceList : [...grouped[targetStage]];

    if (event.previousContainer === event.container) {
      moveItemInArray(sourceList, event.previousIndex, event.currentIndex);
    } else {
      transferArrayItem(sourceList, targetList, event.previousIndex, event.currentIndex);
    }

    const boardPosition = event.currentIndex;
    const previousStage = application.stage;
    const previousPosition = application.board_position;

    application.stage = targetStage;
    application.board_position = boardPosition;
    this.applications.set([...this.applications()]);

    this.applicationService
      .updateStage(application.id, { stage: targetStage, board_position: boardPosition })
      .subscribe({
        error: () => {
          application.stage = previousStage;
          application.board_position = previousPosition;
          this.error.set('Failed to move application — reverted.');
          this.reload();
        },
      });
  }
}
