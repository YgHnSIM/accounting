# DESIGN

현재 시각 체계(`web/assets/app.css`)를 요약한 문서. 새 화면이나 수정은 이 체계를 따른다.

## 정체성
- "Hallmark Ledger": 장부처럼 굵은 상단 괘선(2px `--rule-bar`)과 1px 헤어라인으로 구역을 나눈다. 카드 중첩 대신 괘선과 여백.
- 브랜드 색: Klein Blue `#002FA7`(accent), 조합 로고 `#516DB2`, 잉크 `#0B051A`. 라이트/다크 쌍 토큰, `light-dark()` 사용.
- 의미 색: 수입 `--color-income`(녹색), 지출 `--color-expense`(적색), 교부·지원 `--color-grant`(황토), 잔액 `--color-accent`(청색).
- 차트 팔레트 "Fresh Fintech"(`--chart-*`): cobalt·blue·income·expense·grant·slate·teal·plum. `dashboard.js`가 CSS 변수에서 읽는다.

## 타이포그래피
- Pretendard Variable → SUIT → Apple SD Gothic Neo → Malgun Gothic → system-ui. 한 가족으로 제목·본문·숫자 모두 처리.
- 숫자는 `font-variant-numeric: tabular-nums lining-nums`. 고정폭 글꼴은 쓰지 않는다(데이터 스탬프 포함).
- 한국어 줄바꿈: `word-break: keep-all` + `overflow-wrap: anywhere`. 거래번호·운영기간·건수는 줄바꿈 금지.

## 구성 요소
- KPI 띠: 1px 간격 그리드, 항목별 3px 상단 색 괘선. 휴대폰(본문 폭 < 560px)에서 2열, 300px 미만에서 1열.
- 차트 리드아웃: 카드 안에 또 카드를 만들지 않는다. 배경 없는 띠 + 하단 헤어라인, 항목 색은 0.6rem 사각 스와치(범례와 동일 모양).
- 색 표시는 측면 굵은 테두리(side-tab) 대신 사각 스와치, 상단 괘선, 텍스트 색으로 한다.
- 표: 데스크톱은 상단 고정 헤더 + 580px 내부 스크롤. 본문 폭 < 620px에서는 내부 스크롤을 풀고, 행을 "제목 바 + 2열 필드 그리드" 카드로 바꾼다(분류·내용·설명·정식명칭·비고는 전체 폭).
- 내비: 넓은 화면은 현재 항목 하단 2px 괘선, 모바일 드롭다운은 옅은 accent 배경 + 밑줄.
- 보고서 아카이브 월 카드: 1px outline 격자, 연도 색은 월 숫자와 연도 헤더 상단 괘선으로만.

## 반경·간격
- 반경: 2px(sharp) / 4px(control) / 6px(sheet). 3px 이상 색 괘선이 붙는 요소는 반경 0.
- 페이지 폭 1180px, 거터 `clamp(1rem, 3vw, 2rem)`, 터치 타깃 32px 이상.
