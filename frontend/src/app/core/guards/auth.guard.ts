import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';

import { AuthService } from '../services/auth.service';


export const authGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ensureInitialized();
  return auth.isAuthenticated() ? true : router.createUrlTree(['/login']);
};


export const guestGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.ensureInitialized();
  return auth.isAuthenticated() ? router.createUrlTree(['/questions']) : true;
};
