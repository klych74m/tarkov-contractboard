"""퀘스트 해금 조건을 '위키 우선'으로 맞추는 보정표 생성기.

사용자 방침(2026-09-14): tarkov.dev API는 패치 반영이 느리므로 퀘스트의 해금 순서(선행 퀘스트)와
요구조건(레벨·상인 우호도)은 EFT 위키 현재 판본을 기준으로 맞춘다.

reconcile_quests_wiki.py의 대조 결과(API 값 ↔ 위키 현재값)를 그대로 이용한다. 위키 캐시를 재사용하므로
먼저 `python scripts/reconcile_quests_wiki.py --refresh`로 최신 위키를 받아둔 뒤 실행한다.

규칙
  - level / loyalty: 위키 현재값과 API가 다르면 위키 값으로 교체(위키에 없으면 제거)
  - prereq: 위키 선행 목록으로 교체. 이미 있던 선행은 API의 상태(complete/active/failed)를 유지하고,
    새로 추가하는 선행은 위키에 "Accept"로 적힌 것만 active, 나머지는 complete
  - 자동 적용하지 않고 보고만 하는 경우
      · 위키 선행이 OR 조건(앱 구조로 표현 불가)
      · 위키 선행 퀘스트를 API에서 찾지 못함(ID 불명)
      · 위키에서 조건을 하나도 못 읽었는데 API엔 조건이 있음(파싱 누락 가능성) → --include-empty로만 포함
  - maps: 기존 규칙(API 목표에 지도가 없을 때 위키 지도)

사용법: python scripts/emit_quest_wiki_truth.py [--include-empty] [--js-out 파일] [--json-out 파일]
"""
import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rq", ROOT / "reconcile_quests_wiki.py")
rq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rq)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-empty", action="store_true", help="위키에서 조건을 하나도 못 읽은 퀘스트도 위키대로(조건 제거) 적용")
    ap.add_argument("--js-out", default=str(rq.OUT_DIR / "wiki_truth_overrides.js"))
    ap.add_argument("--json-out", default=str(rq.OUT_DIR / "wiki_truth.json"))
    ap.add_argument("--max-age", type=float, default=48.0, help="위키 캐시 유효 시간(시간)")
    args = ap.parse_args()

    captured = {}
    orig = rq.build_overrides

    def spy(quests, tasks, api_title, canon, en_name, maps_en, trader_name_by_id):
        captured.update(quests=quests, tasks=tasks, api_title=api_title, canon=canon, en_name=en_name)
        return orig(quests, tasks, api_title, canon, en_name, maps_en, trader_name_by_id)
    rq.build_overrides = spy

    api = rq.fetch_api()
    wiki = rq.WikiClient(rq.DEFAULT_SEASON_START, refresh=False, max_age_hours=args.max_age, verbose=False)
    rep = rq.audit(api, wiki, verbose=False)
    tasks, api_title, canon, en_name = captured["tasks"], captured["api_title"], captured["canon"], captured["en_name"]
    maps_by_id = {e["id"]: e["override"].get("maps") for e in rep["overrides"] if e["override"].get("maps")}

    title_to_ids = collections.defaultdict(list)
    for tid in tasks:
        at = api_title(tid)
        if at:
            title_to_ids[canon(at)].append(tid)

    def pick_id(ct):
        ids = title_to_ids.get(ct, [])
        plain = [i for i in ids if "[PVP ZONE]" not in en_name(i)]
        return (plain or ids or [None])[0]

    entries, skipped = [], collections.defaultdict(list)
    stats = collections.Counter()
    for r in rep["quests"]:
        f, qid = r["fields"], r["id"]
        lv, lo, pr = f["level"], f["loyalty"], f["prereq"]
        api_lv, wiki_lv = lv["api"] or 0, lv["wiki_now"] or 0
        api_lo, wiki_lo = lo["api"] or {}, lo["wiki_now"] or {}
        api_pr, wiki_pr = set(pr["api"] or []), set(pr["wiki_now"] or [])
        wiki_empty = not wiki_lv and not wiki_lo and not wiki_pr
        api_gated = bool(api_lv or api_lo or api_pr)
        o, why = {}, []

        if wiki_empty and api_gated and not args.include_empty:
            skipped["wiki_empty"].append({"id": qid, "name": r["name"], "trader": r["trader"], "wiki": r["wiki"],
                                          "api": {"level": api_lv, "loyalty": api_lo, "prereq": sorted(api_pr)}})
            continue

        if api_lv != wiki_lv:
            o["level"] = wiki_lv
            why.append(f"레벨 {api_lv or '-'}→{wiki_lv or '-'}")
            stats["level"] += 1
        if api_lo != wiki_lo:
            o["loyalty"] = wiki_lo
            fmt = lambda d: ",".join(f"{k}{v}" for k, v in sorted(d.items())) or "-"
            why.append(f"우호도 {fmt(api_lo)}→{fmt(wiki_lo)}")
            stats["loyalty"] += 1
        if api_pr != wiki_pr:
            if r["wiki_or_flag"]:
                skipped["or_condition"].append({"id": qid, "name": r["name"], "api": sorted(api_pr), "wiki": sorted(wiki_pr)})
            else:
                accept = set(r["wiki_accept"] or [])
                prereqs, remaining = [], set(wiki_pr)
                for req in tasks[qid].get("taskRequirements") or []:
                    ct = canon(api_title(req["task"]) or en_name(req["task"]))
                    if ct in remaining:
                        status = req.get("status") or ["complete"]
                        prereqs.append([req["task"], status if isinstance(status, list) else [status]])
                        remaining.discard(ct)
                unresolved = []
                for ct in sorted(remaining):
                    tid = pick_id(ct)
                    if tid:
                        prereqs.append([tid, ["active"] if ct in accept else ["complete"]])
                    else:
                        unresolved.append(ct)
                if unresolved:
                    skipped["unresolved_prereq"].append({"id": qid, "name": r["name"], "unresolved": unresolved,
                                                         "api": sorted(api_pr), "wiki": sorted(wiki_pr)})
                else:
                    o["prereqs"] = prereqs
                    why.append(f"선행 {len(api_pr)}개→{len(wiki_pr)}개")
                    stats["prereq"] += 1
        if maps_by_id.get(qid):
            o["maps"] = maps_by_id[qid]
        if o:
            entries.append({"id": qid, "name": r["name"], "trader": r["trader"], "set": o, "why": why})

    entries.sort(key=lambda e: (e["trader"] or "", e["name"], e["id"]))
    lines = []
    for e in entries:
        o, parts = e["set"], []
        if "level" in o:
            parts.append(f"level: {o['level']}")
        if "loyalty" in o:
            parts.append("loyalty: {" + ", ".join(f" {k}: {v}" for k, v in sorted(o["loyalty"].items())) + (" }" if o["loyalty"] else "}"))
        if "prereqs" in o:
            parts.append("prereqs: [" + ", ".join(f"['{i}', {json.dumps(st)}]" for i, st in o["prereqs"]) + "]")
        if "maps" in o:
            parts.append("maps: [" + ", ".join(f"'{m}'" for m in o["maps"]) + "]")
        ko = rq.TRADER_KO.get(e["trader"], e["trader"])
        lines.append(f"  '{e['id']}': {{ {', '.join(parts)} }}, // {ko} · {e['name']} · {' / '.join(e['why']) or '지도'}")

    Path(args.js_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.js_out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(args.json_out).write_text(json.dumps({"generated_at": rep["generated_at"], "stats": stats, "entries": entries,
                                               "skipped": skipped, "no_wiki_page": rep["no_wiki_page"]},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"위키 우선 보정: 퀘스트 {len(entries)}개 (레벨 {stats['level']} · 우호도 {stats['loyalty']} · 선행 {stats['prereq']})")
    for k, v in skipped.items():
        print(f"  자동 적용 제외 — {k}: {len(v)}개")
    print(f"  위키 문서 없음(API 유지): {len(rep['no_wiki_page'])}개")
    print(f"JS: {args.js_out}\nJSON: {args.json_out}")


if __name__ == "__main__":
    main()
