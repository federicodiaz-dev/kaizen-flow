import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';

import { AccountContextService } from './account-context.service';
import { AuthService } from './auth.service';


export type TourPlacement = 'top' | 'right' | 'bottom' | 'left' | 'center';

export interface TourStep {
  id: string;
  route: string;
  selector?: string;
  placement?: TourPlacement;
  title: string;
  description: string;
}

const WELCOME_AGENT_TOUR: readonly TourStep[] = [
  {
    id: 'welcome-overview',
    route: '/questions',
    placement: 'center',
    title: 'Bienvenido a tu workspace operativo',
    description:
      'Este recorrido te muestra dónde cambiar de cuenta, cómo moverte entre módulos y en qué pantallas resolver preguntas, reclamos, catálogo y tareas con IA.',
  },
  {
    id: 'account-selector',
    route: '/questions',
    selector: '[data-tour-id="account-selector"]',
    placement: 'bottom',
    title: 'Desde aquí cambias la cuenta activa',
    description:
      'Si manejas más de una cuenta de Mercado Libre, este selector define con qué negocio trabaja todo el sistema para evitar mezclar contexto, mensajes o métricas.',
  },
  {
    id: 'plan-pill',
    route: '/questions',
    selector: '[data-tour-id="plan-pill"]',
    placement: 'bottom',
    title: 'Tu plan visible en todo momento',
    description:
      'Aquí ves qué plan tiene activa la sesión. Esto te permite validar rápido qué reglas, límites y capacidades deberían estar disponibles para esa cuenta.',
  },
  {
    id: 'questions-nav',
    route: '/questions',
    selector: '[data-tour-id="nav-questions"]',
    placement: 'bottom',
    title: 'Preguntas es tu tablero diario',
    description:
      'Este módulo concentra las consultas de compradores y suele ser el punto más rápido para entrar al ritmo operativo del día.',
  },
  {
    id: 'questions-workspace',
    route: '/questions',
    selector: '[data-tour-id="questions-workspace"]',
    placement: 'top',
    title: 'Aquí controlas el estado general de preguntas',
    description:
      'Ves volumen total, pendientes y respondidas, y desde la lista puedes priorizar qué consultas atender primero según urgencia o filtros activos.',
  },
  {
    id: 'questions-detail',
    route: '/questions',
    selector: '[data-tour-id="questions-detail-panel"]',
    placement: 'left',
    title: 'El detalle vive siempre en este panel lateral',
    description:
      'Cuando eliges una pregunta, aquí aparece el contexto del producto y la respuesta sugerida o manual para no perder foco ni salir de la pantalla.',
  },
  {
    id: 'agents-nav',
    route: '/agents',
    selector: '[data-tour-id="nav-agents"]',
    placement: 'bottom',
    title: 'El agente es tu copiloto transversal',
    description:
      'Desde aquí abres conversaciones estratégicas u operativas para pedir análisis, borradores, resúmenes y seguimiento de la cuenta usando lenguaje natural.',
  },
  {
    id: 'agents-history',
    route: '/agents',
    selector: '[data-tour-id="agents-history"]',
    placement: 'right',
    title: 'Cada hilo conserva su contexto',
    description:
      'El historial te permite retomar conversaciones previas por cuenta sin arrancar de cero ni mezclar decisiones de un negocio con otro.',
  },
  {
    id: 'agents-stage',
    route: '/agents',
    selector: '[data-tour-id="agents-stage"]',
    placement: 'top',
    title: 'Este es tu espacio principal de análisis',
    description:
      'Aquí se muestran respuestas largas, planes de acción y resultados del agente con contexto real de la cuenta que tengas activa.',
  },
  {
    id: 'agents-composer',
    route: '/agents',
    selector: '[data-tour-id="agents-composer"]',
    placement: 'top',
    title: 'Desde aquí lanzas pedidos rápidos',
    description:
      'Puedes consultar por reclamos, publicaciones, ventas o estrategia. Enter envía y Shift + Enter agrega una nueva línea para escribir prompts más largos.',
  },
  {
    id: 'claims-nav',
    route: '/claims',
    selector: '[data-tour-id="nav-claims"]',
    placement: 'bottom',
    title: 'Reclamos te ordena el frente más sensible',
    description:
      'Cuando el caso ya escaló, este acceso te lleva a la bandeja donde sigues conversaciones delicadas con comprador y mediación.',
  },
  {
    id: 'claims-workspace',
    route: '/claims',
    selector: '[data-tour-id="claims-workspace"]',
    placement: 'top',
    title: 'Aquí priorizas los casos abiertos',
    description:
      'La vista resume volumen, urgencia y acciones necesarias para que puedas detectar rápido qué reclamos necesitan intervención primero.',
  },
  {
    id: 'claims-detail',
    route: '/claims',
    selector: '[data-tour-id="claims-detail-panel"]',
    placement: 'left',
    title: 'El detalle concentra defensa y seguimiento',
    description:
      'Cuando abres un reclamo, este panel reúne historial, contexto y acciones para responder con criterio y sin perder el hilo del caso.',
  },
  {
    id: 'items-nav',
    route: '/items',
    selector: '[data-tour-id="nav-items"]',
    placement: 'bottom',
    title: 'Productos abre tu control de catálogo',
    description:
      'Desde aquí revisas stock, estados y publicaciones activas para mantener el catálogo alineado con la operación diaria.',
  },
  {
    id: 'items-workspace',
    route: '/items',
    selector: '[data-tour-id="items-workspace"]',
    placement: 'top',
    title: 'Esta pantalla reúne el catálogo completo',
    description:
      'Puedes navegar el inventario, detectar productos pausados y entrar al detalle del ítem que quieras ajustar sin salir del panel.',
  },
  {
    id: 'items-detail-panel',
    route: '/items',
    selector: '[data-tour-id="items-detail-shell"]',
    placement: 'top',
    title: 'El detalle del producto aparece en este bloque',
    description:
      'Cuando seleccionas un ítem, aquí se despliegan resumen, métricas y acciones de edición para trabajar la publicación sin perder la lista.',
  },
  {
    id: 'copywriter-nav',
    route: '/copywriter',
    selector: '[data-tour-id="nav-copywriter"]',
    placement: 'bottom',
    title: 'Copywriter te ayuda a crear mejores publicaciones',
    description:
      'Es el módulo rápido para generar títulos y descripciones nuevas cuando quieres lanzar o mejorar contenido comercial con ayuda de IA.',
  },
  {
    id: 'copywriter-input',
    route: '/copywriter',
    selector: '[data-tour-id="copywriter-input"]',
    placement: 'right',
    title: 'Aquí defines el brief del producto',
    description:
      'Completa datos concretos del producto y el sistema construye un brief suficiente para generar propuestas más útiles y accionables.',
  },
  {
    id: 'copywriter-results',
    route: '/copywriter',
    selector: '[data-tour-id="copywriter-results"]',
    placement: 'left',
    title: 'Aquí recibes salidas listas para usar',
    description:
      'Vas a ver títulos y descripción listos para copiar, comparar y seguir refinando antes de llevarlos a una publicación real.',
  },
  {
    id: 'market-insights-nav',
    route: '/market-insights',
    selector: '[data-tour-id="nav-market-insights"]',
    placement: 'bottom',
    title: 'Insights te ayuda a descubrir oportunidades',
    description:
      'Este acceso abre el módulo de investigación para detectar tendencias, validar nichos y aterrizar oportunidades en productos concretos.',
  },
  {
    id: 'market-insights-input',
    route: '/market-insights',
    selector: '[data-tour-id="market-insights-input"]',
    placement: 'right',
    title: 'La investigación arranca desde una idea simple',
    description:
      'Escribe una categoría o necesidad en lenguaje natural y el sistema la baja a señales concretas de Mercado Libre para armar el reporte.',
  },
  {
    id: 'market-insights-results',
    route: '/market-insights',
    selector: '[data-tour-id="market-insights-results"]',
    placement: 'left',
    title: 'Aquí aterrizas la oportunidad detectada',
    description:
      'El reporte devuelve evidencia, volumen, rango de precios y señales de riesgo para que decidas con más criterio qué explorar después.',
  },
];

@Injectable({ providedIn: 'root' })
export class OnboardingTourService {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly accountContext = inject(AccountContextService);

  readonly running = signal(false);
  readonly currentPath = signal(this.normalizePath(this.router.url));
  readonly steps = signal<readonly TourStep[]>([]);
  readonly stepIndex = signal(0);
  readonly pendingTour = signal<'welcome-agent' | null>(null);

  readonly currentStep = computed(() => this.steps()[this.stepIndex()] ?? null);
  readonly stepCount = computed(() => this.steps().length);
  readonly progressLabel = computed(() => {
    const total = this.stepCount();
    if (total === 0) {
      return '0/0';
    }
    return `${this.stepIndex() + 1}/${total}`;
  });
  readonly isLastStep = computed(() => this.stepIndex() >= this.stepCount() - 1);

  private completing = false;
  private navigating = false;

  constructor() {
    this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe((event) => {
        this.currentPath.set(this.normalizePath(event.urlAfterRedirects));
        this.navigating = false;
      });

    effect(
      () => {
        const pendingTour = this.pendingTour();
        const isFirstVisit = this.auth.user()?.is_first_visit ?? false;
        const hasActiveAccess = this.accountContext.hasActiveAccess();
        const accountCount = this.accountContext.accountCount();
        const currentPath = this.currentPath();
        const isAuthScreen = currentPath.startsWith('/auth/');

        if (
          pendingTour !== 'welcome-agent' ||
          !isFirstVisit ||
          accountCount === 0 ||
          !hasActiveAccess ||
          this.completing ||
          isAuthScreen
        ) {
          return;
        }

        if (!this.running()) {
          this.steps.set(WELCOME_AGENT_TOUR);
          this.stepIndex.set(0);
          this.running.set(true);
          this.pendingTour.set(null);
        }
      },
      { allowSignalWrites: true },
    );

    effect(() => {
      const running = this.running();
      const step = this.currentStep();
      const currentPath = this.currentPath();

      if (!running || !step || step.route === currentPath || this.navigating) {
        return;
      }

      this.navigating = true;
      void this.router.navigate([step.route]).catch(() => {
        this.navigating = false;
      });
    });
  }

  requestWelcomeTour(): void {
    if (!this.auth.user()?.is_first_visit || this.running() || this.pendingTour() !== null || this.completing) {
      return;
    }
    this.pendingTour.set('welcome-agent');
  }

  next(): void {
    const step = this.currentStep();
    if (!this.running() || !step) {
      return;
    }

    if (this.isLastStep()) {
      this.finish();
      return;
    }

    this.stepIndex.set(Math.min(this.stepIndex() + 1, this.stepCount() - 1));
  }

  skip(): void {
    this.finish();
  }

  private finish(): void {
    this.running.set(false);
    this.pendingTour.set(null);
    this.steps.set([]);
    this.stepIndex.set(0);

    if (!this.auth.user()?.is_first_visit || this.completing) {
      return;
    }

    this.completing = true;
    this.auth.completeOnboarding().subscribe({
      next: () => {
        this.completing = false;
      },
      error: () => {
        this.completing = false;
      },
    });
  }

  private normalizePath(url: string): string {
    return url.split('?')[0].split('#')[0] || '/';
  }
}
