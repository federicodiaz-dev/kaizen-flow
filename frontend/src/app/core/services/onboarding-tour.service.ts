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
    id: 'agents-nav',
    route: '/agents',
    selector: '[data-tour-id="nav-agents"]',
    placement: 'right',
    title: 'Este es tu agente principal',
    description:
      'Desde aca entras al copiloto de Mercado Libre para pedir analisis, respuestas y resumenes usando lenguaje natural.',
  },
  {
    id: 'agents-history',
    route: '/agents',
    selector: '[data-tour-id="agents-history"]',
    placement: 'right',
    title: 'Aca vivira tu historial',
    description:
      'Cada conversacion queda guardada por cuenta para que puedas retomar consultas anteriores sin mezclar contextos.',
  },
  {
    id: 'agents-stage',
    route: '/agents',
    selector: '[data-tour-id="agents-stage"]',
    placement: 'top',
    title: 'Este es el panel de trabajo',
    description:
      'En esta vista vas a seguir la conversacion, ver las respuestas del agente y trabajar con el contexto real de tu cuenta.',
  },
  {
    id: 'agents-composer',
    route: '/agents',
    selector: '[data-tour-id="agents-composer"]',
    placement: 'top',
    title: 'Escribi tu primera consulta aca',
    description:
      'Podes preguntar por reclamos, preguntas, publicaciones o estrategia. Enter envia y Shift + Enter agrega una nueva linea.',
  },
  {
    id: 'questions-workspace',
    route: '/questions',
    selector: '[data-tour-id="questions-workspace"]',
    placement: 'top',
    title: 'Aca resolves preguntas de compradores',
    description:
      'Desde esta seccion revisas consultas pendientes, abris el detalle y respondes manualmente o con ayuda de IA.',
  },
  {
    id: 'questions-response-panel',
    route: '/questions',
    selector: '[data-tour-id="questions-response-panel"]',
    placement: 'left',
    title: 'El detalle te muestra el contexto y la respuesta',
    description:
      'Cuando eliges una pregunta, aqui ves la publicacion asociada y el espacio donde redactas o completas el borrador con IA antes de enviarlo.',
  },
  {
    id: 'claims-workspace',
    route: '/claims',
    selector: '[data-tour-id="claims-workspace"]',
    placement: 'top',
    title: 'Aca seguis reclamos y mediaciones',
    description:
      'Este panel concentra reclamos abiertos, mensajes y opciones de respuesta para comprador o mediador.',
  },
  {
    id: 'claims-tabs',
    route: '/claims',
    selector: '[data-tour-id="claims-tabs"]',
    placement: 'left',
    title: 'Aqui cambias entre comprador y mediacion',
    description:
      'Estas pestanas separan el canal con el comprador del canal con Mercado Libre para que cada mensaje salga por el lugar correcto.',
  },
  {
    id: 'claims-composer',
    route: '/claims',
    selector: '[data-tour-id="claims-composer"]',
    placement: 'left',
    title: 'Desde este bloque preparas tu defensa',
    description:
      'Puedes redactar manualmente o pedir un borrador a la IA, revisarlo con calma y decidir si lo envias al comprador o al mediador.',
  },
  {
    id: 'items-workspace',
    route: '/items',
    selector: '[data-tour-id="items-workspace"]',
    placement: 'top',
    title: 'Aca administras tu catalogo',
    description:
      'En productos podes revisar stock, estado, descripcion y usar IA para mejorar contenido sin salir del panel.',
  },
  {
    id: 'items-detail-panel',
    route: '/items',
    selector: '[data-tour-id="items-detail-panel"]',
    placement: 'top',
    title: 'Aqui se abre el producto seleccionado',
    description:
      'Al elegir un item, en este panel ves su resumen, metricas y la configuracion publica lista para revisar antes de editar.',
  },
  {
    id: 'items-edit-panel',
    route: '/items',
    selector: '[data-tour-id="items-edit-panel"]',
    placement: 'top',
    title: 'Esta es tu zona de edicion rapida',
    description:
      'Desde aqui cambias titulo, precio, stock y estado para el producto activo sin salir del panel.',
  },
  {
    id: 'items-description-field',
    route: '/items',
    selector: '[data-tour-id="items-description-field"]',
    placement: 'top',
    title: 'La descripcion tambien se mejora desde aca',
    description:
      'Este bloque te deja reescribir la descripcion y usar el boton de IA para autocompletar un texto mas solido antes de guardarlo.',
  },
  {
    id: 'copywriter-input',
    route: '/copywriter',
    selector: '[data-tour-id="copywriter-input"]',
    placement: 'right',
    title: 'El copywriter arranca desde este formulario',
    description:
      'Completas la informacion del producto y la IA prepara titulos SEO y una descripcion lista para usar.',
  },
  {
    id: 'copywriter-results',
    route: '/copywriter',
    selector: '[data-tour-id="copywriter-results"]',
    placement: 'left',
    title: 'Aca recibis los textos generados',
    description:
      'Cuando terminas, vas a ver propuestas de titulos y la descripcion final para copiar o seguir refinando.',
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
