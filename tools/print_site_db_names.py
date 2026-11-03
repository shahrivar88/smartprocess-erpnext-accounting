import json
from pathlib import Path

sites = Path("/home/frappe/frappe-bench/sites")
for path in sorted(sites.iterdir()):
	cfg = path / "site_config.json"
	if cfg.is_file():
		data = json.loads(cfg.read_text(encoding="utf-8"))
		print(f"{path.name} db_name={data.get('db_name')}")
