"""
Lucky Scav Junkbox 스크린샷 인식 기능용 잡템(Barter item) 아이콘 해시 DB 생성 스크립트.

tarkov.dev API에서 "Barter item" 카테고리 아이템(총기파츠/스택형 재화 제외)의
아이콘을 받아 지각 해시(dHash)와 색상 시그니처를 계산한다.
file://로 직접 열 때 fetch()가 CORS로 막히는 걸 피하려고, 결과를 index.html의
BARTER_HASH_DB 상수 블록에 직접 박아넣고(barter-item-hashes.json은 검토용 부산물로만 남김).
게임에 새 잡템이 추가/변경될 때만 다시 실행하면 된다.

실행: python build_barter_hashes.py
"""
import json
import re
from io import BytesIO

import requests
from PIL import Image

API_URL = "https://api.tarkov.dev/graphql"
OUTPUT_PATH = "barter-item-hashes.json"
HTML_PATH = "index.html"

QUERY = """
{
  items(categoryNames: ["Barter item"]) {
    id
    name
    iconLink
  }
}
"""


def dhash(img, hash_size=8):
    gray = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(hash_size):
        row_pixels = pixels[row * (hash_size + 1):(row + 1) * (hash_size + 1)]
        for col in range(hash_size):
            bits = (bits << 1) | (1 if row_pixels[col] > row_pixels[col + 1] else 0)
    return format(bits, "016x")


def color_signature(img, grid=4):
    small = img.convert("RGB").resize((grid, grid), Image.LANCZOS)
    flat = []
    for r, g, b in small.getdata():
        flat.extend([r, g, b])
    return flat


def main():
    resp = requests.post(API_URL, json={"query": QUERY}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    items = payload["data"]["items"]
    print(f"{len(items)} barter items found")

    out = []
    for it in items:
        icon_link = it.get("iconLink")
        if not icon_link:
            continue
        try:
            r = requests.get(icon_link, timeout=15)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
        except Exception as e:
            print(f"  skip {it['name']}: {e}")
            continue
        out.append({
            "id": it["id"],
            "name": it["name"],
            "hash": dhash(img),
            "colors": color_signature(img),
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"wrote {len(out)} entries to {OUTPUT_PATH}")

    inject_into_html(out)


def inject_into_html(entries):
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    json_str = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
    block = f"const BARTER_HASH_DB = {json_str};"
    pattern = re.compile(r"(// BARTER_HASH_DB:START\n)(.*?)(\n// BARTER_HASH_DB:END)", re.DOTALL)
    new_html, count = pattern.subn(lambda m: m.group(1) + block + m.group(3), html, count=1)
    if count != 1:
        raise SystemExit("index.html에서 BARTER_HASH_DB:START/END 마커를 찾지 못했습니다.")
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"index.html의 BARTER_HASH_DB 블록을 {len(entries)}개 항목으로 갱신했습니다.")


if __name__ == "__main__":
    main()
