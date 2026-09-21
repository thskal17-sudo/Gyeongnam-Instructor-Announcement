# 부산·울산·경남 대학 평생교육원 강사모집 공고 수집

부산/울산/경남 지역 대학(4년제·전문대) 부설 평생교육원 홈페이지를 대상으로
**강사모집 · 강좌개설 신청 · 강사 인증/등록** 공고를 모아 둔 저장소입니다.

## 결과물

| 파일 | 내용 |
|---|---|
| [`data/announcements.md`](data/announcements.md) | 지역별 공고 표 (바로 보기용) |
| `data/announcements.xlsx` | 엑셀 파일: `공고목록`·`기관목록`·`요약`(지역×구분 자동 집계) 3개 시트 |
| `data/announcements.csv` | CSV (UTF-8 BOM) |
| `data/announcements.json` | 원본 데이터 (스크래퍼가 병합 대상으로 사용) |
| `data/institutions.json` | 대상 기관 38곳의 평생교육원 홈페이지·게시판 URL·연락처 |

각 공고 레코드의 주요 필드

- `category`: `강사모집` / `강좌개설신청` / `강좌개설제안(상시)` / `강사인증/등록` / `강사공지` / `일반강사채용(참고)`
- `confidence`: `high` = 게시글 URL까지 확인, `medium` = 제목·게시판은 확인했으나 상세 URL 미확보, `low` = 검색 스니펫으로만 확인
- `source`: `web_search` (초기 수동 수집) 또는 `scraper` (자동 수집)

`일반강사채용(참고)` 는 평생교육원이 아닌 대학 본부의 학부 강사·겸임교수 채용으로,
검색 과정에서 함께 잡혀 참고용으로만 분리해 두었습니다.

## 재수집 방법

```bash
pip install -r scraper/requirements.txt
python scraper/collect.py              # 전체 기관
python scraper/collect.py --only pia-edu ulsan-cec   # 특정 기관만
python scraper/collect.py --dry-run    # 파일 저장 없이 확인
python scraper/build_reports.py        # JSON -> CSV/MD/XLSX 재생성만
```

스크래퍼는 `data/institutions.json` 의 `boards[].url` 을 읽어 링크 제목에서
`강사모집`, `강사 채용/초빙/위수탁`, `강좌 개설 신청/제안/공모`, `강사 인증` 등의 표현을 찾고,
`수강생/교육생 모집` 같은 학습자 대상 글은 제외합니다. 기존 데이터와는 URL 또는
(기관, 제목) 기준으로 병합되므로 여러 번 실행해도 중복이 쌓이지 않습니다.

`.github/workflows/collect.yml` 은 매주 월요일 09:00(KST)에 자동 수집 후 변경분을 커밋합니다.
Actions 탭에서 `Run workflow` 로 수동 실행도 가능합니다.

## 대상 기관 추가

`data/institutions.json` 에 아래 형식으로 항목을 추가하면 됩니다.

```json
{
  "id": "example-edu",
  "region": "경남",
  "university": "OO대학교",
  "center": "평생교육원",
  "homepage": "https://edu.example.ac.kr/",
  "boards": [{"name": "공지사항", "url": "https://edu.example.ac.kr/notice"}],
  "phone": "055-000-0000"
}
```

`boards` 가 비어 있는 기관(마산대·창원문성대·김해대·거제대·동원과기대·연암공대·부산여대·부산경상대 등)은
평생교육원 게시판 URL이 아직 확인되지 않은 곳입니다. URL을 채우면 다음 수집부터 포함됩니다.

## 알려진 제약

- 초기 데이터는 대학 도메인 직접 접속이 차단된 환경에서 웹 검색 결과로 수집했습니다.
  따라서 일부 항목은 게시일이나 상세 URL이 비어 있으며(`confidence: medium/low`),
  네트워크가 열린 환경에서 `collect.py` 를 한 번 실행하면 보완됩니다.
- JavaScript 로만 목록을 그리는 게시판(onclick 링크)은 게시글 URL 대신 목록 URL이 저장됩니다.
- 첨부파일(hwp/pdf)로만 공고를 올리는 기관은 제목만 수집되고 본문 요약은 비어 있습니다.
