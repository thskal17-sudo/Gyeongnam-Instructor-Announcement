# 한국 PC 실행기 (해외 차단 사이트용)

진주·거제·산청·함양 시청, 경남도청처럼 **해외 IP 를 막는 사이트**는 GitHub 수집 서버(미국)가
읽지 못한다([LOCAL_RUN.md](LOCAL_RUN.md)). 사무실·집의 한국 PC 에 GitHub 자체 실행기를 깔아 두면
그 PC 가 매일 그 사이트들만 대신 읽는다. 경북판(kyeongbuk)과 같은 방식이고, 경북판 실행기가 있는
PC 에 하나 더 깔아도 된다.

## 흐름

```
한국 PC (korea.yml, 23:17·03:17 KST)          GitHub 수집 서버 (collect.yml, 23:47·02:47·04:17 KST)
  gia korea-export                              korea-relay 브랜치의 relay.json 을 받아
   · sources.yaml 의 korea_only: true 소스만      GIA_KOREA_RELAY 로 넘김
   · 목록·상세·첨부 글까지 읽음                     → korea_only 소스는 사이트 대신 이 기록을 읽음
   · 전화·메일은 가림                              → 판별·중복 정리·저장·메일은 평소대로
  → korea-relay 브랜치에 relay.json 하나로 올림
```

- 한국 PC 는 수집 기록(`data/`)을 고치지 않는다. 그래서 두 실행이 같은 파일을 두고 부딪히지 않는다.
- PC 가 꺼진 날은 그 소스들이 수집현황에 **'한국 PC 대기'**(건너뜀)로 나오고, 나머지는 평소대로 온다.
  실패로 세지 않으므로 메일이 미뤄지지 않는다. 36시간이 지난 기록은 쓰지 않는다.
- 한국 PC 에서 사이트가 실패하면 그 소스는 '실패'로 나온다.
- robots.txt 로 막힌 곳은 한국 PC 에서도 읽지 않는다.

## 설치 (Windows 10/11, 처음 한 번)

1. Python 3.12(python.org 설치판)와 Git for Windows 를 설치한다. 경북판 실행기를 깐 PC 면 이미 있다.
2. GitHub 의 이 저장소 → **Settings → Actions → Runners → New self-hosted runner** → Windows 를 고르고,
   'Configure' 칸 명령의 `--token` 뒤 값(1시간 동안만 유효)을 복사한다.
3. [scripts/install_korea_runner.ps1](../scripts/install_korea_runner.ps1) 을 내려받아,
   PowerShell 을 **관리자 권한으로 실행**해서:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install_korea_runner.ps1 -Token <복사한 토큰> -NoSleep
   ```
4. Settings → Actions → Runners 에 `<PC이름>-gn-korea` 가 **Idle(초록)** 이면 끝.
5. 시험: Actions → **korea** → Run workflow. 끝나면 `korea-relay` 브랜치에 `relay.json` 이 생긴다.
6. 첫 korea_only 소스를 넣을 때 `korea.yml` 의 예약(schedule)을 켠다. 실행기 없이 예약이 돌면 작업이 하루 동안 기다리다 실패하고 실패 알림이 가서 꺼 두었다.

패키지를 바꾼 뒤(`pyproject.toml`)에는 토큰 없이 스크립트를 다시 실행하면 패키지만 새로 깐다.

## 사이트 추가

1. **사이트 진단(probe)** 을 `runner: korea` 로 돌려 게시판 구조를 본다 (`urls`, `raw_selector` 등은 평소와 같다).
2. `sources.yaml` 에 셀렉터를 채우고 `korea_only: true` 를 붙인다.
3. probe 를 `runner: korea`, `sources: <id>` 로 돌려 목록·마감일이 잡히는지 확인한다.
