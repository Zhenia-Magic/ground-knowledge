# Deployment and rollback runbook

Production is the Railway `portal` service. Deployment is a source build from this repository; the
application runs its additive database setup on boot. No schema step deletes or rewrites existing
knowledge bases.

## Required configuration

- `DATABASE_URL`: production Postgres connection supplied by Railway.
- `ADMIN_TOKEN`: a long random secret for full-KB replacement, moderation, deletion, and study
  results. Do not put it in the repository or build logs.
- `EPISTEMIC_CONTACT_EMAIL`: optional polite-pool contact for scholarly APIs.
- Resource ceilings may be overridden with the variables documented in [`.env.example`](.env.example).

Keep one service instance during the current in-process rate-limiter design, or add a shared edge
limiter before scaling replicas. The database concurrency controls work across replicas.

## Pre-deployment checks

From the repository root:

```bash
python -m unittest discover -s tests -t .
python eval/run_benchmark.py --require-live-baseline --check-results
python cli.py validate cases/*.kb.json
python -m compileall -q app engine eval ingest ui cli.py
git diff --check
```

Confirm that:

- `.env`, database files, participant assignments, caches, and other local artifacts are excluded
  from the upload by `.railwayignore`;
- `ADMIN_TOKEN` and `DATABASE_URL` are configured in Railway, without printing their values;
- the current production deployment ID and commit are recorded as the known-good rollback target;
- the working diff contains no unrelated or participant data.

## Deploy

```bash
railway up --service portal --environment production --ci -m "<release summary>"
```

Wait for Railway to report success, then verify:

1. `GET /healthz` returns HTTP 200 and `ok`.
2. `GET /api/questions?limit=1` returns valid JSON.
3. An administrator-auth check succeeds without exposing the token.
4. Fresh deployment logs contain no error, exception, or traceback.
5. One existing question page loads and its counts match the API response.

Do not test production by creating or deleting data unless that mutation is explicitly part of the
release plan.

## Rollback triggers

Roll back immediately if any of these occur after deploy:

- build or startup failure;
- `/healthz` does not return 200;
- the question-list API or an existing question page fails;
- database migration or repeated 5xx errors appear in fresh logs;
- existing KB counts or versions are unexpectedly changed.

## Rollback

In Railway, open the `portal` service's Deployments view, select the recorded known-good deployment,
and choose **Redeploy**. Verify the same health, read-only API, page, and log checks above. If the
failure is configuration-only, restore the previous variable value and redeploy the known-good
build. Database changes in this project are additive; do not drop columns or tables during rollback.

After recovery, record the failed deployment ID, observed symptom, rollback target, and corrective
action before attempting another release.
