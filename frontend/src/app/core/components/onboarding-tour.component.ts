import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, DestroyRef, effect, inject, signal } from '@angular/core';

import { OnboardingTourService, TourStep } from '../services/onboarding-tour.service';


interface SpotlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

@Component({
  selector: 'app-onboarding-tour',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './onboarding-tour.component.html',
  styleUrl: './onboarding-tour.component.scss',
})
export class OnboardingTourComponent {
  readonly tour = inject(OnboardingTourService);

  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);

  readonly spotlightRect = signal<SpotlightRect | null>(null);
  readonly cardStyle = signal<Record<string, string>>(this.getCenteredCardStyle());

  private currentStepId: string | null = null;
  private observedTarget: HTMLElement | null = null;
  private remeasureTimer: ReturnType<typeof setTimeout> | null = null;
  private stabilizationTimers: ReturnType<typeof setTimeout>[] = [];
  private readonly resizeObserver =
    typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(() => this.measureCurrentStep(false));
  private readonly viewportListener = () => this.measureCurrentStep(false);

  constructor() {
    window.addEventListener('resize', this.viewportListener);
    window.addEventListener('scroll', this.viewportListener, true);
    this.destroyRef.onDestroy(() => {
      window.removeEventListener('resize', this.viewportListener);
      window.removeEventListener('scroll', this.viewportListener, true);
      this.clearPendingMeasure();
      this.clearStabilizationTimers();
      this.disconnectObservedTarget();
    });

    effect(
      () => {
        const running = this.tour.running();
        const step = this.tour.currentStep();

        if (!running || !step) {
          this.currentStepId = null;
          this.clearPendingMeasure();
          this.clearStabilizationTimers();
          this.disconnectObservedTarget();
          this.spotlightRect.set(null);
          this.cardStyle.set(this.getCenteredCardStyle());
          return;
        }

        const isNewStep = this.currentStepId !== step.id;
        this.currentStepId = step.id;
        this.scheduleMeasure(step, isNewStep, 0);
      },
      { allowSignalWrites: true },
    );
  }

  private scheduleMeasure(step: TourStep, focusTarget: boolean, attempt: number): void {
    this.clearPendingMeasure();
    this.remeasureTimer = setTimeout(() => {
      const found = this.measureStep(step, focusTarget);
      if (found) {
        this.scheduleStabilization(step.id);
      }
      if (!found && attempt < 40 && this.tour.running() && this.tour.currentStep()?.id === step.id) {
        this.scheduleMeasure(step, false, attempt + 1);
      }
    }, attempt === 0 ? 30 : 140);
  }

  private measureCurrentStep(focusTarget: boolean): void {
    const step = this.tour.currentStep();
    if (!this.tour.running() || !step) {
      return;
    }
    this.measureStep(step, focusTarget);
  }

  private measureStep(step: TourStep, focusTarget: boolean): boolean {
    if (!step.selector) {
      this.disconnectObservedTarget();
      this.spotlightRect.set(null);
      this.cardStyle.set(this.getCenteredCardStyle());
      return true;
    }

    const target = this.document.querySelector(step.selector);
    if (!(target instanceof HTMLElement)) {
      this.disconnectObservedTarget();
      this.spotlightRect.set(null);
      this.cardStyle.set(this.getCenteredCardStyle());
      return false;
    }

    this.observeTarget(target);

    if (focusTarget) {
      target.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
        inline: 'nearest',
      });
    }

    const rect = target.getBoundingClientRect();
    const paddedRect: SpotlightRect = {
      top: Math.max(10, rect.top - 10),
      left: Math.max(10, rect.left - 10),
      width: Math.min(window.innerWidth - 20, rect.width + 20),
      height: Math.min(window.innerHeight - 20, rect.height + 20),
    };

    this.spotlightRect.set(paddedRect);
    this.cardStyle.set(this.buildCardStyle(step, paddedRect));
    return true;
  }

  private buildCardStyle(step: TourStep, rect: SpotlightRect): Record<string, string> {
    const margin = 14;
    const gap = 18;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const cardWidth = Math.min(380, viewportWidth - margin * 2);
    const estimatedCardHeight = this.getEstimatedCardHeight();

    if (viewportWidth < 900) {
      return {
        top: `${viewportHeight - margin}px`,
        left: '50%',
        transform: 'translate(-50%, -100%)',
        width: `${Math.min(cardWidth, viewportWidth - margin * 2)}px`,
      };
    }

    let placement = step.placement ?? 'right';
    if (placement === 'right' && rect.left + rect.width + gap + cardWidth > viewportWidth - margin) {
      placement = 'left';
    }
    if (placement === 'left' && rect.left - gap - cardWidth < margin) {
      placement = 'bottom';
    }
    if (placement === 'top' && rect.top - gap - estimatedCardHeight < margin) {
      placement = 'bottom';
    }
    if (placement === 'bottom' && rect.top + rect.height + gap + estimatedCardHeight > viewportHeight - margin) {
      placement = 'top';
    }

    const maxLeft = Math.max(margin, viewportWidth - cardWidth - margin);

    if (placement === 'center') {
      return this.getCenteredCardStyle();
    }

    if (placement === 'right') {
      const safeCenterY = this.clamp(
        rect.top + rect.height / 2,
        margin + estimatedCardHeight / 2,
        viewportHeight - margin - estimatedCardHeight / 2,
      );
      return {
        top: `${safeCenterY}px`,
        left: `${Math.min(rect.left + rect.width + gap, maxLeft)}px`,
        transform: 'translateY(-50%)',
        width: `${cardWidth}px`,
      };
    }

    if (placement === 'left') {
      const safeCenterY = this.clamp(
        rect.top + rect.height / 2,
        margin + estimatedCardHeight / 2,
        viewportHeight - margin - estimatedCardHeight / 2,
      );
      return {
        top: `${safeCenterY}px`,
        left: `${Math.max(margin, rect.left - cardWidth - gap)}px`,
        transform: 'translateY(-50%)',
        width: `${cardWidth}px`,
      };
    }

    if (placement === 'top') {
      const safeTop = this.clamp(
        rect.top - gap,
        margin + estimatedCardHeight,
        viewportHeight - margin,
      );
      return {
        top: `${safeTop}px`,
        left: `${this.clamp(rect.left + rect.width / 2 - cardWidth / 2, margin, maxLeft)}px`,
        transform: 'translateY(-100%)',
        width: `${cardWidth}px`,
      };
    }

    const safeBottomTop = this.clamp(
      rect.top + rect.height + gap,
      margin,
      viewportHeight - margin - estimatedCardHeight,
    );
    return {
      top: `${safeBottomTop}px`,
      left: `${this.clamp(rect.left + rect.width / 2 - cardWidth / 2, margin, maxLeft)}px`,
      transform: 'none',
      width: `${cardWidth}px`,
    };
  }

  private getCenteredCardStyle(): Record<string, string> {
    return {
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      width: 'min(380px, calc(100vw - 28px))',
    };
  }

  private getEstimatedCardHeight(): number {
    const card = this.document.querySelector('.tour-card');
    if (card instanceof HTMLElement) {
      return Math.max(260, Math.ceil(card.getBoundingClientRect().height));
    }
    return 320;
  }

  private clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max);
  }

  private clearPendingMeasure(): void {
    if (this.remeasureTimer) {
      clearTimeout(this.remeasureTimer);
      this.remeasureTimer = null;
    }
  }

  private scheduleStabilization(stepId: string): void {
    this.clearStabilizationTimers();
    const delays = [120, 280, 520, 880, 1280];
    this.stabilizationTimers = delays.map((delay) =>
      setTimeout(() => {
        if (this.tour.running() && this.tour.currentStep()?.id === stepId) {
          this.measureCurrentStep(false);
        }
      }, delay),
    );
  }

  private clearStabilizationTimers(): void {
    this.stabilizationTimers.forEach((timer) => clearTimeout(timer));
    this.stabilizationTimers = [];
  }

  private observeTarget(target: HTMLElement): void {
    if (!this.resizeObserver || this.observedTarget === target) {
      return;
    }

    this.disconnectObservedTarget();
    this.resizeObserver.observe(target);
    this.observedTarget = target;
  }

  private disconnectObservedTarget(): void {
    this.resizeObserver?.disconnect();
    this.observedTarget = null;
  }
}
