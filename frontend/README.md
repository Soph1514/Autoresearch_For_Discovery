# Research lab frontend

Requires Node.js 20.19+ or 22.12+ and npm. From this directory:

```sh
npm ci
npm run dev
```

Open the URL printed by Vite (normally http://127.0.0.1:5173). Choose **Run routing demo**. No Python service, LLM key, or external API is used. **Add problem** previews text, images, documents, and initial results locally; it does not execute research on uploaded content. Drafts are discarded when the composer closes. Refreshing resets the mock lab.

The demo runs concurrent experiments, preserves a failed attempt, supports draining pause/resume and stop, and displays merges, merged mutations, and archive changes. It searches a Pigou routing family with delays x and c and unit demand. For 0 < c ≤ 1, equilibrium cost is c and optimal cost is c − c²/4. These example values are calculated; the search, timing, and niche assignments are scripted. Recovering 4/3 is a known result, not a novel bound.

## Backend handoff

- `src/contracts.ts`: frontend records, events, client interface, and state application.
- `src/mock.ts`: replaceable in-browser client. `src/main.tsx` is the composition point where the real client will be supplied.
- `src/research.tsx`: snapshot loading, event subscription, duplicate sequence suppression, gap recovery, and commands.
- UI components consume these records, not mock fixtures or Python internals.

The future HTTP/SSE adapter must implement `ResearchClient`. Routes and ownership are proposed in `../context/ui-backend-integration.md`; there is no HTTP adapter yet. TypeScript currently uses camelCase; map backend snake_case fields in that adapter rather than coupling components to wire naming. Payload validation and API authentication belong at that boundary once the team agrees the wire contract.

Vite already forwards `/api` to http://127.0.0.1:8000 for development. When available, start the backend in a separate terminal using its owner's command. The mock does not contact that proxy. Production routing must be configured separately.

## Verification

```sh
npm test
npm run build
```

Tests cover pause/drain/resume, lineage and elite transitions, rejected candidates, event replay/duplicates/gaps, stop cancellation, and the analytic routing witness. The UI keeps the viewport stable unless **Fit graph** or **Follow latest** is selected. **Compact inactive** shrinks inactive nodes but retains their ancestry and selection.
