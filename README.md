# Kaizen Flow

Panel privado para operar cuentas de Mercado Libre con FastAPI + Angular.

## Que incluye

- backend modular para preguntas, reclamos, productos, copywriter y agente IA
- frontend standalone con Angular
- autenticacion propia con sesiones seguras
- base SQLite para usuarios, sesiones, cuentas ML y estados OAuth
- vinculacion OAuth de Mercado Libre por usuario
- refresh automatico de `access_token` usando `refresh_token`
- aislamiento por usuario para cuentas, endpoints y hilos del agente

## Arquitectura

```text
kaizen-flow/
|- backend/
|  |- app/
|  |  |- adapters/
|  |  |- agents/
|  |  |- api/
|  |  |- clients/
|  |  |- core/
|  |  |- schemas/
|  |  `- services/
|  `- requirements.txt
|- frontend/
|  `- src/app/
|- .env.example
`- README.md
```

## Seguridad

- el usuario crea su cuenta propia dentro de Kaizen Flow
- el login genera una cookie `HttpOnly` de sesion
- todas las rutas privadas `/api/*` requieren sesion valida
- cada usuario ve solo sus propias cuentas de Mercado Libre
- los tokens nunca se exponen al frontend
- los hilos del agente IA quedan separados por usuario en disco

## OAuth de Mercado Libre

Flujo implementado:

1. el usuario inicia sesion en Kaizen Flow
2. desde la UI hace clic en "Conectar Mercado Libre"
3. el backend crea `state` + PKCE y redirige a Mercado Libre
4. Mercado Libre devuelve `code`
5. el backend intercambia `code` por `access_token` y `refresh_token`
6. la cuenta queda persistida en SQLite para ese usuario

Redirect recomendado:

```env
ML_REDIRECT_URI=https://api.tudominio.com/api/auth/mercadolibre/callback
```

Compatibilidad:

- tambien existe el alias legacy `https://api.tudominio.com/auth/callback`

Importante:

- `ML_REDIRECT_URI` debe apuntar al backend publico que recibe el callback y hace el intercambio de `code` por tokens
- `FRONTEND_ORIGIN` es la URL del frontend, por ejemplo Netlify
- si pones la URL del frontend como `redirect_uri`, Mercado Libre va a rechazar o romper el flujo OAuth
- Mercado Libre puede rechazar `http://localhost` en la configuracion de la app; para desarrollo local usa un callback HTTPS publico o un puente HTTPS que reenvie al backend local

## Persistencia

- SQLite por defecto: `backend/data/kaizen_flow.sqlite3`
- hilos del agente por usuario: `backend/data/agents/user_<id>/threads/`

## Variables importantes

```env
ML_APP_ID=
ML_CLIENT_SECRET=
ML_REDIRECT_URI=https://api.tudominio.com/api/auth/mercadolibre/callback
ML_OAUTH_AUTHORIZE_URL=https://auth.mercadolibre.com.ar/authorization
ML_AUTH_BASE=https://api.mercadolibre.com
ML_API_BASE=https://api.mercadolibre.com

FRONTEND_ORIGIN=https://tu-frontend.netlify.app
APP_DB_PATH=backend/data/kaizen_flow.sqlite3
SESSION_COOKIE_NAME=kaizen_session
SESSION_COOKIE_SECURE=false
SESSION_TTL_HOURS=336

GOOGLE_API_KEY=
GOOGLE_MODEL=gemini-2.5-flash
GOOGLE_ROUTER_MODEL=gemini-2.5-flash-lite
AI_DEFAULT_SITE_ID=MLA
AI_HISTORY_WINDOW=8
AI_MEMORY_DIR=backend/data/agents
```

Notas:

- los formatos legacy con tokens directos en `.env` siguen parseandose, pero el modo recomendado ahora es OAuth por usuario
- los tokens de Mercado Libre quedan guardados en SQLite para poder refrescarlos automaticamente

## Endpoints principales

Publicos:

- `GET /api/health`
- `POST /api/auth/register`
- `POST /api/auth/login`

Privados:

- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/auth/mercadolibre/connect`
- `GET /api/accounts`
- `PATCH /api/accounts/default`
- `GET /api/agents/health`
- `GET /api/agents/threads`
- `POST /api/agents/threads`
- `GET /api/agents/threads/{thread_id}`
- `POST /api/agents/threads/{thread_id}/messages`
- `GET /api/questions`
- `GET /api/questions/{id}`
- `POST /api/questions/{id}/answer`
- `GET /api/claims`
- `GET /api/claims/{id}`
- `GET /api/claims/{id}/messages`
- `POST /api/claims/{id}/message`
- `GET /api/items`
- `GET /api/items/{id}`
- `PATCH /api/items/{id}`
- `POST /api/copywriter/generate`
- `POST /api/copywriter/enhance-description`

Seleccion de cuenta:

- query param `?account=<account_key>`
- header `X-Kaizen-Account: <account_key>`

Si no se envia una cuenta, el backend usa la cuenta por defecto del usuario autenticado.

## Frontend

Pantallas:

- `/login`
- `/register`
- `/questions`
- `/claims`
- `/items`
- `/copywriter`
- `/agents`

## Como correr

### Backend

```powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

Docs:

- `http://localhost:8000/docs`

### Frontend

```powershell
cd frontend
npm install
npm start
```

El proxy del frontend apunta a `http://127.0.0.1:8000`.

## Verificaciones realizadas

- backend: `python -m compileall backend`
- backend: smoke import local de `FastAPI` y `GET /api/health`
- frontend: `npm run build`

## Limites actuales

- los tokens de Mercado Libre se guardan cifrados en SQLite en el servidor; para endurecer aun mas produccion, el siguiente paso recomendado es mover la clave de cifrado a un secret manager
- la disponibilidad real de mensajeria en claims sigue dependiendo del estado y de las reglas reales de Mercado Libre
- el login protege la app y el API, pero no reemplaza buenas practicas de despliegue como HTTPS, rotacion de secretos y backups cifrados de la base

## Referencias oficiales usadas

- OAuth / autorizacion:
  `https://developers.mercadolibre.com.ar/es_ar/autenticacion-y-autorizacion/aprende-a-utilizar-nuestra-api`
- Auth / refresh token:
  `https://developers.mercadolibre.cl/en_us/application-management/authentication-and-authorization`
- Questions & Answers:
  `https://developers.mercadolibre.com.ni/en_us/usuarios-y-aplicaciones/questions`
- Claims:
  `https://developers.mercadolibre.com.co/en_us/working-with-claims`
- Items search:
  `https://developers.mercadolibre.com.bo/en_us/items-and-searches`
- Items update:
  `https://developers.mercadolibre.com.bo/en_us/products-sync-listings`
