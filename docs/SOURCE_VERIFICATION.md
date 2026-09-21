# 수집원 검증 가이드 (Phase 2)

`config/sources.yaml`의 `TODO` 값을 채우고 `verified: true`로 바꾸는 절차입니다. 네트워크가 열린 환경에서 진행합니다.

## 0. 현황 보기

```bash
python -m gia sources            # 소스별 설정 상태 (미설정 이유 포함)
python -m gia sources --tier 2   # 특정 tier만
```

## 1. 게시판 URL 찾기

- 기관 홈페이지에서 "채용", "공고", "모집", "인재채용", "공지사항" 메뉴를 연다.
- 목록 URL에 페이지 번호가 있으면 `{page}`로 바꾼다. 예: `.../list.do?pageIndex={page}`
- 목록이 JavaScript로만 그려지면(HTML 소스에 글 제목이 없음) 지금은 등록하지 말고 `notes`에 "JS 렌더링 필요"라고 적는다 (Phase 4 Playwright 어댑터).
- 로그인이 필요하거나 robots.txt가 해당 경로를 막으면 등록하지 않는다.

## 2. 응답 저장

```bash
python -m gia probe <source_id> --save-fixture
```

`tests/fixtures/live/<source_id>/` 아래에 목록 페이지(과 첫 상세 페이지)가 저장됩니다. 이 파일을 열어 셀렉터를 정합니다.
`list_url`만 채운 상태여도 `--save-fixture`는 동작합니다 (row_selector가 `TODO`면 저장만 하고 파싱은 건너뜀).

## 3. 셀렉터 정하기

| 항목 | 설명 | 흔한 값 |
|---|---|---|
| `row_selector` | 공고 한 건이 되는 요소 | `table.bbs_list tbody tr`, `ul.board_list li`, `div.list-item` |
| `title_selector` | 행 안에서 제목 링크 | `td.subject a`, `td.title a`, `a.tit` |
| `link_selector` | 제목과 다른 요소에 링크가 있을 때 | 보통 생략 (title_selector 사용) |
| `date_selector` | 게시일 | `td.date`, `span.date`, `td:nth-child(4)` |
| `org_selector` | 포털(여러 기관)일 때 기관명 | `td.org` |
| `encoding` | EUC-KR 사이트 | `euc-kr` (meta charset이 없을 때만) |
| `detail.body_selector` | 상세 본문 | `div.bbs_view_content`, `div.view_con`, `td.content` |
| `detail.attachment_selector` | 첨부 링크 | `a[href*="download"]`, `ul.file_list a` |

### onclick 링크 게시판

`<a href="#" onclick="fn_view('12345')">제목</a>`처럼 URL이 없는 경우:

```yaml
adapter:
  type: html_list
  list_url: https://www.example.go.kr/board/list.do?pageIndex={page}
  row_selector: table.bbs_list tbody tr
  title_selector: td.subject a
  link_attr: onclick
  link_regex: "fn_view\\('(\\d+)'\\)"
  link_url_template: "https://www.example.go.kr/board/view.do?seq={1}"
  date_selector: td.date
  detail: { body_selector: div.bbs_view_content, attachment_selector: "a[href*='download']" }
```

`{0}`은 정규식 전체 일치, `{1}`부터는 그룹입니다.

### 정부 표준 CMS 예시 (표 형태)

```yaml
adapter:
  type: html_list
  list_url: https://www.example.go.kr/portal/saeol/gosi/list.do?pageIndex={page}
  row_selector: table.tbl_list tbody tr
  title_selector: td.tit a
  date_selector: td:nth-child(4)
  keywords: [강사, 교강사, 지도자, 지도사]
  detail: { body_selector: div.view_cont, attachment_selector: "div.file a" }
```

### JS 렌더링 게시판 (playwright)

HTML 소스에 글 제목이 없고 스크립트가 목록을 그리는 사이트는 `type: playwright`로 등록합니다. 셀렉터 설정은 `html_list`와 같고 `wait_for`(목록이 그려졌음을 뜻하는 셀렉터)만 추가합니다.

```yaml
adapter:
  type: playwright
  list_url: https://www.example.or.kr/recruit/list?page={page}
  wait_for: table.list tbody tr
  row_selector: table.list tbody tr
  title_selector: td.title a
  date_selector: td.date
  detail: { render: true, body_selector: div.view_body }   # render: false 면 상세는 일반 HTTP로
```

- 실행 환경에 Chromium이 필요합니다. `pip install -e ".[browser]"` 후 `playwright install chromium`. GitHub Actions에서는 `collect.yml`에 `playwright install --with-deps chromium` 단계를 추가합니다 (약 1분).
- 이미 설치된 Chromium을 쓰려면 `GIA_CHROMIUM_PATH` 환경변수로 실행 파일을 지정합니다.
- 브라우저 렌더링은 HTTP보다 10배 이상 느리므로 `paging.max_pages`를 1~2로 둡니다.

### 검색어 기반 포털 (search_portal)

민간 채용 포털처럼 검색 결과 페이지에서 수집하는 소스입니다. `query_url_template`의 `{query}`에 `queries`를 차례로 넣고, 결과는 `html_list`와 같은 셀렉터로 파싱합니다. 같은 URL은 한 번만 남깁니다.

```yaml
adapter:
  type: search_portal
  query_url_template: https://www.example.com/search?q={query}&page={page}
  queries: ["강사 경남", "강사 창원"]
  row_selector: div.item
  title_selector: a.title
  org_selector: span.company
  date_selector: span.date
  paging: { max_pages: 2 }
```

민간 포털은 **이용약관의 자동 수집 조항을 먼저 확인**하고 `tos_checked: true`를 기록한 뒤에만 `enabled: true`로 바꿉니다. 약관이 금지하면 등록하지 않고 사이트의 이메일 알림 기능을 씁니다.

### API 소스

`gia probe <id> --save-fixture`가 저장한 JSON/XML을 보고 `items_path`와 `field_map`을 맞춥니다.
날짜 형식이 다르면 `date_formats`에 추가합니다 (`%Y%m%d`, `%Y-%m-%d`, `%y-%m-%d` 등).

## 4. 확인

```bash
python -m gia probe <source_id>            # 목록 5건 출력
python -m gia probe <source_id> --detail   # 첫 건의 본문 길이, 마감일, 점수, 포함 여부
python -m gia collect --dry-run --sources <source_id>
```

확인 항목

- 제목·링크·날짜가 올바르게 나온다.
- 상세 본문에 접수기간 문장이 들어 있다. 첨부에만 있으면 `attachment_selector`를 확인한다.
- 마감일이 `fixed`로 잡힌다. `unknown`이면 첨부 추출 실패인지, 날짜 표기가 특이한지 본다.
- 강사 공고가 아닌 글은 점수 30 미만으로 제외된다.

## 5. 마무리

- `verified: true`, `tos_checked: true`(약관 확인 시)로 바꾼다.
- 저장한 fixture 중 대표 목록·상세 HTML을 `tests/fixtures/<source_id>/`로 옮기고 `tests/test_sources_live.py`에 파싱 테스트를 추가하면 사이트 개편을 CI에서 잡을 수 있다 (선택).
- 같은 공고가 Tier 1 포털에서도 수집되면 이 소스는 `notes`에 적고 우선순위를 낮춘다.

## 자주 생기는 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| 목록 0건 | row_selector 불일치, JS 렌더링 | fixture HTML에서 셀렉터 재확인 |
| 제목은 나오는데 URL이 홈페이지 | onclick 링크 | `link_attr`, `link_regex`, `link_url_template` |
| 글자 깨짐 | 인코딩 | `encoding: euc-kr` |
| 마감일 unknown | 첨부(HWP)에만 있음 | `attachment_selector` 확인, `첨부추출실패` 플래그 확인 |
| HTTP 403 | User-Agent 차단 또는 robots | `notes`에 기록하고 비활성화 |
