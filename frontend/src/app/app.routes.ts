import { Routes } from '@angular/router';

import { AgentsPageComponent } from './features/agents/agents-page.component';
import { ClaimsPageComponent } from './features/claims/claims-page.component';
import { CopywriterPageComponent } from './features/copywriter/copywriter-page.component';
import { ItemsPageComponent } from './features/items/items-page.component';
import { QuestionsPageComponent } from './features/questions/questions-page.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'questions' },
  { path: 'agents', component: AgentsPageComponent },
  { path: 'copywriter', component: CopywriterPageComponent },
  { path: 'questions', component: QuestionsPageComponent },
  { path: 'claims', component: ClaimsPageComponent },
  { path: 'items', component: ItemsPageComponent },
  { path: '**', redirectTo: 'questions' }
];
