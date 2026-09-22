# 경남 강사 구인공고 수집·일일 요약 (Gyeongnam Instructor Announcement)

경남 지역 공공기관·정부산하기관·민간기관의 **강사 구인공고**를 매일 자동 수집하고,
정해진 시각에 신규·마감임박 공고 요약본을 텔레그램/이메일로 받아보는 시스템입니다.

**범위**: 경남 지방 강사 구인공고만 다룹니다. 부산·울산 지역과 대학 부설 평생교육원은 범위 밖이며 별도 프로젝트에서 관리합니다.

현재 상태: **Phase 4 진행 중** (Playwright 어댑터, 검색 포털 어댑터, GitHub Pages 아카이브, 주간 통계). Phase 3: LLM 판별·구조화 추출, 피드백 루프, 평가 명령. Phase 2: 첨부파일 텍스트 추출, onclick 게시판 지원, 이메일 채널, 소스 검증 도구. Phase 1:  (Tier 1 API 어댑터, 규칙 분류기, 마감일 파서, JSONL 저장, Markdown 리포트, 텔레그램 발송, GitHub Actions 스케줄). Tier 1 소스의 API 엔드포인트·필드명은 실측 검증 전이다.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | 전체 설계서: 요구사항, 아키텍처, 수집·분류·저장·요약·발송 각 계층, 스케줄, 데이터 모델, 운영, 준법, 테스트, 로드맵 |
| [config/sources.yaml](config/sources.yaml) | 수집 대상 기관 레지스트리 (Tier 1~4, 100여 개 항목) |
| [docs/DAILY_REPORT_TEMPLATE.md](docs/DAILY_REPORT_TEMPLATE.md) | 일일 요약본 형식과 채널별 출력 규칙 |

## 한눈에 보기

```
sources.yaml ─▶ Collector ─▶ Normalizer/Deduper ─▶ Classifier(규칙+LLM) ─▶ Store(JSONL)
                                                                             │
                     텔레그램 / 이메일 / reports/ ◀── Notifier ◀── Summarizer ◀┘
                     (매일 07:30 KST, GitHub Actions cron)
```

## 실행 방법

```bash
pip install -e ".[dev]"
python -m pytest -q                      # 오프라인 테스트
python -m gia probe gojobs --detail      # 소스 하나 시험 수집 (DATA_GO_KR_KEY 필요)
python -m gia collect --dry-run          # 전체 수집, 저장 안 함
python -m gia collect                    # 수집·저장 (data/)
python -m gia collect --refetch --sources cw_fmc  # 이미 알던 URL도 다시 파싱 (파서 수정 후 저장 데이터 보정)
python -m gia report                     # 요약본 생성·출력 (reports/)
python -m gia report --send              # 발송 (텔레그램: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID / 이메일: SMTP_*, EMAIL_TO)
python -m gia sources                    # 소스별 설정 상태
python -m gia feedback <id> false_positive  # 오탐 신고 (다음 수집부터 숨김). id는 리포트 링크 옆 12자리
python -m gia eval [--llm]               # 라벨 세트(tests/eval/labeled.jsonl)로 정밀도·재현율 측정
python -m gia stats --days 7             # 최근 7일 통계 (월요일 리포트에 자동 포함)
python -m gia site --out site            # GitHub Pages용 정적 아카이브 생성 (pages.yml이 main 푸시 시 배포)
python -m gia probe <id> --save-fixture  # 응답을 tests/fixtures/live/<id>/에 저장 (셀렉터 정할 때)
```

GitHub Actions는 매일 06:30 KST에 `collect`, 07:30 KST에 `report --send`를 실행하고 결과를 커밋한다. `pages.yml`은 `main`에 데이터·리포트가 커밋될 때 정적 아카이브를 GitHub Pages로 배포한다 (저장소 Settings → Pages → Source를 "GitHub Actions"로 설정 필요).
필요한 저장소 Secrets: `DATA_GO_KR_KEY`, `WORKNET_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. LLM 판별을 켜면 `ANTHROPIC_API_KEY`도 필요.

### LLM 판별 켜기

`config/settings.yaml`에서 `classifier.llm_enabled: true`로 바꾸고 `ANTHROPIC_API_KEY`를 등록합니다. 규칙 점수 30~69점(판단 유보) 공고부터 LLM이 강사 공고 여부를 판별하고, 포함 공고에는 분야·고용형태·마감일·자격·강사료·한 줄 요약을 채웁니다. 실행당 호출 상한은 `llm_max_calls_per_run`(기본 60)이며, 초과분은 규칙 결과만 씁니다. 기본 모델은 `claude-opus-5`이고 비용을 낮추려면 `llm_model: claude-sonnet-5`로 바꿉니다.

## 디렉터리

| 경로 | 내용 |
|---|---|
| `gia/collectors/` | HTTP 클라이언트(요청 간격·재시도·robots), `api_json`·`html_list`·`playwright`(JS 렌더링)·`search_portal`(검색어 포털) 어댑터 |
| `gia/stats.py`, `gia/site.py` | 주간 통계, GitHub Pages 아카이브(제목·요약·링크만 공개) |
| `gia/extract/deadline.py` | 마감일 파서 |
| `gia/extract/attachments.py` | 첨부 텍스트 추출 (PDF, HWPX, DOCX, HWP 5.0) |
| `gia/classify/rules.py` | 규칙 기반 관련성 점수, 분야·고용형태 추정 |
| `gia/classify/llm.py` | Claude API 판별·구조화 추출 (구조화 출력, 프롬프트 캐싱, 거부 폴백). `llm_enabled: true` + `ANTHROPIC_API_KEY` |
| `gia/feedback.py` | 오탐 피드백 기록·적용 (`data/feedback.jsonl`) |
| `gia/normalize.py`, `gia/dedupe.py` | 제목·기관명 정규화, 중복 병합 |
| `gia/store.py` | 월별 JSONL 원장, URL 인덱스, 상태 전이 |
| `gia/report/` | Markdown·텔레그램 템플릿 렌더링 |
| `gia/notify/telegram.py`, `email.py` | 텔레그램(4,000자 분할)·이메일(SMTP) 발송 |
| `docs/SOURCE_VERIFICATION.md` | 게시판 URL·셀렉터를 채우고 검증하는 절차 |
| `data/`, `reports/` | 수집 원장과 일일 리포트 아카이브 (봇이 커밋) |

## 다음 단계

1. 공공데이터포털에서 API 키를 발급받아 `gia probe gojobs`, `gia probe work24`로 엔드포인트·필드명을 검증하고 `verified: true`로 표시한다.
2. 텔레그램 봇을 만들고 Secrets를 등록한 뒤 `report` 워크플로를 수동 실행해 수신을 확인한다.
3. [docs/SOURCE_VERIFICATION.md](docs/SOURCE_VERIFICATION.md) 절차로 경남도·시군·교육청·출자출연기관 게시판의 `list_url`·셀렉터를 채운다 (네트워크가 열린 환경 필요).
