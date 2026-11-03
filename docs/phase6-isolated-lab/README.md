# Phase 6 Isolated Lab

Project: `smartprocess-accounting-lab`

This compose file is independent of `finance-mgmt` and project `erpnext`.
Do not include it from `deployment/compose.smartprocess-accounting.yaml`.

Safety rules:

- `pull_policy: never` — uses only images already on this machine
- Host bind is `127.0.0.1:18080`
- Site `lab.localhost` must list `127.0.0.1` and `localhost` in `domains`, and `sites/127.0.0.1` plus `sites/localhost` must symlink to `lab.localhost`, so `http://127.0.0.1:18080` resolves without a custom Host header
- `hooks.production.py` is the readable production `hooks.py` for contract tests. Do not copy `hooks.lab.py` onto production.
- Volumes and network have the `smartprocess-accounting-lab-` prefix
- App source is bind-mounted read-only
- Passwords are lab placeholders, not CRM secrets
- `restart: "no"` so the lab does not return after a host reboot

Do not run `docker compose down -v` without a separate written approval.
