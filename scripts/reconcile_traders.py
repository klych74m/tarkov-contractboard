#!/usr/bin/env python3
"""
상인 우호도 레벨 요구치(레벨/평판/판매액)를 tarkov.dev 라이브 값과 data/changes/ 누적
로그로 대조한다. scripts/reconcile_hideout.py와 같은 패턴.

비교 대상 필드(로그 원본 필드명 -> tarkov.dev 필드명, 의미가 정확히 같은 것만):
  minLevel     -> requiredPlayerLevel
  minStanding  -> requiredReputation
  minSalesSum  -> requiredCommerce

뺀 것: buy_price_coef/repair_price_coef/insurance_price_coef 등 가격 계수류는
tarkov.dev의 payRate/repairCostMultiplier/insuranceRate와 단위·스케일이 달라서
(계수 60 vs 비율 0.4 같은 식) 값이 달라도 "같은 걸 다르게 표현한 것"인지 "진짜
불일치"인지 구분이 안 된다. 공식이 확인되면 추가할 것.
insurance의 max_return_hour/min_return_hour/max_storage_time은 tarkov.dev 상인
스키마에 대응 필드 자체가 없어서(2026-08 기준) 비교 대상에서 뺐다.

로그의 우호도 레벨 인덱스는 0부터 시작하고(LL1='0'), tarkov.dev의 level은 1부터
시작한다(LL1=level 1) — 이 오프셋을 보정한다.
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, __import__("os").path.dirname(__file__))
import diff_parser as dp

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGES_DIR = REPO_ROOT / "data" / "changes"
JSON_API_BASE = "https://json.tarkov.dev"

FIELD_MAP = {
    "minLevel": "requiredPlayerLevel",
    "minStanding": "requiredReputation",
    "minSalesSum": "requiredCommerce",
}


def _get(path):
    # 큰 응답에서 이 환경의 brotli 디코더가 간헐적으로 깨지는 문제가 있어,
    # br 대신 gzip/deflate만 받도록 명시한다.
    r = requests.get(
        f"{JSON_API_BASE}/{path}", timeout=60,
        headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
    )
    r.raise_for_status()
    return r.json()["data"]


def load_log_events():
    entry_files = sorted(
        (p for p in glob.glob(str(CHANGES_DIR / "*.json")) if not p.endswith("index.json")),
        key=lambda p: int(Path(p).stem),
    )
    events = []
    for p in entry_files:
        entry = json.loads(Path(p).read_text(encoding="utf-8"))
        for f in entry.get("files", []):
            if f["name"] != "client/trading/api/traderSettings/response.json":
                continue
            for change in dp.parse(f["diff_text"]):
                events.append((entry["id"], entry["date"], change))
    return events


def _parse_object_block(text):
    """'"minLevel": 36,\\n"minSalesSum": 0,\\n...' 형태 텍스트에서 필드별 값을 뽑는다."""
    out = {}
    for m in re.finditer(r'"(\w+)":\s*"?(-?[\d.]+)"?', text or ""):
        try:
            out[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    return out


def build_latest_truth(events):
    """(trader, loyalty_level_1based, field) -> {"new": val, "entry_id":, "date":}"""
    truth = {}
    for entry_id, date, ch in events:
        path = ch.path[1:] if ch.path[:1] == ["data"] else ch.path
        # path: [trader, "loyaltyLevels", idx]  (통째 객체 교체, kind="scalar")
        if len(path) != 3 or path[1] != "loyaltyLevels" or ch.kind != "scalar":
            continue
        trader, _, idx_raw = path
        try:
            level = int(idx_raw) + 1  # 로그는 0-based, tarkov.dev는 1-based
        except ValueError:
            continue
        new_fields = _parse_object_block(ch.new)
        for raw_field, dev_field in FIELD_MAP.items():
            if raw_field not in new_fields:
                continue
            key = (trader, level, dev_field)
            prev = truth.get(key)
            if prev is None or entry_id >= prev["entry_id"]:
                truth[key] = {"new": new_fields[raw_field], "entry_id": entry_id, "date": date}
    return truth


def fetch_live_traders(mode="regular"):
    traders = _get(f"{mode}/traders")
    traders_en = _get(f"{mode}/traders_en")
    by_name = {}
    for t in traders.values():
        if not t or not t.get("id"):
            continue
        name = traders_en.get(t.get("name"), t.get("normalizedName"))
        by_name[name] = t
    return by_name


def reconcile(mode="regular"):
    events = load_log_events()
    truth = build_latest_truth(events)
    traders_by_name = fetch_live_traders(mode)

    results = []
    unmatched_traders = set()
    for (trader, level, dev_field), info in truth.items():
        live = traders_by_name.get(trader)
        if not live:
            unmatched_traders.add(trader)
            continue
        live_level = next((l for l in live["levels"] if l["level"] == level), None)
        if live_level is None:
            continue
        dev_value = live_level.get(dev_field)
        match = (dev_value is not None and abs(dev_value - info["new"]) < 0.05)
        results.append({
            "trader": trader, "level": level, "field": dev_field,
            "log_value": info["new"], "dev_value": dev_value, "match": match,
            "source_entry": info["entry_id"], "source_date": info["date"],
        })
    return results, sorted(unmatched_traders)


def print_report(results, unmatched):
    mismatched = [r for r in results if not r["match"]]
    print(f"=== 상인 우호도 요구치 대조: {len(results)}건 중 불일치 {len(mismatched)}건 ===")
    for r in mismatched:
        print(f"  ⚠ {r['trader']} LL{r['level']} {r['field']}: 로그(진짜값)={r['log_value']}"
              f"  vs  tarkov.dev={r['dev_value']}  (출처: id={r['source_entry']}, {r['source_date']})")
    if not mismatched and results:
        print("  ✅ 전부 일치 — tarkov.dev가 이미 따라잡음")
    if unmatched:
        print(f"\n⚠ tarkov.dev에서 이름 매칭 실패한 상인: {unmatched}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--mode", choices=["regular", "pve"], default="regular")
    args = parser.parse_args()
    results, unmatched = reconcile(args.mode)
    if args.json:
        print(json.dumps({"results": results, "unmatched_traders": unmatched}, ensure_ascii=False, indent=2))
    else:
        print_report(results, unmatched)


if __name__ == "__main__":
    main()
