# 경남 강사 구인공고 수집·일일 요약 (Gyeongnam Instructor Announcement)

경남 지역 공공기관·정부산하기관·민간기관의 **강사 구인공고**를 매일 자동 수집하고,
정해진 시각에 신규·마감임박 공고 요약본을 텔레그램/이메일로 받아보는 시스템입니다.

현재 상태: **Phase 1 구현 완료** (Tier 1 API 어댑터, 규칙 분류기, 마감일 파서, JSONL 저장, Markdown 리포트, 텔레그램 발송, GitHub Actions 스케줄). Tier 1 소스의 API 엔드포인트·필드명은 실측 검증 전이다.

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
python -m gia report                     # 요약본 생성·출력 (reports/)
python -m gia report --send              # 텔레그램 발송 (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 필요)
```

GitHub Actions는 매일 06:30 KST에 `collect`, 07:30 KST에 `report --send`를 실행하고 결과를 커밋한다.
필요한 저장소 Secrets: `DATA_GO_KR_KEY`, `WORKNET_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## 디렉터리

| 경로 | 내용 |
|---|---|
| `gia/collectors/` | HTTP 클라이언트(요청 간격·재시도·robots), `api_json`·`html_list` 어댑터 |
| `gia/extract/deadline.py` | 마감일 파서 |
| `gia/classify/rules.py` | 규칙 기반 관련성 점수, 분야·고용형태 추정 |
| `gia/normalize.py`, `gia/dedupe.py` | 제목·기관명 정규화, 중복 병합 |
| `gia/store.py` | 월별 JSONL 원장, URL 인덱스, 상태 전이 |
| `gia/report/` | Markdown·텔레그램 템플릿 렌더링 |
| `gia/notify/telegram.py` | 텔레그램 발송 (4,000자 분할) |
| `data/`, `reports/` | 수집 원장과 일일 리포트 아카이브 (봇이 커밋) |

## 다음 단계

1. 공공데이터포털에서 API 키를 발급받아 `gia probe gojobs`, `gia probe work24`로 엔드포인트·필드명을 검증하고 `verified: true`로 표시한다.
2. 텔레그램 봇을 만들고 Secrets를 등록한 뒤 `report` 워크플로를 수동 실행해 수신을 확인한다.
3. Phase 2: 경남도·시군·교육청 게시판의 `list_url`·셀렉터를 채우고 첨부파일(HWP/PDF) 추출을 붙인다.
