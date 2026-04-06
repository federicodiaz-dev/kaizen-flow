import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';


export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const isApiRequest = request.url.startsWith('/api/');
  const authenticatedRequest = isApiRequest ? request.clone({ withCredentials: true }) : request;

  return next(authenticatedRequest).pipe(
    catchError((error: unknown) => {
      if (
        isApiRequest &&
        error instanceof HttpErrorResponse &&
        error.status === 401 &&
        !request.url.startsWith('/api/auth/login') &&
        !request.url.startsWith('/api/auth/register') &&
        !request.url.startsWith('/api/auth/me')
      ) {
        auth.handleUnauthorized();
      }

      return throwError(() => error);
    }),
  );
};
