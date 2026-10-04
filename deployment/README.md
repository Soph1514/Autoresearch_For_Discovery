# Modal deployment

The lab is deployed as `autoresearch-lab` in the `arin06` workspace:
https://arin06--autoresearch-lab-web.modal.run

FastAPI serves the built Vite frontend and API from one origin. A single warm
container owns the research loop and SQLite database. `autoresearch-lab-data`
persists the database and compiled Lean scorers. Candidate Python executes in
fresh Modal Sandboxes with blocked networking, hard CPU/memory limits, no app
secrets or data volumes, bounded output, and cancellation cleanup. Local execution
continues using Docker. The existing generation, checker, fidelity, and attachment
apps must be deployed in the same Modal environment.

Qwen generates the first Lean draft. After a failed check, Claude Opus 5.5 repairs
the source using the original formulation and current checker diagnostics.
The loop rechecks each repair until it passes or the user presses Stop; provider
errors are surfaced. The UI identifies Opus repairs. The Anthropic key in the
app Secret funds these repair calls as well as research.

## Credentials

`autoresearch-lab-secrets` is a Modal Secret containing `ANTHROPIC_API_KEY`,
`RESEARCH_DEPLOY_TOKEN`, and optionally `RESEARCH_API_USER`/`RESEARCH_API_PASSWORD`.
The initial deployment uses shared HTTP Basic authentication over HTTPS. Local
login details are in ignored `runs/modal-login.txt`; never commit credentials.
The private `deployment_access` Modal function provides deployment credentials to
authenticated Modal operators, not to public HTTP callers.

## Deploy locally

```sh
cd frontend
npm ci
npm run build
cd ..
MODAL_PROFILE=arin06 .venv/bin/python deployment/deploy.py
```

The deploy script gates new submissions, waits up to 30 minutes for active runs
and preparation requests to finish, commits the data volume, then uses Modal's
`recreate` strategy. It checks the frontend, API, isolated worker, and real Lean
compilation afterward. Deployments cause brief downtime. If work does not finish
in time, deployment is cancelled and submissions are re-enabled. Pause/resume/stop
controls remain available while draining. Paused runs must finish or be stopped.

Do not use rolling deployments or increase `max_containers`: the current
in-memory run state and SQLite volume require a single writer. A crash or
preemption interrupts an active run; history is retained, but execution does not
automatically resume. Modal periodically commits the volume; the most recent
uncommitted changes may be lost on abrupt failure. One web container stays warm
and incurs ongoing CPU/memory charges. Sandboxes have a maximum 24-hour lifetime,
even when the local UI's execution time limits are disabled.

## Updates from main

`.github/workflows/deploy-modal.yml` tests pull requests. On a push to `main`, it
runs the same checks, builds the frontend, and invokes the deploy script. The URL
and history volume stay the same. Deployments are serialized and aren't cancelled
mid-flight. `/api/health` reports the deployed Git commit.

To activate it, merge the workflow and configure repository Actions secrets:

- `MODAL_TOKEN_ID`
- `MODAL_TOKEN_SECRET`

Use a dedicated deployment/service-user token for the `arin06` workspace and
the intended Modal environment. Do not copy a collaborator's personal token into
repository secrets. An administrator may need to create the service token.
See https://modal.com/docs/guide/continuous-deployment.

The workflow deploys the web app, candidate runtime, and compiler. The separately
managed GPU generation/fidelity apps are not redeployed by this workflow.
