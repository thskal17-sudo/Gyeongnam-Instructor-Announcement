# 경남 강사 구인공고 수집·일일 요약 (Gyeongnam Instructor Announcement)

경남 지역 공공기관·정부산하기관·민간기관의 **강사 구인공고**를 매일 자동 수집하고,
정해진 시각에 신규·마감임박 공고 요약본을 텔레그램/이메일로 받아보는 시스템입니다.

현재 상태: **설계 단계** (코드 없음).

## 문서

| 문서 | 내용 |
|---|---|
| [docs/DESIGN.md](docs/DESIGN.md) | 전체 설계서: 요구사항, 아키텍처, 수집·분류·저장·요약·발송 각 계층, 스케줄, 데이터 모델, 운영, 준법, 테스트, 로드맵 |
| [config/sources.yaml](config/sources.yaml) | 수집 대상 기관 레지스트리 (Tier 1~4, 70여 개 항목) |
| [docs/DAILY_REPORT_TEMPLATE.md](docs/DAILY_REPORT_TEMPLATE.md) | 일일 요약본 형식과 채널별 출력 규칙 |

## 한눈에 보기

```
sources.yaml ─▶ Collector ─▶ Normalizer/Deduper ─▶ Classifier(규칙+LLM) ─▶ Store(JSONL)
                                                                             │
                     텔레그램 / 이메일 / reports/ ◀── Notifier ◀── Summarizer ◀┘
                     (매일 07:30 KST, GitHub Actions cron)
```

## 다음 단계

설계서 20절 "미결 사항"의 7개 항목(발송 채널, 발송 시각, LLM 모델·예산, 인접 지역 포함 여부 등)을 정한 뒤
로드맵 Phase 0(API 키 신청, 텔레그램 봇 생성, Tier 1 URL 검증)부터 착수합니다.
