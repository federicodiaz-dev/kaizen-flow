import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/guards/auth.guard';
import { AgentsPageComponent } from './features/agents/agents-page.component';
import { AuthPageComponent } from './features/auth/auth-page.component';
import { MercadoLibreCallbackComponent } from './features/auth/mercadolibre-callback.component';
import { ClaimsPageComponent } from './features/claims/claims-page.component';
import { CopywriterPageComponent } from './features/copywriter/copywriter-page.component';
import { ItemsPageComponent } from './features/items/items-page.component';
import { ListingDoctorPageComponent } from './features/listing-doctor/listing-doctor-page.component';
import { QuestionsPageComponent } from './features/questions/questions-page.component';

export const routes: Routes = [
  { path: 'login', component: AuthPageComponent, canActivate: [guestGuard], data: { mode: 'login' } },
  { path: 'register', component: AuthPageComponent, canActivate: [guestGuard], data: { mode: 'register' } },
  { path: 'auth/mercadolibre/callback', component: MercadoLibreCallbackComponent },
  { path: '', pathMatch: 'full', redirectTo: 'questions' },
  { path: 'agents', component: AgentsPageComponent, canActivate: [authGuard] },
  { path: 'copywriter', component: CopywriterPageComponent, canActivate: [authGuard] },
  { path: 'listing-doctor', component: ListingDoctorPageComponent, canActivate: [authGuard] },
  { path: 'questions', component: QuestionsPageComponent, canActivate: [authGuard] },
  { path: 'claims', component: ClaimsPageComponent, canActivate: [authGuard] },
  { path: 'items', component: ItemsPageComponent, canActivate: [authGuard] },
  { path: '**', redirectTo: 'questions' }
];
