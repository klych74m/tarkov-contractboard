#!/usr/bin/env python3
"""
하이드아웃 제작 레시피(신규/삭제)를 tarkov.dev 라이브 crafts 데이터와 data/changes/
누적 로그로 대조한다.

로그의 레시피 키는 "_id(원본ID), 시설명(lvl N) -> 결과물명" 형태로 시설/레벨/결과물이
전부 문자열로 박혀 있다. tarkov.dev의 crafts는 station/productItem이 24자리 hex ID라서,
items_en + hideout_en으로 이름을 번역해 (station, level, product) 3요소로 매칭한다.
원본 _id 자체는 두 파이프라인이 서로 다르게 부여해서 직접 비교할 수 없다.

리포트가 말하는 것: "로그가 새로 생겼다는 레시피가 tarkov.dev에도 있는가",
"로그가 없어졌다는 레시피가 tarkov.dev에서도 없는가".
"""

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))
import diff_parser as dp

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGES_DIR = REPO_ROOT / "data" / "changes"
JSON_API_BASE = "https://json.tarkov.dev"

RECIPE_KEY_RE = re.compile(r"^_id\(([0-9a-f]+)\),\s*(.+?)\(lvl (\d+)\)\s*->\s*(.+)$")


def _get(path):
    # 큰 응답(예: regular/items, ~16MB)에서 이 환경의 brotli 디코더가 간헐적으로
    # 깨지는 문제가 있어, br 대신 gzip/deflate만 받도록 명시한다.
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
            if f["name"] != "client/hideout/production/recipes/response.json":
                continue
            for change in dp.parse(f["diff_text"]):
                events.append((entry["id"], entry["date"], change))
    return events


def build_latest_truth(events):
    """(station, level, product) -> {"state": "added"|"removed", "entry_id":, "date":}
    같은 레시피가 여러 패치에 걸쳐 추가/삭제를 반복하면 가장 최근 상태만 남긴다."""
    truth = {}
    for entry_id, date, ch in events:
        if ch.kind not in ("block_added", "block_removed") or not ch.block_key:
            continue
        m = RECIPE_KEY_RE.match(ch.block_key)
        if not m:
            continue
        _raw_id, station, level, product = m.groups()
        key = (station.strip(), int(level), product.strip())
        state = "added" if ch.kind == "block_added" else "removed"
        prev = truth.get(key)
        if prev is None or entry_id >= prev["entry_id"]:
            truth[key] = {"state": state, "entry_id": entry_id, "date": date}
    return truth


def fetch_live(mode="regular"):
    crafts = _get(f"{mode}/crafts")
    hideout = _get(f"{mode}/hideout")
    hideout_en = _get(f"{mode}/hideout_en")
    items_en = _get(f"{mode}/items_en")
    items_raw = _get(f"{mode}/items")
    items_raw = items_raw.get("items", items_raw)

    station_name_by_id = {}
    for s in hideout.values():
        if s and s.get("id"):
            station_name_by_id[s["id"]] = hideout_en.get(s.get("name"), s.get("normalizedName"))

    def item_name(item_id):
        it = items_raw.get(item_id)
        if not it:
            return None
        return items_en.get(it.get("name"), it.get("normalizedName"))

    live_set = set()
    for c in crafts:
        station = station_name_by_id.get(c.get("station"))
        product = item_name((c.get("productItem") or {}).get("item"))
        if station and product:
            live_set.add((station, c.get("level"), product))
    return live_set


def reconcile(mode="regular"):
    events = load_log_events()
    truth = build_latest_truth(events)
    live_set = fetch_live(mode)

    results = []
    for (station, level, product), info in truth.items():
        present_in_dev = (station, level, product) in live_set
        if info["state"] == "added":
            match = present_in_dev
        else:  # removed
            match = not present_in_dev
        results.append({
            "station": station, "level": level, "product": product,
            "log_state": info["state"], "present_in_dev": present_in_dev, "match": match,
            "source_entry": info["entry_id"], "source_date": info["date"],
        })
    return results


def print_report(results):
    mismatched = [r for r in results if not r["match"]]
    print(f"=== 하이드아웃 레시피 대조: {len(results)}건 중 불일치 {len(mismatched)}건 ===")
    for r in mismatched:
        verb = "생겼다는데 tarkov.dev엔 없음" if r["log_state"] == "added" else "없어졌다는데 tarkov.dev엔 아직 있음"
        print(f"  ⚠ {r['station']} L{r['level']} -> {r['product']}: 로그는 {verb}"
              f"  (출처: id={r['source_entry']}, {r['source_date']})")
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
