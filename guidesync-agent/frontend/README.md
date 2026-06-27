# GuideSync Frontend

React + Vite frontend for the GuideSync Agent API.

## Stack

- React + TypeScript for component structure and type-safe API calls.
- Mantine for the application shell, forms, buttons, cards, badges, notifications, and responsive layout.
- Tabler icons for consistent action/navigation iconography.

Mantine was chosen over copy-based component kits because GuideSync is a data-heavy operator interface: the project needs maintained form controls, status surfaces, responsive application shell behavior, and notifications more than a marketing-oriented design system.

## Run Locally

Start the FastAPI app first:

```bash
cd project/guidesync-agent
uv run guidesync-agent-api --host 127.0.0.1 --port 8770
```

Then start the React frontend:

```bash
cd project/guidesync-agent/frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies API requests to `http://127.0.0.1:8770`.

## Generate API SDK

The API client uses generated OpenAPI types from the FastAPI Swagger schema.
Run this after backend route or schema changes while the API is available on
`127.0.0.1:8770`:

```bash
npm run generate:api
```

## Validate

```bash
npm run build
```
