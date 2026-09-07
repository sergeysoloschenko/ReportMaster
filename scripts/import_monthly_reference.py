"""Import the agreed July baseline; content stays outside Git."""
import argparse
from pathlib import Path
from dotenv import load_dotenv
from src.reporting.pipeline import MonthlyService

load_dotenv(override=False)
p = argparse.ArgumentParser()
p.add_argument("path", type=Path)
p.add_argument("--period", required=True)
args = p.parse_args()
service = MonthlyService()
report = service.import_reference(args.path, args.period)
print("Report ID:", report["id"], flush=True)
service.pool.shutdown(wait=True)
result = service.store.get(report["id"])
print(
    "Status:",
    result["status"],
    "tasks:",
    len(result["tasks"]),
    "risks:",
    len(result["risks"]),
)
if result.get("error"):
    raise SystemExit(result["error"])
