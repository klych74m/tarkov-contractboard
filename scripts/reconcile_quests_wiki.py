#!/usr/bin/env python3
"""
퀘스트 해금 조건(플레이어 레벨 / 상인 우호도 / 선행 퀘스트 / 지역)에 대해
tarkov.dev JSON API와 EFT Fandom 위키를 대조해서 "어느 쪽이 시즌 변경을 반영했는가"를
필드 단위로 판정하는 감사(audit) 스크립트.

배경: Season 1(1.1 패치, 2026-08-03 시작)에서 퀘스트 해금 조건이 "플레이어 레벨 + 선행 퀘스트"
중심에서 대부분 "상인 우호도(LL)" 중심으로 바뀌었다. 그런데 두 출처 모두 고르게 최신이 아니다.
  - tarkov.dev는 옛 조건을 지우기만 하고 새 LL 조건을 안 넣은 퀘스트가 있다.
  - 위키는 시즌 이후 한 번도 내용이 갱신되지 않은 문서가 많다.
tarkov-changes.com(data/changes/)은 quests/tasks 파일을 추적하지 않으므로 다른 reconcile_*.py처럼
로그 기반 대조가 불가능하다. 대신 "위키의 시즌 직전 리비전"을 기준점으로 삼아, API와 위키 중
어느 쪽이 기준점에서 움직였는지를 보고 판정한다.

방법:
  1. json.tarkov.dev에서 regular/tasks, tasks_en, traders, maps_en, pvp-season/tasks를 받는다.
  2. 각 task의 wikiLink → 위키 문서 제목으로 매핑한다.
  3. 위키 MediaWiki API(api.php — 일반 HTML은 Cloudflare에 막힘)로
       - 현재 wikitext (50개씩 묶어서)
       - 시즌 시작 직전 리비전 wikitext (문서당 1회 요청, rvstart=<시즌시작>&rvdir=older)
     를 받는다. data/quest_audit/cache/에 캐시한다.
  4. 위키 문서(현재/시즌 전 각각)의 infobox(given by, previous, location)와 ==Requirements== 섹션을
     파싱해서 {level, loyalty{trader: LL}, prereq(set), locations(set)}을 만든다.
  5. 필드별로 API / wiki_pre / wiki_now를 비교해 판정한다.
       API == wiki_now                         → OK
       시즌 전 리비전이 없음(시즌 후 새 문서)   → NEW_PAGE_DIFF
       위키만 바뀜(pre≠now), API == pre         → USE_WIKI  (API가 낡음 → 위키로 교정)
       API만 바뀜(API≠pre), 위키 그대로          → KEEP_API  (위키가 낡음 → API 유지)
       둘 다 바뀌었는데 결과가 다름             → CONFLICT  (사람이 직접 판단)
       둘 다 안 바뀌었는데 원래부터 다름         → LEGACY
     추가로 "API에는 게이팅이 전혀 없는데(레벨>1·LL>1·선행 모두 없음) 위키에는 레벨 조건이 있는"
     퀘스트를 따로 뽑는다 — 앱에서 레벨 1부터 열린 것처럼 보이는 퀘스트들이다.

주의:
  - 거의 모든 퀘스트 문서에 2026-08-15 수정 이력이 있는데, 이는 관리자의 문서 보호 설정 변경일 뿐
    내용 편집이 아니다. "마지막 수정일"은 신선도 신호로 절대 쓰지 않는다 — 오직 시즌 전 리비전과
    현재 리비전의 파싱 결과만 비교한다.
  - 레벨 ≤1, LL ≤1은 "조건 없음"으로 취급한다.
  - 선행 퀘스트는 "퀘스트 문서로 해석되는 링크"만 센다. 이름이 바뀐 문서는 위키 API의
    redirects=1로 해석한다.

캐시 정책:
  - 시즌 전 리비전은 과거 이력이라 변하지 않으므로 시즌 시작일별로 영구 캐시한다.
  - 현재 wikitext는 --max-age 시간(기본 6시간)이 지나면 자동으로 다시 받는다.
  - --refresh를 주면 둘 다 새로 받는다.

사용법:
    python scripts/reconcile_quests_wiki.py                    # 사람이 읽는 리포트 출력
    python scripts/reconcile_quests_wiki.py --emit-overrides   # index.html QUEST_UNLOCK_OVERRIDES용 JS 줄만 출력
    python scripts/reconcile_quests_wiki.py --json             # 리포트를 JSON으로 출력(다른 도구 연계용)
    python scripts/reconcile_quests_wiki.py --refresh          # 위키 캐시 무시하고 전부 다시 받기
    python scripts/reconcile_quests_wiki.py --season-start 2026-08-03T00:00:00Z
결과 JSON은 항상 data/quest_audit/latest.json에도 저장된다.
"""

import argparse
import collections
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "quest_audit"
CACHE_DIR = OUT_DIR / "cache"
JSON_API_BASE = "https://json.tarkov.dev"
WIKI_API = "https://escapefromtarkov.fandom.com/api.php"
USER_AGENT = "ContractBoardQuestAudit/1.0 (+https://github.com/IroncladSkin)"
DEFAULT_SEASON_START = "2026-08-03T00:00:00Z"
WIKI_DELAY = 0.15      # 위키 요청 사이 대기(초) — 예의상
WIKI_BATCH = 50        # MediaWiki API가 한 번에 받는 titles 최대 개수

FIELDS = ["level", "loyalty", "prereq", "locations"]
DECISIONS = ["OK", "KEEP_API", "USE_WIKI", "CONFLICT", "NEW_PAGE_DIFF", "LEGACY"]

TRADER_KO = {
    "prapor": "프라퍼", "therapist": "테라피스트", "fence": "펜스", "skier": "스키어",
    "peacekeeper": "피스키퍼", "mechanic": "메카닉", "ragman": "래그맨", "jaeger": "예거",
    "lightkeeper": "등대지기", "ref": "레프", "btr-driver": "BTR 운전수",
}
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
IGNORED_LOCATIONS = {"any", "arena"}


# ─────────────────────────── tarkov.dev ───────────────────────────

def _get(path):
    # 큰 응답에서 이 환경의 brotli 디코더가 간헐적으로 깨지는 문제가 있어,
    # br 대신 gzip/deflate만 받도록 명시한다. (reconcile_hideout.py와 동일)
    r = requests.get(
        f"{JSON_API_BASE}/{path}", timeout=120,
        headers={"Accept": "application/json", "Accept-Encoding": "gzip, deflate"},
    )
    r.raise_for_status()
    return r.json()["data"]


def fetch_api():
    tasks = _get("regular/tasks")
    tasks = tasks.get("tasks", tasks)  # {"tasks": {id: task}} 형태
    season = _get("pvp-season/tasks")
    season = season.get("tasks", season)
    return {
        "tasks": tasks,
        "season_tasks": season,
        "tasks_en": _get("regular/tasks_en"),   # "<taskId> name" → 영문명 (task.name은 로케일 키)
        "traders": _get("regular/traders"),     # 상인 ID → 상인 객체
        "maps_en": _get("regular/maps_en"),     # "<mapId> Name" → 영문 맵 이름
    }


def wiki_title_from_link(link):
    """task.wikiLink → 위키 문서 제목. 일부 링크는 끝에 공백/개행이 붙어 있다."""
    link = (link or "").strip()
    if "/wiki/" not in link:
        return None
    title = urllib.parse.unquote(link.split("/wiki/", 1)[1]).replace("_", " ")
    title = title.split("#", 1)[0]
    return re.sub(r"\s+", " ", title).strip() or None


# ─────────────────────────── 위키 (MediaWiki API) ───────────────────────────

class WikiClient:
    def __init__(self, season_start, refresh=False, max_age_hours=6.0, verbose=True):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.season_start = season_start
        self.refresh = refresh
        self.max_age = max_age_hours * 3600
        self.verbose = verbose
        self.errors = []
        self.request_count = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tag = re.sub(r"[^0-9]", "", season_start)[:8]
        self.current_path = CACHE_DIR / "wiki_current.json"
        self.pre_path = CACHE_DIR / f"wiki_preseason_{tag}.json"
        self.redirect_path = CACHE_DIR / "wiki_redirects.json"

    def _log(self, msg):
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    def _query(self, params, retries=3):
        params = dict(params, action="query", format="json")
        for attempt in range(retries):
            time.sleep(WIKI_DELAY)
            self.request_count += 1
            try:
                r = self.s.get(WIKI_API, params=params, timeout=90)
                r.raise_for_status()
                return r.json().get("query", {})
            except (requests.RequestException, ValueError) as e:
                if attempt == retries - 1:
                    raise
                self._log(f"  위키 요청 실패, 재시도 {attempt + 1}: {e}")
                time.sleep(2 * (attempt + 1))

    @staticmethod
    def _load(path):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    @staticmethod
    def _save(path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    # 현재 리비전 ──────────────────────────────────────────
    def fetch_current(self, titles):
        """titles(요청 제목) → {"pages": {최종제목: {timestamp, text}}, "resolved": {요청제목: 최종제목},
        "missing": [...]}. 캐시가 --max-age 이내면 없는 제목만 추가로 받는다."""
        cache = None if self.refresh else self._load(self.current_path)
        if cache and time.time() - cache.get("fetched_at", 0) > self.max_age:
            self._log(f"현재 위키 캐시가 {self.max_age / 3600:.0f}시간보다 오래돼 다시 받는다.")
            cache = None
        cache = cache or {"fetched_at": time.time(), "pages": {}, "resolved": {}, "missing": []}
        todo = sorted(t for t in set(titles) if t not in cache["resolved"])
        if todo:
            self._log(f"현재 위키 wikitext 받는 중: {len(todo)}개 제목 ({WIKI_BATCH}개씩)")
        for i in range(0, len(todo), WIKI_BATCH):
            batch = todo[i:i + WIKI_BATCH]
            q = self._query({
                "prop": "revisions", "titles": "|".join(batch),
                "rvprop": "content|timestamp", "rvslots": "main", "redirects": 1,
            })
            norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
            red = {r["from"]: r["to"] for r in q.get("redirects", [])}
            for p in q.get("pages", {}).values():
                if "missing" in p or "revisions" not in p:
                    continue
                rev = p["revisions"][0]
                cache["pages"][p["title"]] = {"timestamp": rev["timestamp"], "text": rev["slots"]["main"]["*"]}
            for t in batch:
                x = norm.get(t, t)
                x = red.get(x, x)
                cache["resolved"][t] = x
                if x not in cache["pages"] and t not in cache["missing"]:
                    cache["missing"].append(t)
        if todo:
            self._save(self.current_path, cache)
        return cache

    # 시즌 전 리비전 ──────────────────────────────────────
    def fetch_preseason(self, titles):
        """최종제목 → 시즌 시작 직전 리비전 {timestamp, text}, 그 시점에 문서가 없었으면 None.
        과거 이력은 변하지 않으므로 --refresh가 아니면 영구 캐시한다."""
        cache = None if self.refresh else self._load(self.pre_path)
        cache = cache or {"season_start": self.season_start, "pages": {}}
        todo = sorted(t for t in set(titles) if t not in cache["pages"])
        if todo:
            self._log(f"시즌 전({self.season_start}) 리비전 받는 중: {len(todo)}개 문서 (문서당 1회 요청)")
        for n, t in enumerate(todo, 1):
            try:
                q = self._query({
                    "prop": "revisions", "titles": t, "rvprop": "content|timestamp", "rvslots": "main",
                    "rvlimit": 1, "rvstart": self.season_start, "rvdir": "older",
                })
            except (requests.RequestException, ValueError) as e:
                self.errors.append({"title": t, "error": str(e)})
                continue  # 캐시에 안 넣음 → 다음 실행 때 다시 시도
            page = next(iter(q.get("pages", {}).values()), {})
            revs = page.get("revisions")
            cache["pages"][t] = (
                {"timestamp": revs[0]["timestamp"], "text": revs[0]["slots"]["main"]["*"]} if revs else None
            )
            if n % 50 == 0:
                self._log(f"  {n}/{len(todo)}")
                self._save(self.pre_path, cache)  # 중간 저장 — 중단돼도 이어받기 가능
        if todo:
            self._save(self.pre_path, cache)
        return cache["pages"]

    # 링크 제목 → 리다이렉트 해석 ──────────────────────────
    def resolve_titles(self, titles):
        cache = (None if self.refresh else self._load(self.redirect_path)) or {}
        todo = sorted(t for t in set(titles) if t not in cache)
        if todo:
            self._log(f"퀘스트 목록에 없는 링크 제목 {len(todo)}개를 리다이렉트 해석 중")
        for i in range(0, len(todo), WIKI_BATCH):
            batch = todo[i:i + WIKI_BATCH]
            q = self._query({"titles": "|".join(batch), "redirects": 1})
            norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
            red = {r["from"]: r["to"] for r in q.get("redirects", [])}
            for t in batch:
                x = norm.get(t, t)
                cache[t] = red.get(x, x)
        if todo:
            self._save(self.redirect_path, cache)
        return cache


# ─────────────────────────── 위키 파싱 ───────────────────────────

def nt(s):
    """제목 비교용 정규화 (소문자, 공백 정리)."""
    s = urllib.parse.unquote(s or "").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def links(s):
    out = []
    for m in re.findall(r"\[\[([^\]]+)\]\]", s or ""):
        t = m.split("|")[0].split("#")[0].strip().lstrip(":")
        if t:
            out.append(t)
    return out


def section(text, name):
    m = re.search(r"==\s*" + name + r"\s*==(.*?)(?=\n==[^=]|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def infobox_field(text, field):
    m = re.search(r"\|\s*" + re.escape(field) + r"\s*=([^\n]*)", text)
    return m.group(1).strip() if m else ""


def trader_key(name):
    n = re.sub(r"[^a-z ]", "", name.strip().lower()).strip()
    return "btr-driver" if n in ("btr driver", "btr") else n.replace(" ", "-")


def map_norm(n):
    n = n.lower().replace("night ", "").replace(" 21+", "").replace(" (dark)", "").replace(" tutorial", "")
    return n.strip()


def lnum(s):
    return int(s) if s.isdigit() else ROMAN.get(s.upper(), 0)


LEVEL_RE = re.compile(r"must be level\s+(\d+)", re.I)
LL_WITH_RE = re.compile(r"loyalty level\s+(\d+|[IV]+)\s+with\s+(.*)", re.I)       # Must reach / Reach ... with [[A]], [[B]] and [[C]]
LL_OBTAIN_RE = re.compile(r"obtain level\s+(\d+|[IV]+)\s+loyalty with\s+(.*)", re.I)
LL_GIVER_RE = re.compile(r"must be loyalty level\s+(\d+|[IV]+)", re.I)             # 상인 = 퀘스트 제공자
OR_RE = re.compile(r"(^|>|\s)or(\s|<|$)", re.I)


class WikiParser:
    def __init__(self, canon, is_quest):
        self.canon = canon
        self.is_quest = is_quest

    def _add_quests(self, target, titles):
        for q in titles:
            if self.is_quest(q):
                target.add(self.canon(q))

    def parse(self, text):
        """위키 문서 → {level, loyalty{trader: LL}, prereq(set), accept(set), or_flag, locations(set)}.
        prereq는 완료 조건과 수락(accept) 조건을 합친 집합이다(API 쪽도 status 구분 없이 합친다)."""
        res = {"level": 0, "loyalty": {}, "prereq": set(), "accept": set(), "or_flag": False, "locations": set()}
        giver = links(infobox_field(text, "given by"))
        giver_key = trader_key(giver[0]) if giver else None

        # infobox previous: <br/>로 구분, "or"가 있으면 OR 조건, "Accept [[X]]"는 수락만 하면 되는 조건
        prev_field = infobox_field(text, "previous")
        res["or_flag"] = bool(OR_RE.search(prev_field))
        for part in re.split(r"<br\s*/?>", prev_field, flags=re.I):
            is_accept = bool(re.search(r"\baccept\b", part, re.I))
            for q in links(part):
                if self.is_quest(q):
                    res["prereq"].add(self.canon(q))
                    if is_accept:
                        res["accept"].add(self.canon(q))

        in_list = False
        for line in section(text, "Requirements").splitlines():
            ln = line.strip()
            if not ln:
                continue
            m = LEVEL_RE.search(ln)
            if m:
                res["level"] = max(res["level"], int(m.group(1)))
            mm = LL_WITH_RE.search(ln) or LL_OBTAIN_RE.search(ln)
            m3 = LL_GIVER_RE.search(ln)
            if mm:
                for n in (links(mm.group(2)) or [mm.group(2)]):
                    res["loyalty"][trader_key(n)] = lnum(mm.group(1))
            elif m3 and giver_key:
                res["loyalty"][giver_key] = lnum(m3.group(1))
            if re.search(r"after completion of|must accept", ln, re.I):
                qs = links(ln)
                self._add_quests(res["prereq"], qs)
                if re.search(r"must accept", ln, re.I):
                    self._add_quests(res["accept"], qs)
            if re.search(r"complete the quests", ln, re.I):
                in_list = True
                continue
            if in_list and ln.startswith("**"):
                self._add_quests(res["prereq"], links(ln))
            elif not ln.startswith("**"):
                in_list = False

        for loc in links(infobox_field(text, "location")):
            m = map_norm(loc)
            if m not in IGNORED_LOCATIONS:
                res["locations"].add(m)
        if res["level"] <= 1:
            res["level"] = 0
        res["loyalty"] = {k: v for k, v in res["loyalty"].items() if v > 1}  # LL1은 사실상 조건 없음
        return res


# ─────────────────────────── 판정 ───────────────────────────

def decide(api_v, pre_v, cur_v, new_page):
    if api_v == cur_v:
        return "OK"
    if new_page:
        return "NEW_PAGE_DIFF"
    w_changed = pre_v != cur_v
    a_changed = api_v != pre_v
    if w_changed and not a_changed:
        return "USE_WIKI"   # 위키만 시즌 반영, API는 시즌 전 값 그대로
    if a_changed and not w_changed:
        return "KEEP_API"   # API만 시즌 반영, 위키는 시즌 전 값 그대로
    if w_changed and a_changed:
        return "CONFLICT"   # 둘 다 바뀌었는데 결과가 다름
    return "LEGACY"         # 둘 다 시즌 전과 같고 원래부터 달랐음


def _jsonable(v):
    if isinstance(v, set):
        return sorted(v)
    return v


def audit(api, wiki, verbose=True):
    tasks, tasks_en, maps_en = api["tasks"], api["tasks_en"], api["maps_en"]
    trader_name_by_id = {tid: t.get("normalizedName") for tid, t in api["traders"].items() if t}

    def en_name(tid):
        return (tasks_en.get(f"{tid} name") or tid).strip()

    # 1) task → 위키 제목 → 현재 문서
    req_title = {tid: wiki_title_from_link(t.get("wikiLink")) for tid, t in tasks.items()}
    cur = wiki.fetch_current([x for x in req_title.values() if x])
    cur_pages, resolved = cur["pages"], cur["resolved"]

    def api_title(tid):
        rt = req_title.get(tid)
        return resolved.get(rt, rt) if rt else None

    quest_titles = sorted({api_title(tid) for tid in tasks if api_title(tid) in cur_pages})

    # 2) 시즌 전 리비전
    pre_pages = wiki.fetch_preseason(quest_titles)

    # 3) 링크 제목 정규화: 알려진 퀘스트 문서 + 리다이렉트
    known = {nt(t) for t in quest_titles}
    redirect_norm = {nt(k): nt(v) for k, v in resolved.items()}
    unknown = set()
    for src in (cur_pages, pre_pages):
        for title in quest_titles:
            p = src.get(title)
            if not p:
                continue
            for ln in links(infobox_field(p["text"], "previous")) + links(section(p["text"], "Requirements")):
                if nt(ln) not in known and nt(ln) not in redirect_norm:
                    unknown.add(ln)
    for k, v in wiki.resolve_titles(unknown).items():
        redirect_norm.setdefault(nt(k), nt(v))

    def canon(title):
        x = nt(title)
        return redirect_norm.get(x, x)

    parser = WikiParser(canon, lambda t: canon(t) in known)

    def api_fields(t):
        lvl = t.get("minPlayerLevel") or 0
        loy = {}
        for r in t.get("traderRequirements") or []:
            if r.get("requirementType") == "level" and (r.get("value") or 0) > 1:
                loy[trader_name_by_id.get(r["trader"], r["trader"])] = r["value"]
        pr = set()
        for r in t.get("taskRequirements") or []:
            title = api_title(r["task"]) if r["task"] in tasks else None
            pr.add(canon(title or en_name(r["task"])))
        locs = set()
        for o in t.get("objectives") or []:
            for m in o.get("maps") or []:
                mm = map_norm(maps_en.get(f"{m} Name") or m)
                if mm not in IGNORED_LOCATIONS:
                    locs.add(mm)
        return {"level": lvl if lvl > 1 else 0, "loyalty": loy, "prereq": pr, "locations": locs}

    # 4) 퀘스트별 판정
    counts = {f: collections.Counter() for f in FIELDS}
    quests, no_wiki, ungated = [], [], []
    parsed = {}
    for tid, t in tasks.items():
        name = en_name(tid)
        trader = trader_name_by_id.get(t.get("trader"))
        title = api_title(tid)
        cp = cur_pages.get(title) if title else None
        if not cp:
            no_wiki.append({"id": tid, "name": name, "trader": trader, "wikiLink": (t.get("wikiLink") or "").strip()})
            continue
        pp = pre_pages.get(title)
        c = parser.parse(cp["text"])
        p = parser.parse(pp["text"]) if pp else None
        a = api_fields(t)
        parsed[tid] = (a, p, c)
        rec = {"id": tid, "name": name, "trader": trader, "wiki": title,
               "in_season_api": tid in api["season_tasks"], "wiki_or_flag": c["or_flag"],
               "wiki_accept": sorted(c["accept"]), "fields": {}}
        for f in FIELDS:
            d = decide(a[f], p[f] if p else None, c[f], p is None)
            counts[f][d] += 1
            rec["fields"][f] = {"decision": d, "api": _jsonable(a[f]), "wiki_now": _jsonable(c[f]),
                                "wiki_pre": _jsonable(p[f]) if p else None}
        quests.append(rec)
        if not a["level"] and not a["loyalty"] and not a["prereq"] and c["level"]:
            ungated.append({"id": tid, "name": name, "trader": trader, "wiki_level": c["level"],
                            "wiki_pre_level": p["level"] if p else None,
                            "level_decision": rec["fields"]["level"]["decision"]})

    overrides = build_overrides(quests, tasks, api_title, canon, en_name, maps_en, trader_name_by_id)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season_start": wiki.season_start,
        "task_count": len(tasks),
        "audited_count": len(quests),
        "counts": {f: {d: counts[f][d] for d in DECISIONS if counts[f][d]} for f in FIELDS},
        "ungated_but_wiki_level": ungated,
        "no_wiki_page": no_wiki,
        "wiki_missing_titles": cur["missing"],
        "preseason_missing": sorted(t for t in quest_titles if pre_pages.get(t) is None),
        "fetch_errors": wiki.errors,
        "overrides": overrides,
        "quests": quests,
    }


# ─────────────────────────── 오버라이드 생성 ───────────────────────────

def build_overrides(quests, tasks, api_title, canon, en_name, maps_en, trader_name_by_id):
    """QUEST_UNLOCK_OVERRIDES용 보정값. 기준:
      - loyalty: USE_WIKI/NEW_PAGE_DIFF이고 위키 LL이 API보다 높은 상인만 추가
      - removeLevel: level이 USE_WIKI이고 위키엔 레벨 조건이 없어짐 → API 레벨 제거
      - removePrereqs/addPrereqs: prereq가 USE_WIKI일 때 차집합
      - maps: API 목표에 지도가 하나도 없는데 위키 location에는 있음"""
    title_to_ids = collections.defaultdict(list)
    for tid in tasks:
        at = api_title(tid)
        if at:
            title_to_ids[canon(at)].append(tid)

    def pick_id(ctitle):
        ids = title_to_ids.get(ctitle, [])
        plain = [i for i in ids if "[PVP ZONE]" not in en_name(i)]
        return (plain or ids or [None])[0]

    proper_map = {}
    for k, v in maps_en.items():
        if k.endswith(" Name"):
            proper_map.setdefault(map_norm(v), v)

    out = []
    for r in quests:
        f, qid = r["fields"], r["id"]
        o = {}
        lv = f["level"]
        if lv["decision"] == "USE_WIKI" and lv["wiki_now"] == 0:
            o["removeLevel"] = lv["api"]
        lo = f["loyalty"]
        if lo["decision"] in ("USE_WIKI", "NEW_PAGE_DIFF"):
            add = {k: v for k, v in lo["wiki_now"].items() if (lo["api"] or {}).get(k, 0) < v}
            if add:
                o["loyalty"] = add
        pr = f["prereq"]
        if pr["decision"] == "USE_WIKI":
            api_set, wiki_set = set(pr["api"]), set(pr["wiki_now"])
            rem = [req["task"] for req in tasks[qid].get("taskRequirements") or []
                   if canon(api_title(req["task"]) or en_name(req["task"])) in api_set - wiki_set]
            add_ids = [pick_id(t) for t in sorted(wiki_set - api_set)]
            if rem:
                o["removePrereqs"] = rem
            if any(add_ids):
                o["addPrereqs"] = [a for a in add_ids if a]
            if None in add_ids:
                o["unresolvedAddPrereqs"] = [t for t in sorted(wiki_set - api_set) if not pick_id(t)]
        loc = f["locations"]
        if loc["wiki_now"] and not loc["api"]:
            o["maps"] = sorted(proper_map.get(m, m.title()) for m in loc["wiki_now"])
        if o:
            out.append({"id": qid, "name": r["name"], "trader": r["trader"], "override": o})
    out.sort(key=lambda x: (x["trader"] or "", x["name"], x["id"]))
    return out


def override_js_lines(overrides):
    lines = []
    for e in overrides:
        o = e["override"]
        parts = []
        if "removeLevel" in o:
            parts.append(f"removeLevel: {o['removeLevel']}")
        if "loyalty" in o:
            parts.append("loyalty: { " + ", ".join(f"'{k}': {v}" for k, v in o["loyalty"].items()) + " }")
        for key in ("removePrereqs", "addPrereqs", "maps"):
            if key in o:
                parts.append(f"{key}: [" + ", ".join(f"'{x}'" for x in o[key]) + "]")
        ko = TRADER_KO.get(e["trader"], e["trader"])
        lines.append(f"  '{e['id']}': {{ {', '.join(parts)} }}, // {ko} · {e['name']}")
    return lines


# ─────────────────────────── 출력 ───────────────────────────

def _fmt(v):
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}:{x}" for k, x in v.items()) + "}" if v else "{}"
    if isinstance(v, list):
        return "[" + ", ".join(v) + "]"
    return str(v)


def print_report(rep):
    quests = rep["quests"]
    print(f"=== 퀘스트 해금 조건 대조: tarkov.dev regular {rep['task_count']}개 중 위키 문서 매칭 "
          f"{rep['audited_count']}개 (시즌 기준점 {rep['season_start']}) ===")
    print(f"{'field':10s} " + " ".join(f"{d:>13s}" for d in DECISIONS))
    for f in FIELDS:
        print(f"{f:10s} " + " ".join(f"{rep['counts'][f].get(d, 0):>13d}" for d in DECISIONS))

    def listing(decision, title):
        rows = [(r, f) for r in quests for f in FIELDS if r["fields"][f]["decision"] == decision]
        print(f"\n=== {title}: {len(rows)}건 (퀘스트 {len({r['id'] for r, _ in rows})}개) ===")
        for r, f in sorted(rows, key=lambda x: (x[0]["trader"] or "", x[0]["name"], x[1])):
            v = r["fields"][f]
            print(f"  {r['trader']:11s} | {r['name']} | {f}: API={_fmt(v['api'])}  위키pre={_fmt(v['wiki_pre'])}"
                  f"  위키now={_fmt(v['wiki_now'])}")

    listing("USE_WIKI", "USE_WIKI (API가 낡음 → 위키 값으로 교정 필요)")
    listing("CONFLICT", "CONFLICT (둘 다 시즌 후 바뀌었는데 결과가 다름 → 직접 판단)")
    listing("NEW_PAGE_DIFF", "NEW_PAGE_DIFF (시즌 후 새로 생긴 위키 문서와 API가 다름)")

    ug = rep["ungated_but_wiki_level"]
    print(f"\n=== API엔 게이팅이 전혀 없는데(레벨·LL·선행 없음) 위키엔 레벨 조건이 있는 퀘스트: {len(ug)}개 ===")
    print("    (앱에서 레벨 1부터 열린 것처럼 보임)")
    for u in sorted(ug, key=lambda x: (x["trader"] or "", x["name"])):
        print(f"  {u['trader']:11s} | {u['name']} | 위키now Lv{u['wiki_level']} (pre Lv{u['wiki_pre_level']}) "
              f"| level 판정 {u['level_decision']}")

    if rep["no_wiki_page"]:
        print(f"\n⚠ 위키 문서를 못 찾은 task {len(rep['no_wiki_page'])}개:")
        for x in rep["no_wiki_page"]:
            print(f"  {x['trader']} | {x['name']} | {x['wikiLink'] or '(wikiLink 없음)'}")
    if rep["fetch_errors"]:
        print(f"\n⚠ 시즌 전 리비전 받기 실패 {len(rep['fetch_errors'])}건 (다음 실행 때 재시도): "
              f"{[e['title'] for e in rep['fetch_errors']]}")
    print(f"\n보정(오버라이드) 후보 퀘스트: {len(rep['overrides'])}개 — --emit-overrides로 JS 줄 출력")
    print(f"JSON 저장: {OUT_DIR / 'latest.json'}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="tarkov.dev vs EFT 위키 퀘스트 해금 조건 대조")
    parser.add_argument("--season-start", default=DEFAULT_SEASON_START,
                        help=f"시즌 전 리비전 기준 시각 (ISO8601, 기본 {DEFAULT_SEASON_START})")
    parser.add_argument("--refresh", action="store_true", help="위키 캐시(현재·시즌 전·리다이렉트) 무시하고 다시 받기")
    parser.add_argument("--max-age", type=float, default=6.0,
                        help="현재 위키 wikitext 캐시 유효 시간(시간 단위, 기본 6)")
    parser.add_argument("--emit-overrides", action="store_true",
                        help="index.html QUEST_UNLOCK_OVERRIDES에 붙여넣을 JS 줄만 stdout에 출력")
    parser.add_argument("--json", action="store_true", help="리포트를 JSON으로 stdout에 출력")
    parser.add_argument("--out", default=str(OUT_DIR / "latest.json"), help="결과 JSON 저장 경로")
    parser.add_argument("--quiet", action="store_true", help="진행 상황(stderr) 출력 끄기")
    args = parser.parse_args()

    t0 = time.time()
    verbose = not args.quiet
    if verbose:
        print("tarkov.dev JSON API 받는 중...", file=sys.stderr, flush=True)
    api = fetch_api()
    wiki = WikiClient(args.season_start, refresh=args.refresh, max_age_hours=args.max_age, verbose=verbose)
    rep = audit(api, wiki, verbose=verbose)
    rep["wiki_requests"] = wiki.request_count
    rep["elapsed_sec"] = round(time.time() - t0, 1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.emit_overrides:
        print("\n".join(override_js_lines(rep["overrides"])))
        unresolved = [e for e in rep["overrides"] if "unresolvedAddPrereqs" in e["override"]]
        for e in unresolved:
            print(f"!! 추가할 선행 퀘스트 ID 못 찾음: {e['name']} → {e['override']['unresolvedAddPrereqs']}",
                  file=sys.stderr)
    elif args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print_report(rep)
    if verbose:
        print(f"완료: {rep['elapsed_sec']}초, 위키 요청 {wiki.request_count}회", file=sys.stderr)


if __name__ == "__main__":
    main()
