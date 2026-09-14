#!/usr/bin/env python3
"""
업적 변경사항 요약 도구 — reconcile_*.py와 다른 종류다.

json.tarkov.dev에는 achievements 엔드포인트가 없다(2026-08 기준, regular/achievements 등
4가지 경로 다 404 확인함). 즉 tarkov.dev와 대조할 대상 자체가 없다 — 그래서 이 파일은
"불일치 리포트"가 아니라 "data/changes/ 로그에 쌓인 업적 변경사항을 사람이 읽기 좋게
요약"만 한다. 새로 추가된 업적이 있으면 여기서 바로 보이므로, 예를 들어
"카파 패스 폐지 -> Dawn of a New Era 업적 신설" 같은 걸 원문 diff를 직접 안 읽고도
빠르게 확인할 수 있다.
"""

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import diff_parser as dp

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGES_DIR = REPO_ROOT / "data" / "changes"


def load_log_events():
    entry_files = sorted(
        (p for p in glob.glob(str(CHANGES_DIR / "*.json")) if not p.endswith("index.json")),
        key=lambda p: int(Path(p).stem),
    )
    events = []
    for p in entry_files:
        entry = json.loads(Path(p).read_text(encoding="utf-8"))
        for f in entry.get("files", []):
            if f["name"] != "client/achievement/list/response.json":
                continue
            for change in dp.parse(f["diff_text"]):
                events.append((entry["id"], entry["date"], change))
    return events


def summarize():
    events = load_log_events()
    added, removed, changed = [], [], []
    for entry_id, date, ch in events:
        path = ch.path[1:] if ch.path[:1] == ["data"] else ch.path
        # 업적 목록은 ['elements', 이름] 형태로 한 단계 더 감싸여 있다(아이템/하이드아웃과 다름).
        if path[:1] == ["elements"]:
            path = path[1:]
        if len(path) != 1:
            continue
        name = path[0]
        if ch.kind == "block_added":
            rarity_m = re.search(r'"rarity":\s*"([^"]+)"', ch.block_text or "")
            side_m = re.search(r'"side":\s*"([^"]+)"', ch.block_text or "")
            added.append({
                "name": name,
                "rarity": rarity_m.group(1) if rarity_m else None,
                "side": side_m.group(1) if side_m else None,
                "entry_id": entry_id, "date": date,
            })
        elif ch.kind == "block_removed":
            removed.append({"name": name, "entry_id": entry_id, "date": date})
    return added, removed


def print_report(added, removed):
    print(f"=== 업적 신규 추가: {len(added)}건 ===")
    for a in added:
        tag = " / ".join(x for x in (a["rarity"], a["side"]) if x)
        print(f"  + {a['name']}" + (f"  ({tag})" if tag else "") + f"   [id={a['entry_id']}, {a['date']}]")
    print(f"\n=== 업적 삭제: {len(removed)}건 ===")
    for r in removed:
        print(f"  - {r['name']}   [id={r['entry_id']}, {r['date']}]")
    if not added and not removed:
        print("(수집된 업적 변경사항 없음)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    added, removed = summarize()
    if args.json:
        print(json.dumps({"added": added, "removed": removed}, ensure_ascii=False, indent=2))
    else:
        print_report(added, removed)


if __name__ == "__main__":
    main()
