"""公共工具：路径、配置、CSV 读写。"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
CHARTS_DIR = OUTPUT_DIR / "charts"
REPORTS_DIR = OUTPUT_DIR / "reports"
DEBUG_DIR = OUTPUT_DIR / "debug"
AUTH_DIR = ROOT / "auth"
CSV_PATH = DATA_DIR / "prices.csv"
STATUS_PATH = OUTPUT_DIR / "run_status.json"

CSV_FIELDS = [
    "date", "item_id", "model", "platform", "form", "brand", "chip",
    "price", "shop", "title", "url",
]

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def ensure_dirs() -> None:
    for d in (DATA_DIR, CHARTS_DIR, REPORTS_DIR, DEBUG_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def weekday_cn(d: str | None = None) -> str:
    dt = datetime.strptime(d, "%Y-%m-%d") if d else datetime.now()
    return WEEKDAYS[dt.weekday()]


def load_env() -> None:
    """极简 .env 读取（KEY=VALUE），已存在的环境变量不覆盖。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_items(path: Path | None = None) -> list[dict]:
    import yaml

    cfg_path = path or ROOT / "products.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return data.get("items", [])


def read_all_rows() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_rows(rows: list[dict]) -> None:
    """写入今日数据；同一天同一商品同一平台重复运行时覆盖旧行。"""
    ensure_dirs()
    existing = read_all_rows()
    stamped = []
    for r in rows:
        stamped.append({k: r.get(k, "") for k in CSV_FIELDS})
    keys = {(r["date"], r["item_id"], r["platform"]) for r in stamped}
    keep = [r for r in existing if (r["date"], r["item_id"], r["platform"]) not in keys]
    merged = sorted(keep + stamped, key=lambda r: (r["date"], r["item_id"], r["platform"]))
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(merged)


def write_status(status: dict) -> None:
    ensure_dirs()
    STATUS_PATH.write_text(
        __import__("json").dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_status() -> dict:
    if not STATUS_PATH.exists():
        return {}
    try:
        return __import__("json").loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
