# Kaizen Flow

MVP privado para operar con Mercado Libre desde un panel propio.

Incluye:

- `backend/` con FastAPI y capa modular de integración con Mercado Libre
- `frontend/` con Angular standalone
- pantallas para `questions`, `claims` e `items`
- selector de cuenta vía backend
- soporte de refresh token en backend

## Arquitectura

```text
kaizen-flow/
├── backend/
│   ├── app/
│   │   ├── adapters/
│   │   ├── api/
│   │   ├── clients/
│   │   ├── core/
│   │   ├── schemas/
│   │   └── services/
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── src/app/core/
│   ├── src/app/features/questions/
│   ├── src/app/features/claims/
│   └── src/app/features/items/
├── .env.example
└── README.md
```

## Features implementadas

### Preguntas

- listado de preguntas
- búsqueda local por texto / item / id
- filtro respondidas / no respondidas
- detalle de la pregunta
- respuesta desde la UI
- envío real desde backend a Mercado Libre con `POST /answers`

### Reclamos

- listado de reclamos
- detalle enriquecido
- mensajes del reclamo
- historial de estado
- acciones disponibles informadas por API
- envío de mensaje desde backend cuando el flujo lo permite

Notas:

- la mensajería de claims depende del estado, etapa y reglas reales de Mercado Libre
- si el backend detecta que no corresponde, la UI lo muestra como limitación
- no se inventaron acciones extra fuera de la documentación oficial

### Productos

- listado de publicaciones
- búsqueda local por título o id
- filtro por estado
- detalle del producto
- link a la publicación
- edición básica de `title`, `price`, `available_quantity` y `status`

Notas:

- el título queda deshabilitado en UI si la publicación ya tiene ventas, alineado con la documentación oficial
- la API de Mercado Libre sigue validando restricciones finales

## Cuentas y `.env`

El backend nunca expone tokens al frontend.

Formatos soportados:

1. Formato explícito recomendado:

```env
ML_SELLER_ACCESS_TOKEN=
ML_SELLER_REFRESH_TOKEN=
ML_SELLER_USER_ID=

ML_PERSONAL_ACCESS_TOKEN=
ML_PERSONAL_REFRESH_TOKEN=
ML_PERSONAL_USER_ID=

ML_BUYER_ACCESS_TOKEN=
ML_BUYER_REFRESH_TOKEN=
ML_BUYER_USER_ID=
```

2. Formato legacy:

```env
access_token=
refresh_token=
user_id=
scope=
```

3. Bloques JSON legacy:

- el backend los detecta si contienen `access_token`
- si no tienen nombre, quedan como cuentas legacy

Estado actual detectado en tu `.env`:

- hoy el backend encuentra solo `seller` como cuenta usable bajo las convenciones actuales
- la app ya está preparada para `personal` y `buyer`, pero hay que agregarlas explícitamente con prefijos para que aparezcan como alias estables

## Endpoints backend

- `GET /api/health`
- `GET /api/accounts`
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
- `GET /api/claims/{id}/available-actions`
- `GET /api/items`
- `GET /api/items/{id}`
- `PATCH /api/items/{id}`
- `GET /api/items/{id}/permalink`

Selección de cuenta:

- query param `?account=seller`
- header `X-Kaizen-Account: seller`

Si no se envía nada, usa la cuenta por defecto.

## Pantallas frontend

- `/questions`
- `/claims`
- `/items`

## Asistente AI multiagente

El backend ahora incluye una capa nueva en `backend/app/agents/` pensada para un chatbot multiagente con LangChain + LangGraph.

Arquitectura:

- `intent analyst`: entiende la intencion principal y enruta con salida estructurada
- `mercadolibre account agent`: responde preguntas sobre la cuenta activa usando herramientas read-only
- `market intelligence agent`: analiza mercado, ideas de producto, competencia y tendencias
- `main workflow`: recupera memoria del hilo, enruta, ejecuta el sub-workflow correcto y persiste la conversacion

Persistencia:

- los hilos del chatbot se guardan en `backend/data/agents/threads/`

Tooling:

- si configurás un MCP de Mercado Libre, el asistente carga sus herramientas read-only
- si no hay MCP disponible, usa herramientas locales de compatibilidad sobre la API actual de Mercado Libre

Variables nuevas sugeridas en `.env`:

```env
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_ROUTER_MODEL=openai/gpt-oss-20b
AI_DEFAULT_SITE_ID=MLA
AI_HISTORY_WINDOW=8
AI_MEMORY_DIR=backend/data/agents

# MCP opcional
AI_MCP_ENABLED=false
AI_MCP_SERVER_NAME=mercadolibre
AI_MCP_TRANSPORT=http
AI_MCP_URL=
AI_MCP_COMMAND=
AI_MCP_ARGS_JSON=[]
AI_MCP_HEADERS_JSON={}
AI_MCP_ENV_JSON={}
AI_MCP_CWD=
```

## Cómo correr

### Backend

Instalar dependencias:

```powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Levantar API:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

API docs:

- `http://localhost:8000/docs`

### Frontend

Instalar dependencias:

```powershell
cd frontend
npm install
```

Levantar Angular:

```powershell
cd frontend
npm start
```

El proxy del frontend apunta a `http://127.0.0.1:8000`.

## Verificaciones realizadas

- `backend`: compilación sintáctica con `compileall`
- `backend`: smoke import de `FastAPI` y de la app
- `backend`: health check local `GET /api/health`
- `frontend`: `npm run build`

## Limitaciones reales encontradas

- La API de claims sí permite lectura y mensajería, pero la disponibilidad real depende del estado y de las acciones expuestas por Mercado Libre en cada caso.
- No implementé mediaciones complejas ni acciones no verificadas documentalmente.
- El link humano al reclamo dentro de Mercado Libre no quedó generado porque no encontré una URL oficial/documentada estable para construirlo sin inventar.
- El detalle de order asociado al claim quedó preparado para crecer, pero en este MVP se priorizó no asumir estructuras no verificadas.
- Tu `.env` actual no está declarando todavía aliases estables para `buyer` y `personal`.

## Referencias oficiales usadas

- Questions & Answers:
  `https://developers.mercadolibre.com.ni/en_us/usuarios-y-aplicaciones/questions`
- Claims:
  `https://developers.mercadolibre.com.co/en_us/working-with-claims`
- Items search:
  `https://developers.mercadolibre.com.bo/en_us/items-and-searches`
- Items update:
  `https://developers.mercadolibre.com.bo/en_us/products-sync-listings`
- Auth / refresh token:
  `https://developers.mercadolibre.cl/en_us/application-management/authentication-and-authorization`

## Próximos pasos recomendados

1. Normalizar `.env` con `ML_SELLER_*`, `ML_PERSONAL_*` y `ML_BUYER_*`.
2. Probar con datos reales de claims para ajustar `receiver_role` por flujo.
3. Agregar enriquecimiento opcional de órdenes si querés más contexto en reclamos.
4. Sumar persistencia segura de tokens refrescados si querés conservar refresh en reinicios del backend.
