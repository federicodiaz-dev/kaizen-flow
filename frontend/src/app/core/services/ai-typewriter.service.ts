import { Injectable } from '@angular/core';

interface TypewriterEntry {
  delayId: number | null;
  frameId: number | null;
  targetText: string;
  onUpdate: (value: string) => void;
  onDone?: () => void;
}

export interface TypewriterOptions {
  key: string;
  text: string;
  onUpdate: (value: string) => void;
  onDone?: () => void;
  initialDelayMs?: number;
  durationMs?: number;
  from?: string;
}

@Injectable({ providedIn: 'root' })
export class AiTypewriterService {
  private readonly animations = new Map<string, TypewriterEntry>();

  revealText({
    key,
    text,
    onUpdate,
    onDone,
    initialDelayMs = 0,
    durationMs,
    from = '',
  }: TypewriterOptions): void {
    const targetText = text ?? '';
    const seed = from && targetText.startsWith(from) ? from : '';

    this.cancel(key);
    onUpdate(seed);

    if (!targetText || seed === targetText) {
      onDone?.();
      return;
    }

    const entry: TypewriterEntry = {
      delayId: null,
      frameId: null,
      targetText,
      onUpdate,
      onDone,
    };

    this.animations.set(key, entry);

    const startIndex = seed.length;
    const totalChars = targetText.length - startIndex;
    const totalDuration = durationMs ?? this.resolveDuration(totalChars);

    const start = () => {
      const startTime = performance.now();

      const step = (now: number) => {
        const current = this.animations.get(key);
        if (!current) {
          return;
        }

        const progress = Math.min((now - startTime) / totalDuration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const visibleChars =
          startIndex + Math.max(1, Math.round(totalChars * eased));

        current.onUpdate(targetText.slice(0, visibleChars));

        if (progress >= 1) {
          this.complete(key);
          return;
        }

        current.frameId = window.requestAnimationFrame(step);
      };

      entry.frameId = window.requestAnimationFrame(step);
    };

    if (initialDelayMs > 0) {
      entry.delayId = window.setTimeout(() => {
        const current = this.animations.get(key);
        if (!current) {
          return;
        }
        current.delayId = null;
        start();
      }, initialDelayMs);
      return;
    }

    start();
  }

  isRunning(key: string): boolean {
    return this.animations.has(key);
  }

  finish(key: string): boolean {
    const entry = this.animations.get(key);
    if (!entry) {
      return false;
    }

    this.clearHandles(entry);
    entry.onUpdate(entry.targetText);
    this.animations.delete(key);
    entry.onDone?.();
    return true;
  }

  cancel(key: string): void {
    const entry = this.animations.get(key);
    if (!entry) {
      return;
    }

    this.clearHandles(entry);
    this.animations.delete(key);
  }

  cancelPrefix(prefix: string): void {
    for (const key of [...this.animations.keys()]) {
      if (key.startsWith(prefix)) {
        this.cancel(key);
      }
    }
  }

  private complete(key: string): void {
    const entry = this.animations.get(key);
    if (!entry) {
      return;
    }

    this.clearHandles(entry);
    entry.onUpdate(entry.targetText);
    this.animations.delete(key);
    entry.onDone?.();
  }

  private clearHandles(entry: TypewriterEntry): void {
    if (entry.delayId !== null) {
      window.clearTimeout(entry.delayId);
      entry.delayId = null;
    }

    if (entry.frameId !== null) {
      window.cancelAnimationFrame(entry.frameId);
      entry.frameId = null;
    }
  }

  private resolveDuration(charCount: number): number {
    return Math.min(Math.max(320 + charCount * 7, 420), 1700);
  }
}
