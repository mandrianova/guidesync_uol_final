# GuideSync Frontend

React + Vite frontend for the GuideSync Agent API.

## Stack

- React + TypeScript for component structure and type-safe API calls.
- Mantine for the application shell, forms, buttons, cards, badges, notifications, and responsive layout.
- Tabler icons for consistent action/navigation iconography.

Mantine was chosen over copy-based component kits because GuideSync is a data-heavy operator interface: the project needs maintained form controls, status surfaces, responsive application shell behavior, and notifications more than a marketing-oriented design system.

## Run Locally

Run the frontend through the GuideSync Docker Compose stack from the app root:

```bash
cd guidesync-agent
docker compose up --build frontend
```

Open `http://127.0.0.1:5173`. Vite proxies API requests to `http://127.0.0.1:8770`.

## Generate API SDK

The API client uses generated OpenAPI types from the FastAPI Swagger schema.
Run this after backend route or schema changes through Docker Compose:

```bash
docker compose run --rm frontend sh -c "npm install && npm run generate:api"
```

The Compose frontend service uses `GUIDESYNC_OPENAPI_URL=http://app:8770/openapi.json`.
Do not hand-edit `src/api/generated/schema.ts`; fix the FastAPI/Pydantic contract
and regenerate the SDK.

## Validate

```bash
docker compose run --rm frontend sh -c "npm install && npm run build"
```
