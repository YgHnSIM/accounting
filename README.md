# 우체국물류지원단 물류노동조합 회계 프로젝트

Google Sheets 통합 원장([ledger](https://docs.google.com/spreadsheets/d/1uD8E7Sew4e3Xs50DsExENEbK9gAewtbJwRDY5Z-co3U/edit))과 로컬 보관·분석·보고 체계를 연결하는 프로젝트 폴더입니다.

## 폴더 구조

| 경로 | 역할 |
| :--- | :--- |
| `_raw/{단위코드}/` | 월별 원본 PDF 보관 (`HQ`: 본부, `AY`: 안물, `BP`: 부평물, `SS`: 서물[폐지]) |
| `config/units.json` | 회계단위 코드·명칭·신설/폐지 상태 레지스트리 |
| `config/coa.json` | 3단계 계정과목(`관·항·목`), `지출형태`, `재원구분` 마스터 |
| `config/people.json` | 인명사전: 지부 조합원 명부 및 원장 인물 인덱스 · 존칭 생략 정책 (Git 제외) |
| `data/latest/` | 최신 동기화 스냅샷 (`ledger.xlsx`, 탭별 `.csv`, `ledger.json`, `sync_meta.json`) |
| `data/snapshots/YYYY-MM-DD/` | 날짜별 `.xlsx` 백업 스냅샷 |
| `scripts/build_reports.py` | 원장 검증(존칭 자동 생략 포함) + 내부 회의용 운영위·대의원대회 보고서/차트 생성기 |
| `scripts/build_site.py` | 공개용 정제(`ledger_public.json`) 및 `_site/`(대시보드·탐색기·아카이브) 빌더 |
| `scripts/validate_site.py` | 원장 산술 검증 + 개인 실명·연락처 비식별 검사 + 링크/모바일 메타 검증기 |
| `scripts/people_utils.py` | 인명사전 조회, `privacy.json` 동기화 및 인명 존칭 생략 정규화 유틸리티 |
| `scripts/manage_units.py` | 지부 신설·폐지 시 `units.json` 및 `_raw/{CODE}/` 자동 관리 |
| `web/` | 대시보드(`dashboard.js`), 거래 탐색기(`ledger.js`), 반응형 UI(`app.css`, `nav.js`) |
| `data/public/` | 개인 실명이 비식별 처리된 GitHub Pages 빌드용 공개 JSON |
| `reports/monthly/` | 내부 회의용 정기 운영위원회 월간 재정보고 (`YYYY-MM_운영위보고.html`, Git 제외) |
| `reports/annual/` | 내부 회의용 대의원대회 결산 보고서 (`YYYY_대의원대회결산.html`, Git 제외) |
| `reports/charts/` | 대의원대회용 고해상도 PNG 차트 이미지 (Git 제외) |
| `GLOSSARY.md` | 회계 도메인 용어 사전 |

## 4. 공개 웹 대시보드 빌드 및 GitHub Pages 배포
- 공개 웹 빌드(`_site/`)에서는 `config/privacy.json`과 `config/people.json` 규칙에 따라 조합원·관계자 실명 및 연락처를 자동 비식별 처리하며, `config/privacy.json`·`config/people.json`·`_raw/`·`data/latest/`·내부 `reports/`는 `.gitignore`로 Git 추적에서 제외됩니다.
- 내부 원장·보고서 및 일반 표기에서는 인명사전(`config/people.json`) 기준에 따라 사람 이름 뒤 `'님'` 등 모든 존칭을 생략합니다.
- `main` 브랜치에 푸시하면 `.github/workflows/pages.yml`이 자동 검증 후 GitHub Pages로 배포합니다.

```powershell
# 1. 내부 보고서 생성 (실명 포함)
python scripts/build_reports.py --month 2026-09 --year 2025

# 2. 공개 웹(_site) 빌드 및 개인정보·링크 검증
python scripts/build_site.py
python scripts/validate_site.py
```

## 1. 원본 PDF 입고 규칙
- 파일명 형식: `{단위코드}_{YYYYMM}.pdf` (예: `_raw/HQ/HQ_202610.pdf`, `_raw/AY/AY_202610.pdf`)
- 폐지된 지부(예: `SS` 서물)의 폴더와 기록은 삭제하지 않고 `status: "closed"`로 영구 보존합니다.

## 2. 지부 신설 / 폐지 관리
```powershell
# 현재 회계단위 목록 확인
python scripts/manage_units.py list

# 신규 지부 추가 (예: 동서울 DS)
python scripts/manage_units.py add --code DS --name 동서울 --full-name 동서울물류센터지부 --opened 2026-11

# 기존 지부 폐지 처리
python scripts/manage_units.py close --code XX --closed 2026-12 --note "잔여금 본부 회수 완료"
```

## 3. Google Sheet 동기화 및 보고서 생성
- **방법 A (권장)**: Antigravity에게 `"구글 시트 동기화하고 이번 달 운영위 보고서 만들어줘"` 요청(또는 `/schedule` 주기 실행)
- **방법 B (오프라인 수동)**: Google Sheets에서 `파일 > 다운로드 > Microsoft Excel (.xlsx)`로 받아 `data/latest/ledger.xlsx`에 저장한 뒤 아래 명령 실행

```powershell
# 최신 월 운영위 보고서 + 2025년 대의원대회 결산 보고서 생성
python scripts/build_reports.py --month 2026-09 --year 2025

# 2026년 진행중 대의원대회 결산 자료 생성
python scripts/build_reports.py --month 2026-09 --year 2026
```
