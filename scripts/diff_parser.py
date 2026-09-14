"""
tarkov-changes.com의 대괄호-경로 diff 텍스트(scrape_changes.py가 저장한 diff_text)를
구조화된 변경 이벤트 목록으로 바꾸는 범용 파서.

이 파일은 특정 카테고리(하이드아웃/상인/아이템 등)를 모른다 — 순수하게 문법만 본다.
카테고리별 의미 해석(어떤 path가 무슨 값을 뜻하는지, tarkov.dev의 어떤 필드에 대응하는지)은
scripts/reconcile_*.py 쪽에서 담당한다.

입력 형태(scrape_changes.py의 parse_detail_page()가 만드는 diff_text) 예:
    ['data']
        ['Heating (5)']
            ['stages']
                ['2']
                    ['requirements']
                        ['4']
                            ['isSpawnedInSession']
    -                        (Old) 1
    +                        (New) 0 (-100.00%)
                    ['constructionTime']
    -                (Old) 7,200.0
    +                (New) 3,600.0 (-50.00%)
        ['Generator (4)']
            ['stages']
                ['2']
                        (Removed) ['6']: {
                              "type": "TraderLoyalty",
                              "traderId": "Mechanic",
                              "loyaltyLevel": 3
                            }

들여쓰기 규칙: 각 줄은 "['key']" 형태의 순수 경로 줄이거나, 맨 앞에 -/+ 기호가 붙은 값 줄이다.
-/+ 기호는 원래 있던 공백 한 칸을 대체하므로, 기호를 뗀 나머지의 들여쓰기는 형제 경로 줄과
정확히 같은 칸에 맞는다(실제 HTML 샘플로 확인함).

출력: Change 리스트. 하나의 논리적 변경(스칼라 값이면 Old+New 한 쌍, 블록이면 Removed/Added
하나)마다 Change 객체 하나.
"""

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

KEY_LINE_RE = re.compile(r"^\['(.*)'\]$")
MARKER_RE = re.compile(r"^\((Old|New|Removed)\)\s?(.*)$")
BLOCK_START_RE = re.compile(r"^\['(.*)'\]:\s*\{\s*$")


@dataclass
class Change:
    path: List[str]              # 예: ["Heating (5)", "stages", "2", "constructionTime"]
    kind: str                    # "scalar" | "block_added" | "block_removed"
    old: Optional[str] = None    # kind == "scalar"일 때만
    new: Optional[str] = None    # kind == "scalar"일 때만
    block_text: Optional[str] = None  # kind == "block_*"일 때 블록 내용 원문(여러 줄)
    block_key: Optional[str] = None   # 블록의 키 (예: TraderLoyalty 요구사항 인덱스 "6")


def _split_marker(line: str):
    """줄 맨 앞 -/+ 기호를 떼고 (marker, 나머지, 들여쓰기폭)을 돌려준다."""
    if line[:1] in ("-", "+"):
        marker = line[0]
        rest = line[1:]
    else:
        marker = None
        rest = line
    indent = len(rest) - len(rest.lstrip(" "))
    return marker, rest.strip(), indent


def parse(diff_text: str) -> List[Change]:
    lines = diff_text.split("\n")
    stack: List[tuple] = []  # (indent, key)
    changes: List[Change] = []
    i = 0
    n = len(lines)

    while i < n:
        marker, text, indent = _split_marker(lines[i])
        if not text:
            i += 1
            continue

        if marker is None:
            # 순수 경로 줄: 같은 깊이의 이전 형제(및 그 자손)를 걷어내고 새로 push한다.
            while stack and stack[-1][0] >= indent:
                stack.pop()
            m = KEY_LINE_RE.match(text)
            if m:
                stack.append((indent, m.group(1)))
            i += 1
            continue

        m = MARKER_RE.match(text)
        if not m:
            i += 1
            continue
        kind, rest = m.group(1), m.group(2)
        block_m = BLOCK_START_RE.match(rest)
        bare_block = rest.strip() == "{"  # 이미 스택에 있는 키의 값 전체가 객체로 통째로 바뀜

        if block_m or bare_block:
            if block_m:
                # "(Removed) ['5']: {...}" — 이 줄 자체가 새 키를 담고 있다(배열 인덱스를
                # 통째로 대체하는 형제 항목). 순수 경로 줄처럼 같은 깊이의 이전 형제까지
                # 걷어내고 그 키를 path에 새로 추가한다.
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                extra_key = [block_m.group(1)]
            else:
                # "(Old) {" / "(New) {" — 이미 순수 경로 줄로 push된 현재 키(예:
                # loyaltyLevels > '3')의 값 전체가 객체로 바뀐 것. 스칼라와 같은 규칙으로
                # 그 키 자체는 남기고 더 깊은 것만 걷어낸다.
                while stack and stack[-1][0] > indent:
                    stack.pop()
                extra_key = []

            # 닫는 '}' 줄의 들여쓰기가 여는 줄과 안 맞는 경우가 있어(사이트 렌더링 특성),
            # 들여쓰기 대신 중괄호 개수 균형으로 블록의 끝을 찾는다.
            block_lines = []
            depth = rest.count("{") - rest.count("}")
            i += 1
            while i < n and depth > 0:
                _, btext, _ = _split_marker(lines[i])
                depth += btext.count("{") - btext.count("}")
                if depth > 0:
                    block_lines.append(btext)
                i += 1
            block_text = "\n".join(block_lines)
            path = [k for _, k in stack] + extra_key
            block_key = extra_key[0] if extra_key else None

            if kind == "Removed":
                changes.append(Change(path=path, kind="block_removed", block_text=block_text, block_key=block_key))
            elif block_m:
                changes.append(Change(path=path, kind="block_added", block_text=block_text, block_key=block_key))
            elif kind == "Old":
                changes.append(Change(path=path, kind="scalar", old=block_text))
            else:  # bare "(New) {" completing a preceding bare "(Old) {"
                if changes and changes[-1].kind == "scalar" and changes[-1].path == path and changes[-1].new is None:
                    changes[-1].new = block_text
                else:
                    changes.append(Change(path=path, kind="scalar", new=block_text))
            continue

        # 스칼라 값: (Old) 7,200.0  또는  (New) 3,600.0 (-50.00%)
        # 이 줄의 들여쓰기는 자신이 속한 필드명 키(예: constructionTime)와 정확히 같다.
        # 그 필드명 키는 바로 앞서 순수 경로 줄로 이미 push되어 있으므로, 더 깊은
        # 것만 걷어내고 그 필드명 자체는 스택에 남겨 path에 포함시킨다.
        while stack and stack[-1][0] > indent:
            stack.pop()
        path = [k for _, k in stack]
        if kind == "Old":
            changes.append(Change(path=path, kind="scalar", old=rest))
        elif kind == "New":
            # 직전 변경이 같은 path의 Old였다면 짝을 맞춘다
            if changes and changes[-1].kind == "scalar" and changes[-1].path == path and changes[-1].new is None:
                changes[-1].new = rest
            else:
                changes.append(Change(path=path, kind="scalar", new=rest))
        i += 1

    return changes


def parse_number(value_str: Optional[str]):
    """'7,200.0' / '3,600.0 (-50.00%)' 같은 값 문자열에서 숫자만 뽑는다. 실패 시 None."""
    if not value_str:
        return None
    m = re.match(r"^-?[\d,]+(\.\d+)?", value_str.strip())
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None
