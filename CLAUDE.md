# Tarkov Tracker — 프로젝트 지침

## 데이터 출처 원칙

모든 게임 정보(퀘스트, 아이템, 상인, 하이드아웃, 스토리 등)는 반드시 아래 두 출처를 기반으로 작업한다.

1. **tarkov.dev GraphQL API** — `https://api.tarkov.dev/graphql`
   - 퀘스트 목록, 아이템 목표, 하이드아웃 시설/재료, 상인 정보 등 동적 데이터
   - 현재 앱에서 `fetchAllData()`로 실시간 호출 중

2. **Escape from Tarkov Wiki** — `https://escapefromtarkov.fandom.com/wiki/Escape_from_Tarkov_Wiki`
   - API에 없거나 부정확한 정보(스토리, 선택지 결과, 게임 메커니즘 등)의 보완 출처
   - 아이템 위키 링크는 `https://escapefromtarkov.fandom.com/wiki/{아이템명}` 패턴 사용 중

출처 확인 없이 학습 데이터 기억만으로 게임 정보를 추가하거나 수정하지 않는다.

**검색·조사 출처 제한**: 게임 정보를 조사·검증할 때는 위 두 출처(tarkov.dev API, `https://escapefromtarkov.fandom.com/wiki/Escape_from_Tarkov_Wiki` 산하 위키 문서)만 사용한다. 그 외 어떤 웹페이지·블로그·커뮤니티 글도 검색하거나 참조하지 않는다(WebSearch/WebFetch로 타사 사이트를 조회하는 것도 금지).

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

### 게임 메커니즘 용어

| 영문 | 표준 한국어 |
|------|------------|
| Loyalty (level) | 우호도 (충성도 사용 금지) |

### 스토리 챕터명 표기 원칙

- 모든 스토리챕터명은 **한글(영어)** 형식으로 작성한다.
- 예: 추락하는 하늘(Falling Skies), 푸른 불꽃(Blue Fire)

## 프로젝트 구조

- 단일 파일: `tarkov_tracker.html` (HTML + CSS + JS 전부 포함)
- 빌드 도구 없음 — 파일 하나만 수정하면 됨
- 상태: `localStorage` 키 `tarkov_tracker_v2`
