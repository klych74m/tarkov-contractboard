#!/usr/bin/env python3
"""
신규/삭제 아이템 목록을 tarkov.dev 라이브 데이터와 data/changes/ 누적 로그로 대조한다.

client/items/response.json은 항목당 필드가 수십 개라 필드 단위 비교는 하지 않는다
(범위가 너무 넓고, 대부분은 Contract Board가 안 쓰는 필드다). 대신 "이 아이템이 최상위
키로 신규 추가/삭제됐다"는 굵직한 사실만 확인한다 — 새 무기·탄약류가 실제로 tarkov.dev
아이템 목록에 들어왔는지, 삭제됐다는 아이템이 실제로 빠졌는지.
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))
import diff_parser as dp

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGES_DIR = REPO_ROOT / "data" / "changes"
JSON_API_BASE = "https://json.tarkov.dev"


def _get(path):
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
            if f["name"] != "client/items/response.json":
                continue
            for change in dp.parse(f["diff_text"]):
                events.append((entry["id"], entry["date"], change))
    return events


def build_latest_truth(events):
    """item_name -> {"state": "added"|"removed", "entry_id":, "date":}
    최상위(경로 길이 1, 'data' 제외)로 통째 추가/삭제된 것만 대상으로 한다."""
    truth = {}
    for entry_id, date, ch in events:
        path = ch.path[1:] if ch.path[:1] == ["data"] else ch.path
        if len(path) != 1 or ch.kind not in ("block_added", "block_removed"):
            continue
        name = path[0]
        state = "added" if ch.kind == "block_added" else "removed"
        prev = truth.get(name)
        if prev is None or entry_id >= prev["entry_id"]:
            truth[name] = {"state": state, "entry_id": entry_id, "date": date}
    return truth


def fetch_live_item_names(mode="regular"):
    items_en = _get(f"{mode}/items_en")
    return set(v for v in items_en.values() if isinstance(v, str))


def reconcile(mode="regular"):
    events = load_log_events()
    truth = build_latest_truth(events)
    live_names = fetch_live_item_names(mode)

    results = []
    for name, info in truth.items():
        present = name in live_names
        match = present if info["state"] == "added" else (not present)
        results.append({
            "item": name, "log_state": info["state"], "present_in_dev": present,
            "match": match, "source_entry": info["entry_id"], "source_date": info["date"],
        })
    return results


def print_report(results):
    added = [r for r in results if r["log_state"] == "added"]
    removed = [r for r in results if r["log_state"] == "removed"]
    mismatched = [r for r in results if not r["match"]]

    print(f"=== 아이템 대조: 신규 {len(added)}건 / 삭제 {len(removed)}건, 불일치 {len(mismatched)}건 ===")
    for r in mismatched:
        verb = "생겼다는데 tarkov.dev엔 없음" if r["log_state"] == "added" else "없어졌다는데 tarkov.dev엔 아직 있음"
        print(f"  ⚠ {r['item']}: 로그는 {verb}  (출처: id={r['source_entry']}, {r['source_date']})")
    if not mismatched and results:
        print("  ✅ 전부 일치 — tarkov.dev가 이미 따라잡음")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--mode", choices=["regular", "pve"], default="regular")
    args = parser.parse_args()
    results = reconcile(args.mode)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_report(results)


if __name__ == "__main__":
    main()
