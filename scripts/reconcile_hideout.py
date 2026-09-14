#!/usr/bin/env python3
"""
하이드아웃 건설 조건에 대해 tarkov.dev(현재 라이브 값)와 data/changes/(tarkov-changes.com
누적 diff 로그)를 구조적으로 대조해서 불일치 리포트를 만든다.

배경: 2026-08 KORD BREACH 패치에서 하이드아웃 건설 조건이 대규모로 바뀌었는데,
tarkov.dev API 파이프라인이 한동안 이를 반영하지 못했던 사례가 실제로 있었다(직접 확인함).
이 스크립트는 그런 상황을 매번 손으로 diff 텍스트를 읽지 않고 자동으로 잡아내기 위한 것.

비교하는 필드 (현재 범위 — diff_parser.py가 뽑아내는 이벤트 중 의미가 명확한 것만):
  1. constructionTime   — 레벨별 건설 시간(초)
  2. TraderLoyalty 요구 제거 — 상인 우호도 게이팅이 삭제된 레벨

주의: requiredLevel(개별 requirement 안의 레벨 조건)과 isSpawnedInSession(FIR 요구)은
diff 로그의 배열 인덱스가 tarkov.dev의 itemRequirements 배열 순서와 1:1로 대응한다는
보장이 없어서(양쪽이 서로 다른 파이프라인이 만든 별개의 배열이라 순서가 안 맞을 수 있음)
이번 버전에서는 대상에서 뺐다. 항목 매칭 방법을 찾으면 확장할 것.

사용법:
    python scripts/reconcile_hideout.py            # 사람이 읽는 리포트 출력
    python scripts/reconcile_hideout.py --json      # 리포트를 JSON으로 출력(다른 도구 연계용)
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

STATION_KEY_RE = re.compile(r"^(.*) \(\d+\)$")  # "Heating (5)" -> "Heating"

# tarkov-changes.com(원본 클라이언트 값)과 tarkov.dev 스키마가 같은 시설을 다른 이름으로
# 부르는 경우 — 실제로 대조해서 확인된 것만 등록한다.
STATION_NAME_ALIASES = {
    "Med Station": "Medstation",
    "Weapon Stand": "Weapon Rack",
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
    """data/changes/*.json 중 client/hideout/areas/response.json 파일의 diff를
    id(=시간) 순서대로 파싱해서 이어붙인다. index.json은 제외."""
    entry_files = sorted(
        (p for p in glob.glob(str(CHANGES_DIR / "*.json")) if not p.endswith("index.json")),
        key=lambda p: int(Path(p).stem),
    )
    all_events = []  # [(entry_id, entry_date, Change), ...]
    for p in entry_files:
        entry = json.loads(Path(p).read_text(encoding="utf-8"))
        for f in entry.get("files", []):
            if f["name"] != "client/hideout/areas/response.json":
                continue
            for change in dp.parse(f["diff_text"]):
                all_events.append((entry["id"], entry["date"], change))
    return all_events


def build_latest_truth(events):
    """같은 (station, stage, field) 경로에 여러 패치가 겹쳐 있으면 가장 최근(entry id가
    가장 큰) 것만 '지금의 진짜 값'으로 남긴다."""
    construction_time = {}  # (station, stage) -> {"new": float, "entry_id": int, "date": str}
    trader_removed = {}     # (station, stage) -> [{"trader": str, "loyaltyLevel": int, "entry_id": int, "date": str}]

    for entry_id, date, ch in events:
        # diff는 항상 ['data'][station]... 형태로 시작한다 — 맨 앞 'data'를 떼어낸다.
        path = ch.path[1:] if ch.path[:1] == ["data"] else ch.path
        if len(path) < 2:
            continue
        station_raw = path[0]
        m = STATION_KEY_RE.match(station_raw)
        station = m.group(1) if m else station_raw
        station = STATION_NAME_ALIASES.get(station, station)

        if ch.kind == "scalar" and "constructionTime" in path:
            # path: [station, "stages", stage_idx, "constructionTime"]
            try:
                stage_idx = int(path[2])
            except (IndexError, ValueError):
                continue
            key = (station, stage_idx)
            new_val = dp.parse_number(ch.new)
            if new_val is None:
                continue
            prev = construction_time.get(key)
            if prev is None or entry_id >= prev["entry_id"]:
                construction_time[key] = {"new": new_val, "entry_id": entry_id, "date": date}

        elif ch.kind == "block_removed" and "TraderLoyalty" in (ch.block_text or ""):
            try:
                stage_idx = int(path[2])
            except (IndexError, ValueError):
                continue
            trader_m = re.search(r'"traderId":\s*"([^"]+)"', ch.block_text)
            level_m = re.search(r'"loyaltyLevel":\s*(\d+)', ch.block_text)
            if not trader_m or not level_m:
                continue
            key = (station, stage_idx)
            trader_removed.setdefault(key, []).append({
                "trader": trader_m.group(1),
                "loyaltyLevel": int(level_m.group(1)),
                "entry_id": entry_id,
                "date": date,
            })

    return construction_time, trader_removed


def fetch_live(mode="regular"):
    hideout = _get(f"{mode}/hideout")
    hideout_en = _get(f"{mode}/hideout_en")
    traders = _get(f"{mode}/traders")

    stations_by_name = {}
    for s in hideout.values():
        if not s or not s.get("id"):
            continue
        name = hideout_en.get(s.get("name"), s.get("normalizedName"))
        stations_by_name[name] = s

    trader_name_by_id = {}
    for t in traders.values():
        if t and t.get("id"):
            trader_name_by_id[t["id"]] = t.get("normalizedName") or t.get("name")

    return stations_by_name, trader_name_by_id


# 로그의 상인 표기("Mechanic","Prapor"...)는 tarkov.dev normalizedName과 대소문자만 다름
def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def reconcile(mode="regular"):
    events = load_log_events()
    construction_time, trader_removed = build_latest_truth(events)
    stations_by_name, trader_name_by_id = fetch_live(mode)

    report = {"constructionTime": [], "traderLoyaltyRemoved": [], "unmatched_stations": []}

    for (station, stage_idx), info in construction_time.items():
        live = stations_by_name.get(station)
        if not live:
            report["unmatched_stations"].append(station)
            continue
        live_level = next((l for l in live["levels"] if l["level"] == stage_idx), None)
        if live_level is None:
            continue
        live_ct = live_level.get("constructionTime")
        match = (live_ct is not None and abs(live_ct - info["new"]) < 0.5)
        report["constructionTime"].append({
            "station": station, "stage": stage_idx,
            "log_value": info["new"], "dev_value": live_ct,
            "match": match, "source_entry": info["entry_id"], "source_date": info["date"],
        })

    for (station, stage_idx), removals in trader_removed.items():
        live = stations_by_name.get(station)
        if not live:
            report["unmatched_stations"].append(station)
            continue
        live_level = next((l for l in live["levels"] if l["level"] == stage_idx), None)
        live_trader_reqs = (live_level or {}).get("traderRequirements", [])
        live_trader_names = {_norm(trader_name_by_id.get(r.get("trader"))) for r in live_trader_reqs}

        for rm in removals:
            still_present = _norm(rm["trader"]) in live_trader_names
            report["traderLoyaltyRemoved"].append({
                "station": station, "stage": stage_idx,
                "trader": rm["trader"], "loyaltyLevel": rm["loyaltyLevel"],
                "match": not still_present,  # match = dev도 이미 제거함
                "source_entry": rm["entry_id"], "source_date": rm["date"],
            })

    report["unmatched_stations"] = sorted(set(report["unmatched_stations"]))
    return report


def print_report(report):
    ct = report["constructionTime"]
    tr = report["traderLoyaltyRemoved"]

    mismatched_ct = [r for r in ct if not r["match"]]
    mismatched_tr = [r for r in tr if not r["match"]]

    print(f"=== 건설 시간(constructionTime) 대조: {len(ct)}건 중 불일치 {len(mismatched_ct)}건 ===")
    for r in mismatched_ct:
        print(f"  ⚠ {r['station']} L{r['stage']}: 로그(진짜값)={r['log_value']:.0f}초  vs  tarkov.dev={r['dev_value']}"
              f"  (출처: id={r['source_entry']}, {r['source_date']})")
    if not mismatched_ct:
        print("  ✅ 전부 일치 — tarkov.dev가 이미 따라잡음")

    print(f"\n=== 상인 우호도 요구 삭제 대조: {len(tr)}건 중 불일치 {len(mismatched_tr)}건 ===")
    for r in mismatched_tr:
        print(f"  ⚠ {r['station']} L{r['stage']}: 로그는 '{r['trader']} LL{r['loyaltyLevel']}' 요구가 삭제됐다고 함,"
              f" 그런데 tarkov.dev엔 아직 남아있음  (출처: id={r['source_entry']}, {r['source_date']})")
    if not mismatched_tr:
        print("  ✅ 전부 일치 — tarkov.dev가 이미 따라잡음")

    if report["unmatched_stations"]:
        print(f"\n⚠ tarkov.dev에서 이름 매칭 실패한 시설: {report['unmatched_stations']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="리포트를 JSON으로 출력")
    parser.add_argument("--mode", choices=["regular", "pve"], default="regular", help="대조할 tarkov.dev 모드")
    args = parser.parse_args()

    report = reconcile(args.mode)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
