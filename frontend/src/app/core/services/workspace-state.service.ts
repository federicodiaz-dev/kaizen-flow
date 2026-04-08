import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class WorkspaceStateService {
  private readonly uiPrefix = 'kaizen-flow:workspace-ui';
  private readonly draftPrefix = 'kaizen-flow:workspace-draft';

  loadUiState<T extends object>(workspace: string, accountKey: string, defaults: T): T {
    const stored = this.readStorage(localStorage, this.buildUiKey(workspace, accountKey));
    if (!stored || typeof stored !== 'object') {
      return defaults;
    }
    return { ...defaults, ...stored } as T;
  }

  saveUiState<T extends object>(workspace: string, accountKey: string, state: T): void {
    this.writeStorage(localStorage, this.buildUiKey(workspace, accountKey), state);
  }

  loadDraft<T>(workspace: string, accountKey: string, entityKey: string, fallback: T): T {
    const stored = this.readStorage(sessionStorage, this.buildDraftKey(workspace, accountKey, entityKey));
    return stored === null ? fallback : (stored as T);
  }

  saveDraft<T>(workspace: string, accountKey: string, entityKey: string, state: T): void {
    this.writeStorage(sessionStorage, this.buildDraftKey(workspace, accountKey, entityKey), state);
  }

  removeDraft(workspace: string, accountKey: string, entityKey: string): void {
    this.removeStorage(sessionStorage, this.buildDraftKey(workspace, accountKey, entityKey));
  }

  private buildUiKey(workspace: string, accountKey: string): string {
    return `${this.uiPrefix}:${accountKey}:${workspace}`;
  }

  private buildDraftKey(workspace: string, accountKey: string, entityKey: string): string {
    return `${this.draftPrefix}:${accountKey}:${workspace}:${entityKey}`;
  }

  private readStorage(storage: Storage, key: string): unknown | null {
    if (typeof window === 'undefined') {
      return null;
    }

    try {
      const raw = storage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  private writeStorage(storage: Storage, key: string, value: unknown): void {
    if (typeof window === 'undefined') {
      return;
    }

    try {
      storage.setItem(key, JSON.stringify(value));
    } catch {
      // Ignore storage write failures to keep the UI responsive.
    }
  }

  private removeStorage(storage: Storage, key: string): void {
    if (typeof window === 'undefined') {
      return;
    }

    try {
      storage.removeItem(key);
    } catch {
      // Ignore storage cleanup failures.
    }
  }
}
