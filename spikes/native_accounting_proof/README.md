# Native Accounting Proof Lab

This folder contains disposable proof artifacts. It is not the V2 application.

The Docker stack uses its own internal network and named volumes. It publishes no host port.

Resources:

- Network: `sp_accounting_v2_proof_network`
- Site volume: `sp_accounting_v2_proof_sites`
- Database volume: `sp_accounting_v2_proof_db`
- Redis volumes: `sp_accounting_v2_proof_redis_cache` and `sp_accounting_v2_proof_redis_queue`
- Log volume: `sp_accounting_v2_proof_logs`
- Site: `sp_accounting_v2_test`

Start the lab with an ignored `.env.proof` file:

```bash
docker compose --env-file .env.proof up -d
```

The app under `app_overlay` is a proof-only fixture. It must not be installed on a production site or copied into the future V2 application as production code. Evidence and the exact test command are in `docs/v2/NATIVE_ACCOUNTING_PROOF.md`.

For a fresh lab, configure only this Bench, create the disposable site, and install ERPNext:

```bash
docker compose --env-file .env.proof exec backend bench set-config -g db_host db
docker compose --env-file .env.proof exec backend bench set-config -g db_port 3306
docker compose --env-file .env.proof exec backend bench set-config -g redis_cache redis://redis-cache:6379
docker compose --env-file .env.proof exec backend bench set-config -g redis_queue redis://redis-queue:6379
docker compose --env-file .env.proof exec backend bench set-config -g redis_socketio redis://redis-queue:6379
docker compose --env-file .env.proof exec backend bench new-site sp_accounting_v2_test \
  --db-root-password DISPOSABLE_DB_PASSWORD \
  --admin-password DISPOSABLE_ADMIN_PASSWORD \
  --no-mariadb-socket
docker compose --env-file .env.proof exec backend \
  bench --site sp_accounting_v2_test install-app erpnext
```

Copy `app_overlay` to `/home/frappe/frappe-bench/apps/sp_accounting_native_proof` in the proof backend. Add `sp_accounting_native_proof` as a separate line in `sites/apps.txt`. Then run `install-app`, `migrate`, and the proof runner with this environment value:

```text
PYTHONPATH=/home/frappe/frappe-bench/apps/sp_accounting_native_proof
```

The proof network is intentionally internal. Do not enable network access merely to install the fixture. The `PYTHONPATH` registration avoids downloading a build backend into the lab.

Do not attach production volumes or networks. Do not use `SmartProcessERP`.

After the evidence is recorded, the operator can destroy the lab with:

```bash
docker compose --env-file .env.proof down --volumes --remove-orphans
```

Destruction is optional and must not run before evidence review.
