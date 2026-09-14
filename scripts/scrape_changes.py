#!/usr/bin/env python3
"""
tarkov-changes.com 의 "Silent Changes" 변경 로그를 스크래핑해서
data/changes/ 아래에 패치 단위로 누적 저장하는 스크립트.

기준점(BASELINE_ID)
--------------------
Season 1 "KORD BREACH"(1.1.0.0.46608, 2026-08-03) 이전 변경 로그는 이 프로젝트와
무관하므로 수집하지 않는다. /list 페이지에서 해당 버전의 첫 항목이 id=1151로
확인되어(2026-08-04 기준) 이 값을 하한선으로 고정했다. 이후 tarkov-changes.com이
글머리를 재정렬하지 않는 한 이 값은 바뀌지 않는다.

저장 구조
---------
data/changes/index.json      경량 목록 — [{id, version, date, change_count, file_count}, ...]
data/changes/{id}.json       항목 하나의 전체 내용(files[].diff_text 포함)
Contract Board는 평소엔 index.json만 fetch하고, 사용자가 특정 패치를 펼칠 때만
그 항목의 {id}.json을 추가로 불러온다. (매 실행마다 통째로 자라는 단일 파일 대신
패치 단위로 파일을 나눠서, 리포/페이지 로드 부담을 항목 단위로 국한시킨다.)

파싱 방식 (2026-08-04 구조 검증 완료)
--------------------------------------
상세 페이지(/view/{id})는 파일별로 다음 구조를 반복한다:
    <h3>파일 경로</h3>
    <div class="diff-block">
        <div class="diff-line[ diff-added|diff-removed]">한 줄</div>
        ...
    </div>
실제 HTML(id=1107, id=1151)을 직접 받아 h3 개수와 diff-block 개수가 항상
1:1로 맞물리는 것을 확인했다(id=1151: 10개 파일 = h3 10개 = diff-block 10개).
따라서 각 h3의 "바로 다음 형제"인 diff-block만 정확히 짝지어 그 안의
diff-line 각각을 한 줄씩 그대로 읽으면 된다.

※ 이 파일의 이전 버전은 문서 전체를 find_all_next()로 훑는 방식이었는데,
  - 같은 내용이 부모 컨테이너 텍스트와 자식 div 텍스트로 두 번 잡히고,
  - "중복 제거"를 문자열 완전 일치로 처리하다 보니 서로 다른 항목이 우연히
    같은 값으로 바뀌면(예: 여러 아이템이 전부 "1 → 0"으로 바뀜) 뒤에 나온
    항목의 값이 통째로 삭제되고,
  - 다음 h3가 없는 마지막 파일 섹션은 문서 끝(사이트 "Back to all changes"
    푸터 링크)까지 텍스트를 계속 주워담는 문제가 있었다.
  지금 방식은 diff-line을 개별 DOM 요소로 정확히 카운트하므로 위 세 가지가
  구조적으로 발생하지 않는다.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://changes.tarkov-changes.com"
LIST_URL = f"{BASE}/list"
DETAIL_URL = f"{BASE}/view/{{id}}"

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "changes"
INDEX_PATH = DATA_DIR / "index.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ContractBoardBot/1.0)"}
REQUEST_DELAY_SEC = 1.0  # 사이트에 과도한 요청 방지용 딜레이

BASELINE_ID = 1151  # Season 1 KORD BREACH(1.1.0.0.46608)의 첫 변경 로그 항목 id

LIST_ITEM_RE = re.compile(
    r"(?P<version>[\d.]+)\s*-\s*(?P<date>[A-Za-z]+,\s*\d{2}\s+[A-Za-z]+\s+\d{4}\s*-\s*[\d:APM\s]+[A-Z]{2,4})"
)
CHANGE_COUNT_RE = re.compile(r"(\d+)\s*change\(s\) detected")


def fetch(url: str) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp


def parse_list_page(html: str):
    """/list 페이지에서 (id, version, date, change_count) 목록을 뽑는다."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for a in soup.find_all("a", href=re.compile(r"/view/\d+")):
        m = re.search(r"/view/(\d+)", a["href"])
        if not m:
            continue
        entry_id = int(m.group(1))
        text = a.get_text(" ", strip=True)
        vm = LIST_ITEM_RE.search(text)
        version = vm.group("version") if vm else None
        date = vm.group("date").strip() if vm else None

        change_count = None
        nxt = a.find_next(string=CHANGE_COUNT_RE)
        if nxt:
            cm = CHANGE_COUNT_RE.search(str(nxt))
            if cm:
                change_count = int(cm.group(1))

        entries.append(
            {"id": entry_id, "version": version, "date": date, "change_count": change_count}
        )

    dedup = {}
    for e in entries:
        dedup[e["id"]] = e
    return list(dedup.values())


def is_login_gated(resp: requests.Response) -> bool:
    """/view/{id} 요청이 /list 로 리다이렉트되면(=최신 항목, 로그인 필요) True."""
    final_path = resp.url.split("?")[0].rstrip("/")
    return final_path.endswith("/list")


def parse_detail_page(html: str, entry_id: int, fallback_version, fallback_date):
    """/view/{id} 상세 페이지에서 파일별 diff 블록을 뽑는다.

    각 파일은 <h3>경로</h3> 바로 뒤에 <div class="diff-block"> 형제가 오고,
    그 안에 <div class="diff-line">줄 내용</div>이 한 줄씩 들어있다.
    """
    soup = BeautifulSoup(html, "html.parser")

    version = fallback_version
    date = fallback_date
    header_text = soup.get_text("\n", strip=True)
    vm = re.search(r"Game Version[:\s]*([\d.]+)", header_text)
    if vm:
        version = vm.group(1)
    dm = re.search(r"Dated:\s*([A-Za-z]+,\s*\d{2}\s+[A-Za-z]+\s+\d{4}\s*-\s*[\d:APM\s]+[A-Z]{2,4})", header_text)
    if dm:
        date = dm.group(1).strip()

    files = []
    for h3 in soup.find_all("h3"):
        diff_block = h3.find_next_sibling("div", class_="diff-block")
        if diff_block is None:
            continue
        name = h3.get_text(strip=True)
        lines = [
            line.get_text()
            for line in diff_block.find_all("div", class_="diff-line", recursive=False)
        ]
        files.append({"name": name, "diff_text": "\n".join(lines)})

    if not files:
        # 사이트 구조가 바뀌어 위 방식으로 못 찾은 경우 — 원문 전체를 저장해두고
        # 수동으로 확인할 수 있게 폴백한다.
        files.append({"name": "(파싱 실패 - 원문 통째 저장)", "diff_text": header_text})

    return {
        "id": entry_id,
        "version": version,
        "date": date,
        "files": files,
        "source_url": DETAIL_URL.format(id=entry_id),
    }


def load_index():
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return []


def save_index(index_entries):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index_sorted = sorted(index_entries, key=lambda e: e["id"])
    INDEX_PATH.write_text(
        json.dumps(index_sorted, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_entry(entry):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry_path = DATA_DIR / f"{entry['id']}.json"
    entry_path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="파일에 저장하지 않고 새로 찾은 항목만 콘솔에 출력"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="이번 실행에서 새로 가져올 최대 항목 수 (테스트용)"
    )
    args = parser.parse_args()

    index = load_index()
    existing_ids = {e["id"] for e in index}

    list_resp = fetch(LIST_URL)
    list_entries = parse_list_page(list_resp.text)

    new_ids = sorted(
        e["id"] for e in list_entries
        if e["id"] not in existing_ids and e["id"] >= BASELINE_ID
    )
    if args.limit:
        new_ids = new_ids[: args.limit]

    if not new_ids:
        print("새로운 항목 없음.")
        return

    print(f"새로 발견된 항목: {new_ids}")

    list_lookup = {e["id"]: e for e in list_entries}
    fetched = []
    skipped_login_gated = []

    for entry_id in new_ids:
        detail_resp = fetch(DETAIL_URL.format(id=entry_id))
        if is_login_gated(detail_resp):
            skipped_login_gated.append(entry_id)
            print(f"  id={entry_id}: 로그인 필요(리다이렉트) -> 다음 실행에서 재시도")
            time.sleep(REQUEST_DELAY_SEC)
            continue

        base_info = list_lookup.get(entry_id, {})
        parsed = parse_detail_page(
            detail_resp.text, entry_id,
            base_info.get("version"), base_info.get("date"),
        )
        parsed["change_count"] = base_info.get("change_count")
        fetched.append(parsed)
        print(f"  id={entry_id}: OK ({len(parsed['files'])}개 파일)")
        time.sleep(REQUEST_DELAY_SEC)

    if args.dry_run:
        print(json.dumps(fetched, ensure_ascii=False, indent=2))
        print(f"\n(dry-run) 저장 안 함. 로그인 게이트로 건너뛴 항목: {skipped_login_gated}")
        return

    for entry in fetched:
        save_entry(entry)
        index.append({
            "id": entry["id"],
            "version": entry["version"],
            "date": entry["date"],
            "change_count": entry["change_count"],
            "file_count": len(entry["files"]),
        })
    save_index(index)

    print(f"data/changes/ 업데이트 완료. 이번에 추가된 항목 {len(fetched)}개.")
    if skipped_login_gated:
        print(f"로그인 게이트로 건너뛴 항목(다음 실행 때 재시도): {skipped_login_gated}")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"요청 실패: {e}", file=sys.stderr)
        sys.exit(1)
