# Tarkov ContractBoard

타르코프 하면서 퀘스트, 하이드아웃, 카파에 필요한 아이템 챙기는 게 번거로워서 만든 트래커입니다.

사이트: https://klych74m.github.io/tarkov-contractboard/

가입이나 설치 없이 바로 쓰면 되고, 진행 상황은 쓰고 있는 브라우저에만 저장됩니다.

## 기능

- 아이템 트래커: 퀘스트, 하이드아웃, 카파 컨테이너에 들어가는 아이템을 모아서 수량 체크
- 하이드아웃: 시설별 건설 조건이랑 필요한 재료
- 퀘스트 트래커: 상인별 진행 상황. 잠긴 퀘스트는 레벨, 우호도, 선행 퀘스트 중에 뭐가 부족한지 같이 보여줌
- 스토리 챕터: 메인 스토리 진행이랑 선택지
- 레이드 준비 (베타): 맵을 고르면 지금 할 수 있는 퀘스트와 챙겨갈 열쇠, 아이템, 장비를 정리
- 맵 (베타): 퀘스트 위치, 탈출구, 스폰, 잠긴 문 표시. 층을 고르면 그 층 위치만 보임
- KORD 퍽 (시즌 PVP 전용): 퍽 조합 시뮬레이션, 링크로 공유 가능
- 로그 동기화 (베타): 게임 로그 폴더를 고르면 퀘스트 시작/완료 기록을 읽어서 체크

PVE, PVP, 시즌 PVP 진행 상황은 각각 따로 저장됩니다.

## 처음 쓸 때

진영(BEAR/USEC), 에디션, 레벨부터 본인 캐릭터에 맞춰주세요. 이 값에 따라 보이는 퀘스트랑 필요한 아이템이 달라집니다.

어떻게 쓰는지 모르겠으면 상단 🎯 사용법 버튼을 누르면 탭별로 하나씩 알려줍니다.

브라우저 데이터를 지우면 진행 상황도 같이 사라지니까 가끔 상단 내보내기로 백업 파일을 받아두세요. 다른 PC로 옮길 때도 그 파일을 불러오기 하면 됩니다.

## 데이터

- 퀘스트, 아이템, 하이드아웃, 상인, 지도 좌표는 [tarkov.dev](https://tarkov.dev) 데이터를 씁니다.
- 스토리, 선택지는 [Escape from Tarkov Wiki](https://escapefromtarkov.fandom.com/wiki/Escape_from_Tarkov_Wiki)를 참고했습니다.
- 퀘스트 해금 순서랑 요구 조건은 위키 기준으로 맞췄습니다. tarkov.dev 쪽은 패치 반영이 늦을 때가 있어서요.
- 터미널 상세 지도는 tarkov-dev 저장소에 있는 이미지입니다. (Map by re3mr.com, CC BY-NC-SA 4.0)

tarkov.dev가 안 열릴 때도 볼 수 있게 마지막으로 받은 데이터를 index.html 안에 같이 넣어뒀습니다. 파일이 좀 큰 건 그래서 그렇습니다.

패치 직후에는 틀린 정보가 있을 수 있어요. 발견하면 이슈로 알려주세요.

## 구조

빌드 과정 없이 `index.html` 하나로 돌아갑니다. `scripts/` 폴더는 사이트에서 쓰는 게 아니라 데이터 점검할 때 쓰는 스크립트들입니다.

- `scrape_changes.py`: changes.tarkov-changes.com의 패치 변경 기록 수집. GitHub Actions로 2시간마다 돌고 결과는 `data/changes/`에 쌓임
- `reconcile_*.py`: tarkov.dev 값을 변경 기록, 위키랑 비교
- `emit_quest_wiki_truth.py`: 위키 기준 퀘스트 해금 조건 표 생성
- `generate_static_bundle.js`: index.html에 넣는 오프라인용 데이터 갱신

## 참고

Battlestate Games와 관계없는 개인 팬 프로젝트입니다. Escape from Tarkov 관련 이름과 이미지에 대한 권리는 Battlestate Games에 있습니다.
