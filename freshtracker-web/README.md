# FreshTracker Web

React/Vite frontend for FreshTracker. The app provides authenticated inventory
management, expiry-aware filtering, waste outcome analytics, and recipe
suggestions from the Flask API.

## Scripts

- `npm run dev` starts the local Vite development server.
- `npm run lint` runs Oxlint.
- `npm run test` runs Vitest.
- `npm run build` creates the production bundle served by Nginx in Docker.

The frontend expects the API to be available through the `/api` proxy in local
development or the Nginx configuration in the container image.
