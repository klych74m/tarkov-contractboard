# Tarkov ContractBoard — 프로젝트 지침

## 데이터 출처 원칙

모든 게임 정보(퀘스트, 아이템, 상인, 하이드아웃, 스토리 등)는 반드시 아래 세 출처를 기반으로 작업한다.

1. **tarkov.dev GraphQL API** — `https://api.tarkov.dev/graphql`
   - 퀘스트 목록, 아이템 목표, 하이드아웃 시설/재료, 상인 정보 등 동적 데이터
   - 현재 앱에서 `fetchAllData()`로 실시간 호출 중

2. **Escape from Tarkov Wiki** — `https://escapefromtarkov.fandom.com/wiki/Escape_from_Tarkov_Wiki`
   - API에 없거나 부정확한 정보(스토리, 선택지 결과, 게임 메커니즘 등)의 보완 출처
   - 아이템 위키 링크는 `https://escapefromtarkov.fandom.com/wiki/{아이템명}` 패턴 사용 중

3. **tarkov-changes.com (Silent Changes)** — `https://changes.tarkov-changes.com`
   - BSG가 패치노트에 공지하지 않고 조용히 바꾼 값(밸런스 수치, 아이템 스펙 등) 추적용 보완 출처
   - `scripts/scrape_changes.py` + `.github/workflows/scrape-changes.yml`이 2시간 주기로 스크래핑해 `data/changes/`(패치별 `{id}.json` + 가벼운 목록 `index.json`)에 누적 저장한다
   - **이 데이터는 사용자 화면에 그대로 노출하지 않는다.** Contract Board 프론트엔드는 이 파일을 fetch하지 않는다. 용도는 오직 하나 — 새 패치가 나왔을 때 Claude가 이 원본 diff를 직접 읽고 무엇이 바뀌었는지 파악한 뒤, 그 내용을 바탕으로 `index.html`의 실제 사용자용 데이터(퀘스트명, 특성 수치, 하이드아웃 조건 등)를 다른 두 출처와 똑같은 방식으로 수정하는 것이다. 즉 tarkov-changes.com은 "화면에 보여줄 콘텐츠"가 아니라 "조사용 원본 자료"다.
   - `BASELINE_ID = 1151`(Season 1 KORD BREACH 본패치, 1.1.0.0.46608) 이전 항목은 수집하지 않는다.
   - 이 사이트에 대한 임의의 WebFetch/WebSearch 조사는 여전히 금지. 접근은 오직 위 자동화 파이프라인이 쌓은 `data/changes/`를 읽는 것으로만 이루어진다.

**세 출처의 역할 — 우선순위가 아니라 계층 구조다**: "1번이 항상 이긴다"는 단순 순위가 아니다. `data/changes/`(로그)는 diff만 기록하므로 안 바뀐 값은 애초에 거기 없다 — 그래서 로그 단독으로는 "현재 전체 상태"를 answer할 수 없다. 실제 조사 순서는 다음과 같다.
   1. **tarkov.dev API**에서 현재 값을 가져온다 (뼈대 — 전체 상태)
   2. `data/changes/`(및 `scripts/reconcile_*.py` 대조 스크립트의 산출물)에 tarkov.dev보다 최근 diff가 있는지 확인한다 → 있으면 로그의 New 값이 진짜 최신값이므로 tarkov.dev 값을 대체한다 (tarkov.dev 파이프라인이 아직 못 따라잡은 경우가 실제로 있었다 — 2026-08 KORD BREACH 하이드아웃 건설 조건이 그 사례)
   3. 그래도 없는 정보(스토리, 선택지 결과, 게임 메커니즘 설명 등)만 위키로 보완한다

**대조 스크립트 구성**:
   - `scripts/diff_parser.py` — tarkov-changes.com의 대괄호-경로 diff 텍스트를 구조화된 이벤트로 바꾸는 범용 파서. 모든 `reconcile_*.py`/`summarize_*.py`가 이걸 공유한다. 카테고리를 모르는 순수 문법 파서이므로, 새 카테고리를 추가할 때 이 파일은 안 건드려도 된다.
   - `scripts/reconcile_hideout.py` — 하이드아웃 건설시간·상인우호도삭제 대조
   - `scripts/reconcile_traders.py` — 상인 우호도 레벨의 요구 레벨/평판/판매액 대조 (가격 계수류는 tarkov.dev와 단위가 달라 대상에서 뺐다)
   - `scripts/reconcile_hideout_recipes.py` — 하이드아웃 제작 레시피 신규/삭제 대조
   - `scripts/reconcile_items.py` — 최상위 아이템 신규/삭제 대조
   - `scripts/summarize_achievements.py` — **대조가 아니라 요약이다.** json.tarkov.dev에 achievements 엔드포인트가 없어서(2026-08 확인, 404) 비교 대상 자체가 없다. 로그에 쌓인 업적 변경사항을 사람이 읽기 좋게 나열만 한다.
   - **퀘스트는 로그가 아니라 위키 대조로 본다.** tarkov-changes.com은 quests/tasks 파일을 아예 추적하지 않는다(2026년 6~8월 여러 시점 직접 확인함). 대신 `scripts/reconcile_quests_wiki.py`가 tarkov.dev 퀘스트 해금 조건(레벨·상인 우호도·선행 퀘스트·지도)을 위키 문서의 **시즌 전 판본과 현재 판본** 둘 다와 비교해, 필드마다 어느 출처가 최신인지 판정한다(위키만 바뀜 → USE_WIKI, API만 바뀜 → KEEP_API, 둘 다 다르게 바뀜 → CONFLICT). 위키 문서의 최종 수정일은 관리자 보호 설정 변경으로도 바뀌므로 신선도 판단에 쓰지 않는다.
     - `--emit-overrides`로 index.html `QUEST_UNLOCK_OVERRIDES`에 붙여넣을 줄을 뽑는다. 단, 메카닉의 옛 등대지기 접근 체인 중 Getting Acquainted는 9/8 "To the Light" 개편의 마지막 단계로 확인돼 선행을 새 체인(To the Light - The Other Side)으로 바꾼 줄을 따로 넣었다. 나머지 6줄(Network Provider 2 → Assessment 1~3 → Key to the Tower → Knock-Knock)은 위키에서 선행·후속이 모두 지워졌지만 게임에서 삭제됐는지 확인될 때까지 붙여넣지 않는다.
     - **퀘스트 해금 조건은 위키 우선(사용자 방침, 2026-09-14)**: tarkov.dev는 패치 반영이 느리므로 레벨·상인 우호도·선행 퀘스트는 위키 현재 판본을 기준으로 맞춘다. `python scripts/reconcile_quests_wiki.py --refresh` → `python scripts/emit_quest_wiki_truth.py` 순서로 실행해 `data/quest_audit/wiki_truth_overrides.js`를 만들고, index.html `QUEST_WIKI_REQUIREMENTS` 표를 그 내용으로 바꾼다(위키와 API가 다른 퀘스트만, API와 무관하게 항상 적용). 위키 선행이 OR 조건인 퀘스트와 위키 문서에 조건이 하나도 적혀 있지 않은 퀘스트는 자동 적용하지 않으니 생성기의 skipped 목록을 보고 판단한다. 예전 `QUEST_LEVEL_FALLBACKS`(위키 레벨 임시 하한)는 이 표로 대체돼 삭제했고, `QUEST_UNLOCK_OVERRIDES`에는 이 표로 표현할 수 없는 수동 보정(예: tarkov.dev에 없는 신규 퀘스트를 선행으로 연결)만 남긴다.
     - `WIKI_PENDING_QUESTS`(index.html) — tarkov.dev에 아직 없는 신규 퀘스트를 위키 문서 기준으로 임시 주입하는 표. 새 패치가 나오면 `data/changes/{id}.json`의 `client/locale/en` 번역 diff에서 새로 생긴 `<id> name` 키로 퀘스트 ID를 찾고, 위키 문서로 상인·해금 조건·목표·보상을 채운다. tarkov.dev에 같은 ID가 들어오면 앱이 자동으로 건너뛰므로, 반영을 확인한 뒤 해당 항목을 지운다.
   - 실행: `python scripts/reconcile_hideout.py` 처럼 개별 실행. 새 카테고리가 필요하면 같은 패턴(대상 diff 파일 지정 → 최신 truth 구성 → tarkov.dev 라이브 값과 필드 단위 비교, 단위/스키마가 다른 필드는 명시적으로 제외)으로 추가한다.

출처 확인 없이 학습 데이터 기억만으로 게임 정보를 추가하거나 수정하지 않는다.

**검색·조사 출처 제한**: 게임 정보를 조사·검증할 때는 위 세 출처(tarkov.dev API, `https://escapefromtarkov.fandom.com/wiki/Escape_from_Tarkov_Wiki` 산하 위키 문서, tarkov-changes.com 스크래핑 파이프라인이 쌓은 `data/changes/`)만 사용한다. 그 외 어떤 웹페이지·블로그·커뮤니티 글도 검색하거나 참조하지 않는다(WebSearch/WebFetch로 타사 사이트를 조회하는 것도 금지 — tarkov-changes.com 자체도 예외 없이 직접 WebFetch/WebSearch 금지, 반드시 자동화 파이프라인이 쌓은 `data/changes/`를 통해서만 참조).

**지도(맵) 이미지 출처 원칙**: 지도 관련 작업(맵 배경 이미지, 좌표 변환, 지형 시각화 등)은 아래 출처만 사용한다.
   - **tarkov.dev** — `the-hideout/tarkov-dev` 저장소의 2D 맵 이미지(`public/maps/{name}-2d.jpg` 등)와 `src/data/maps.json`(좌표·층 구간). 이미지마다 라이선스가 다르니 확인한다(예: `terminal-2d.jpg`는 re3mr.com CC BY-NC-SA 4.0, 출처 표시 필수).
   - **맵 탭 배경·층 레이어 SVG(`maps/*.svg` 12개)** — [Zeliper/Tarkov-Item-Helper](https://github.com/Zeliper/Tarkov-Item-Helper)(`TarkovHelper/Assets/DB/Maps/`, 터미널 제외 11개)와 그 포크 [SIGDrone/Tarkov-Helper](https://github.com/SIGDrone/Tarkov-Helper)(같은 경로, 터미널 포함 12개). 두 저장소 모두 README에 MIT License를 명시해 사용이 허용된다(2026-09-14 사용자 확인, 파일이 바이트 단위로 동일함도 확인). index.html `MAP_DEFS`의 좌표 변환값(transform)과 SVG 층 레이어 id도 같은 저장소의 `map_configs.json` 기준이다(터미널 transform만 tarkov.dev `maps.json`으로 다시 계산). README.md 데이터 항목의 출처 표시를 유지하고, SVG를 새로 받거나 갱신할 때도 이 두 저장소에서만 가져온다.
   - 그 밖의 제3자 팬메이드 툴·사이트("Where am I" 류 등)의 지도 이미지·데이터는 출처가 불분명하거나 또 다른 제3자(tarkov-market.com 등)의 자산을 재배포하는 경우가 많아 저작권 문제가 있으므로 사용하지 않는다.

## 용어 통일 원칙

코드/텍스트 내 모든 한국어 표기는 아래 표준 용어를 사용한다. 다른 표현(커스텀, 쇼어라인, 팩토리, 우즈, 인터페인지, 라이트하우스, 더 랩, BTR 드라이버 등)은 사용하지 않는다.

### 상인 (Trader)
| 영문 | 표준 한국어 |
|------|------------|
| Prapor | 프라퍼 |
| Therapist | 테라피스트 |
| Fence | 펜스 |
| Skier | 스키어 |
| Peacekeeper | 피스키퍼 |
| Mechanic | 메카닉 |
| Ragman | 래그맨 |
| Jaeger | 예거 |
| Lightkeeper | 등대지기 |
| Ref | 레프 |
| BTR Driver | BTR 운전수 |

### 지역 (Map)
| 영문 | 표준 한국어 |
|------|------------|
| Customs | 세관 |
| Shoreline | 해안선 |
| The Labyrinth | 미궁 |
| Icebreaker | 쇄빙선 |
| Factory | 공장 |
| Woods | 삼림 |
| Interchange | 인터체인지 |
| The Lab | 연구소 |
| Reserve | 리저브 |
| Lighthouse | 등대 |
| Streets of Tarkov | 타르코프 시내 |
| Ground Zero | 그라운드 제로 |
| Terminal | 터미널 |

### 하이드아웃 시설 (Hideout)
| 영문 | 표준 한국어 |
|------|------------|
| Air Filtering Unit | 공기 정화 시설 |
| Bitcoin Farm | 비트코인 채굴 시설 |
| Booze Generator | 양조 시설 |
| Generator | 발전기 |
| Heating | 난방 시설 |
| Illumination | 조명 시설 |
| Intelligence Center | 정보 수집 시설 |
| Lavatory | 화장실 |
| Library | 서재 |
| Medstation | 의료 시설 |
| Nutrition Unit | 조리 시설 |
| Rest Space | 휴식 공간 |
| Scav Case | 스캐브 케이스 |
| Security | 보안 시설 |
| Shooting Range | 사격장 |
| Solar Power | 태양열 발전기 |
| Stash | 창고 |
| Vents | 환기 시설 |
| Water Collector | 물 공급 시설 |
| Workbench | 작업대 |
| Gym | 헬스장 |
| Hall of Fame | 진열장 |
| Gear Rack | 장비 거치대 |
| Weapon Rack | 무기 거치대 |
| Cultist Circle | 광신도 제단 |
| Defective Wall | 약한벽 |

### 아이템 표기 원칙

- 한국어 명칭이 있는 게임 아이템은 **한글(영어)** 형식으로 표기한다.
- 예: 인식표(Dogtag), 건설 자재(Corrugated hose) 등

| 영문 | 표준 한국어 표기 |
|------|----------------|
| Dogtag | 인식표(Dogtag) |

### 보스 (Boss)

| 영문 | 표준 한국어 | 비고 |
|------|------------|------|
| Reshala | 르샬라 | 세관 |
| Killa | 킬라 | 타르코프 시내 |
| Shturman | 슈트르만 | 삼림 |
| Glukhar | 글루하 | 리저브 |
| Sanitar | 세니타 | 해안선 |
| Tagilla | 타길라 | 공장 |
| Shadow of Tagilla | 쉐도우 오브 타길라 | |
| Kaban | 카반 | 타르코프 시내 |
| Kollontay | 콜론타이 | 그라운드 제로 |
| The Goons | 군즈 | Knight+Big Pipe+Birdeye 3인조 |
| Big Pipe | 빅 파이프 | 군즈 소속 |
| Knight | 나이트 | 군즈 소속 |
| Birdeye | 버드아이 | 군즈 소속 |
| Black Division | 블랙 디비전 | |
| The Wedge | 웨지 | |
| Cultists | 컬티스트 | 광신도 집단 전체 지칭 |
| Sektant (Cultist follower) | 광신도 | |
| Zhrec (Cultist Priest) | 사제 | |
| Zryachiy | 즈랴치 | 등대 |
| Oni | 오니 | |
| Harbinger | 하빈저 | |
| Ghost | 고스트 | |
| Partisan | 파르티잔 | |
| Boar (bossBoar) | 카반 | 타르코프 시내 |
| ExUsec | 로그 | 등대·터미널 |
| Sentry | 러시아 정규군 보초병 | 해안선 |
| vsRF | 러시아 정규군 | 터미널 |
| vsRFSniper | 러시아 정규군 저격수 | 터미널 |

### 게임 메커니즘 용어

| 영문 | 표준 한국어 |
|------|------------|
| Loyalty (level) | 우호도 (충성도 사용 금지) |

### 스토리 챕터명 표기 원칙

- 모든 스토리챕터명은 **한글(영어)** 형식으로 작성한다.
- 예: 추락하는 하늘(Falling Skies), 푸른 불꽃(Blue Fire)

## 배포 금지 원칙

**`git push` 및 GitHub Pages 배포는 사용자가 명시적으로 "배포해줘" / "푸시해줘" 라고 요청하기 전까지 절대 금지한다.**

- 코드 수정 후 자체 판단으로 배포하지 않는다.
- 테스트·검증이 필요한 경우 로컬(file://)에서 먼저 확인하거나 사용자에게 보고하고 지시를 기다린다.
- commit은 사용자 요청 시에만 생성한다.

## 프로젝트 구조

- 단일 파일: `index.html` (HTML + CSS + JS 전부 포함, GitHub Pages 배포용)
- 빌드 도구 없음 — 파일 하나만 수정하면 됨
- 상태: `localStorage` 키 `tarkov_tracker_v2`
- 사용법 투어: `index.html`의 `TOURS`(전체 투어 `full` + 탭별 투어). 각 단계는 실제 화면 요소를 선택자로 가리키므로, 버튼·카드를 추가하거나 id·class를 바꾸면 해당 탭의 투어 단계도 함께 고친다. 진행 기록은 localStorage `tarkov_tour_v1`.
- 오프라인 폴백 데이터: `index.html` 맨 끝 `</body>` 바로 앞의 `static-fallback-data` JSON 스크립트 태그(약 4MB). tarkov.dev 접속 실패 + 이 브라우저에 캐시가 없을 때만 읽는다. 갱신은 `node scripts/generate_static_bundle.js`(앱을 헤드리스 크롬으로 열어 받은 캐시를 그대로 넣음). 이 태그의 여는 태그 문자열을 코드·주석 다른 곳에 적지 않는다 — 생성 스크립트가 태그를 하나만 있어야 덮어쓰도록 막아두었다.
