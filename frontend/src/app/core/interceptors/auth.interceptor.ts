import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';


function readCookie(name: string): string | null {
  if (typeof document === 'undefined') {
    return null;
  }
  const encodedName = `${encodeURIComponent(name)}=`;
  const item = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(encodedName));
  if (!item) {
    return null;
  }
  return decodeURIComponent(item.slice(encodedName.length));
}


export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const isApiRequest = request.url.startsWith('/api/');
  const csrfToken = readCookie('kaizen_csrf');
  const needsCsrf = !['GET', 'HEAD', 'OPTIONS'].includes(request.method.toUpperCase());

  let authenticatedRequest = isApiRequest ? request.clone({ withCredentials: true }) : request;
  if (isApiRequest && needsCsrf && csrfToken) {
    authenticatedRequest = authenticatedRequest.clone({
      setHeaders: {
        'X-CSRF-Token': csrfToken,
      },
    });
  }

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
