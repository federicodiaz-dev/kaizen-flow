(function () {
  const readMeta = (name) => {
    const element = document.querySelector(`meta[name="${name}"]`);
    return element ? String(element.content || '').trim() : '';
  };

  const isLocalHost = ['localhost', '127.0.0.1'].includes(window.location.hostname);
  const apiBaseUrl = isLocalHost
    ? 'http://localhost:8000'
    : readMeta('kaizen-api-base-url') || window.location.origin;
  const appBaseUrl = isLocalHost
    ? 'http://localhost:4200'
    : readMeta('kaizen-app-base-url') || window.location.origin;

  const accessSection = document.getElementById('access');
  if (!accessSection) {
    return;
  }

  const fallbackPlans = [
    {
      code: 'starter',
      name: 'Starter',
      headline: 'Control operativo base para sellers que arrancan',
      description: 'Panel unificado, alertas basicas y operacion esencial.',
      price_monthly: 29,
      currency: 'USD',
      max_accounts: 1,
      reply_assistant_limit: 200,
      listing_doctor_limit: 5,
      features: [],
      sort_order: 10,
    },
    {
      code: 'growth',
      name: 'Growth',
      headline: 'El plan recomendado para sellers en expansion',
      description: 'Benchmark profundo, IA sin limites y foco en crecimiento.',
      price_monthly: 79,
      currency: 'USD',
      max_accounts: 1,
      reply_assistant_limit: null,
      listing_doctor_limit: null,
      features: [],
      sort_order: 20,
    },
    {
      code: 'scale',
      name: 'Scale',
      headline: 'Operacion avanzada para agencias y marcas multi cuenta',
      description: 'Mayor capacidad operativa, reportes y soporte prioritario.',
      price_monthly: 149,
      currency: 'USD',
      max_accounts: 5,
      reply_assistant_limit: null,
      listing_doctor_limit: null,
      features: [],
      sort_order: 30,
    },
  ];

  const state = {
    plans: [...fallbackPlans],
    selectedPlanCode: 'growth',
    currentUser: null,
    accessMode: 'register',
    isSubmitting: false,
  };

  const elements = {
    openAppLink: document.getElementById('access-open-app'),
    logoutButton: document.getElementById('access-logout'),
    feedback: document.getElementById('access-feedback'),
    registerForm: document.getElementById('access-register-form'),
    loginForm: document.getElementById('access-login-form'),
    tabButtons: document.querySelectorAll('[data-access-mode]'),
    miniPlans: document.getElementById('access-mini-plans'),
    statusTitle: document.getElementById('access-status-title'),
    statusCopy: document.getElementById('access-status-copy'),
    statusUser: document.getElementById('access-status-user'),
    statusEmail: document.getElementById('access-status-email'),
    statusPlan: document.getElementById('access-status-plan'),
    selectedPlanName: document.getElementById('access-selected-plan-name'),
    selectedPlanCopy: document.getElementById('access-selected-plan-copy'),
    registerPlanName: document.getElementById('access-register-plan-name'),
    loginPlanName: document.getElementById('access-login-plan-name'),
    pricingButtons: document.querySelectorAll('.js-plan-select'),
    pricingCards: document.querySelectorAll('[data-plan-card]'),
  };

  const apiUrl = (path) => `${apiBaseUrl}${path}`;

  const getPlanByCode = (planCode) =>
    state.plans.find((plan) => plan.code === planCode) || state.plans[0] || fallbackPlans[0];

  const setFeedback = (message, tone) => {
    if (!elements.feedback) {
      return;
    }
    elements.feedback.hidden = false;
    elements.feedback.textContent = message;
    elements.feedback.dataset.tone = tone;
  };

  const clearFeedback = () => {
    if (!elements.feedback) {
      return;
    }
    elements.feedback.hidden = true;
    elements.feedback.textContent = '';
    delete elements.feedback.dataset.tone;
  };

  const setSubmitting = (isSubmitting) => {
    state.isSubmitting = isSubmitting;
    [elements.registerForm, elements.loginForm].forEach((form) => {
      if (!form) {
        return;
      }
      form.querySelectorAll('input, button').forEach((control) => {
        control.disabled = isSubmitting;
      });
    });
    if (elements.logoutButton) {
      elements.logoutButton.disabled = isSubmitting;
    }
  };

  const extractMessage = (payload, fallbackMessage) => {
    if (typeof payload === 'string' && payload.trim()) {
      return payload.trim();
    }
    if (payload && typeof payload === 'object') {
      if (typeof payload.message === 'string' && payload.message.trim()) {
        return payload.message.trim();
      }
      if (payload.details && typeof payload.details === 'object') {
        if (typeof payload.details.message === 'string' && payload.details.message.trim()) {
          return payload.details.message.trim();
        }
      }
    }
    return fallbackMessage;
  };

  const requestJson = async (path, options) => {
    const response = await fetch(apiUrl(path), {
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(options && options.body ? { 'Content-Type': 'application/json' } : {}),
      },
      ...options,
      body: options && options.body ? JSON.stringify(options.body) : undefined,
    });

    const rawText = await response.text();
    let payload = null;
    if (rawText) {
      try {
        payload = JSON.parse(rawText);
      } catch (_) {
        payload = rawText;
      }
    }

    if (!response.ok) {
      throw new Error(extractMessage(payload, `No se pudo completar la solicitud (${response.status}).`));
    }

    return payload;
  };

  const syncMarketingLinks = () => {
    document.querySelectorAll('.nav-cta, .hero .btn-primary, .final-cta .btn-primary').forEach((link) => {
      link.setAttribute('href', '#access');
    });
  };

  const markSelectedPricingCard = () => {
    elements.pricingCards.forEach((card) => {
      card.classList.toggle('is-selected', card.dataset.planCard === state.selectedPlanCode);
    });
  };

  const renderSelectedPlan = () => {
    const activePlan = state.currentUser && state.currentUser.current_plan
      ? getPlanByCode(state.currentUser.current_plan.code)
      : getPlanByCode(state.selectedPlanCode);

    if (elements.selectedPlanName) {
      elements.selectedPlanName.textContent = activePlan.name;
    }
    if (elements.selectedPlanCopy) {
      elements.selectedPlanCopy.textContent = activePlan.headline;
    }
    if (elements.registerPlanName) {
      elements.registerPlanName.textContent = activePlan.name;
    }
    if (elements.loginPlanName) {
      elements.loginPlanName.textContent = activePlan.name;
    }
    if (elements.statusPlan) {
      elements.statusPlan.textContent = activePlan.name;
    }

    markSelectedPricingCard();
  };

  const renderMiniPlans = () => {
    if (!elements.miniPlans) {
      return;
    }

    elements.miniPlans.innerHTML = '';
    state.plans.forEach((plan) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'access-mini-plan';
      if (plan.code === state.selectedPlanCode) {
        button.classList.add('is-selected');
      }
      button.dataset.planCode = plan.code;
      button.textContent = `${plan.name} · ${plan.currency} ${plan.price_monthly}`;
      button.addEventListener('click', () => {
        void choosePlan(plan.code, { persistIfAuthenticated: true, scrollToAccess: false });
      });
      elements.miniPlans.appendChild(button);
    });
  };

  const renderUserState = () => {
    if (elements.openAppLink) {
      elements.openAppLink.href = appBaseUrl;
    }

    if (state.currentUser) {
      const currentPlan = state.currentUser.current_plan
        ? getPlanByCode(state.currentUser.current_plan.code)
        : getPlanByCode(state.selectedPlanCode);
      state.selectedPlanCode = currentPlan.code;
      if (elements.statusTitle) {
        elements.statusTitle.textContent = `Sesion activa como ${state.currentUser.username}`;
      }
      if (elements.statusCopy) {
        elements.statusCopy.textContent = 'Tu identidad ya vive en el backend principal. Puedes abrir el panel grande o cambiar el plan desde esta misma landing.';
      }
      if (elements.statusUser) {
        elements.statusUser.textContent = state.currentUser.username;
      }
      if (elements.statusEmail) {
        elements.statusEmail.textContent = state.currentUser.email;
      }
      if (elements.statusPlan) {
        elements.statusPlan.textContent = currentPlan.name;
      }
      if (elements.logoutButton) {
        elements.logoutButton.hidden = false;
      }
      if (elements.openAppLink) {
        elements.openAppLink.textContent = `Abrir panel principal (${currentPlan.name})`;
      }
    } else {
      if (elements.statusTitle) {
        elements.statusTitle.textContent = 'Sin sesion activa';
      }
      if (elements.statusCopy) {
        elements.statusCopy.textContent = 'Selecciona un plan, crea tu cuenta y el backend dejara lista la misma identidad para la otra UI del sistema.';
      }
      if (elements.statusUser) {
        elements.statusUser.textContent = 'Pendiente';
      }
      if (elements.statusEmail) {
        elements.statusEmail.textContent = 'Pendiente';
      }
      if (elements.logoutButton) {
        elements.logoutButton.hidden = true;
      }
      if (elements.openAppLink) {
        elements.openAppLink.textContent = 'Abrir panel principal';
      }
    }

    renderMiniPlans();
    renderSelectedPlan();
  };

  const setAccessMode = (mode) => {
    state.accessMode = mode === 'login' ? 'login' : 'register';
    elements.tabButtons.forEach((button) => {
      button.classList.toggle('active', button.dataset.accessMode === state.accessMode);
    });
    if (elements.registerForm) {
      elements.registerForm.hidden = state.accessMode !== 'register';
    }
    if (elements.loginForm) {
      elements.loginForm.hidden = state.accessMode !== 'login';
    }
  };

  const scrollIntoAccess = () => {
    accessSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const persistCurrentPlan = async (planCode, successMessage) => {
    const response = await requestJson('/api/plans/select', {
      method: 'POST',
      body: { plan_code: planCode },
    });
    state.currentUser = response.user;
    renderUserState();
    setFeedback(successMessage || `Plan ${getPlanByCode(planCode).name} guardado correctamente.`, 'success');
  };

  const choosePlan = async (planCode, options) => {
    const resolvedOptions = {
      persistIfAuthenticated: true,
      scrollToAccess: true,
      ...options,
    };

    state.selectedPlanCode = planCode;
    renderSelectedPlan();
    renderMiniPlans();

    if (resolvedOptions.scrollToAccess) {
      scrollIntoAccess();
    }

    if (state.currentUser && resolvedOptions.persistIfAuthenticated) {
      try {
        setSubmitting(true);
        await persistCurrentPlan(planCode, `Plan ${getPlanByCode(planCode).name} activado en tu cuenta.`);
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : 'No se pudo guardar el plan.', 'error');
      } finally {
        setSubmitting(false);
      }
    }
  };

  const handleRegister = async (event) => {
    event.preventDefault();
    if (!elements.registerForm || state.isSubmitting) {
      return;
    }

    const formData = new FormData(elements.registerForm);
    const email = String(formData.get('email') || '').trim();
    const username = String(formData.get('username') || '').trim();
    const password = String(formData.get('password') || '');
    const confirmPassword = String(formData.get('confirmPassword') || '');

    clearFeedback();
    if (!email || !username || !password) {
      setFeedback('Completa email, username y contrasena para crear tu cuenta.', 'error');
      return;
    }
    if (password !== confirmPassword) {
      setFeedback('Las contrasenas no coinciden.', 'error');
      return;
    }

    try {
      setSubmitting(true);
      const response = await requestJson('/api/auth/register', {
        method: 'POST',
        body: {
          email,
          username,
          password,
          selected_plan_code: state.selectedPlanCode,
        },
      });
      state.currentUser = response.user;
      renderUserState();
      setFeedback(`Cuenta creada correctamente. El plan ${getPlanByCode(state.selectedPlanCode).name} ya quedo asociado a ${response.user.username}.`, 'success');
      elements.registerForm.reset();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'No se pudo crear la cuenta.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogin = async (event) => {
    event.preventDefault();
    if (!elements.loginForm || state.isSubmitting) {
      return;
    }

    const formData = new FormData(elements.loginForm);
    const login = String(formData.get('login') || '').trim();
    const password = String(formData.get('password') || '');

    clearFeedback();
    if (!login || !password) {
      setFeedback('Completa tu email o username y la contrasena.', 'error');
      return;
    }

    try {
      setSubmitting(true);
      const response = await requestJson('/api/auth/login', {
        method: 'POST',
        body: { login, password },
      });
      state.currentUser = response.user;
      renderUserState();

      const currentPlanCode = response.user.current_plan ? response.user.current_plan.code : null;
      if (state.selectedPlanCode && state.selectedPlanCode !== currentPlanCode) {
        await persistCurrentPlan(
          state.selectedPlanCode,
          `Sesion iniciada. Tambien dejamos activo el plan ${getPlanByCode(state.selectedPlanCode).name}.`
        );
      } else {
        setFeedback(`Sesion iniciada correctamente como ${response.user.username}.`, 'success');
      }

      elements.loginForm.reset();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'No se pudo iniciar sesion.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleLogout = async () => {
    if (state.isSubmitting) {
      return;
    }

    clearFeedback();
    try {
      setSubmitting(true);
      await requestJson('/api/auth/logout', { method: 'POST' });
      state.currentUser = null;
      renderUserState();
      setFeedback('Sesion cerrada correctamente.', 'success');
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'No se pudo cerrar la sesion.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const wirePlanButtons = () => {
    elements.pricingButtons.forEach((button) => {
      button.addEventListener('click', () => {
        const planCode = button.dataset.planCode;
        if (planCode) {
          void choosePlan(planCode, { persistIfAuthenticated: true, scrollToAccess: true });
        }
      });
    });

    [
      ['growth', 'a[href*="Quiero%20el%20plan%20Growth"]'],
      ['scale', 'a[href*="Quiero%20el%20plan%20Scale"]'],
    ].forEach(([planCode, selector]) => {
      document.querySelectorAll(selector).forEach((link) => {
        link.addEventListener('click', (event) => {
          event.preventDefault();
          void choosePlan(planCode, { persistIfAuthenticated: true, scrollToAccess: true });
        });
      });
    });
  };

  const bootstrap = async () => {
    syncMarketingLinks();
    wirePlanButtons();
    renderUserState();
    setAccessMode('register');

    elements.tabButtons.forEach((button) => {
      button.addEventListener('click', () => {
        clearFeedback();
        setAccessMode(button.dataset.accessMode || 'register');
      });
    });

    if (elements.registerForm) {
      elements.registerForm.addEventListener('submit', (event) => {
        void handleRegister(event);
      });
    }

    if (elements.loginForm) {
      elements.loginForm.addEventListener('submit', (event) => {
        void handleLogin(event);
      });
    }

    if (elements.logoutButton) {
      elements.logoutButton.addEventListener('click', () => {
        void handleLogout();
      });
    }

    try {
      const planPayload = await requestJson('/api/plans');
      if (planPayload && Array.isArray(planPayload.plans) && planPayload.plans.length > 0) {
        state.plans = planPayload.plans;
      }
      if (!state.plans.some((plan) => plan.code === state.selectedPlanCode)) {
        state.selectedPlanCode = state.plans[0].code;
      }
    } catch (_) {
      // Fallback catalog already loaded in memory.
    }

    try {
      const sessionPayload = await requestJson('/api/auth/me');
      state.currentUser = sessionPayload.user;
      if (sessionPayload.user && sessionPayload.user.current_plan) {
        state.selectedPlanCode = sessionPayload.user.current_plan.code;
      }
    } catch (_) {
      state.currentUser = null;
    }

    renderUserState();
  };

  void bootstrap();
})();
