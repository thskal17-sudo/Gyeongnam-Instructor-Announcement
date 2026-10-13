# 한국 PC 에 GitHub 자체 실행기(라벨 korea)를 설치한다 (Windows 10/11).
#
# 경남판(Gyeongnam-Instructor-Announcement)용. 해외 접속을 막는 시·군 누리집(진주·거제·산청·함양 등)을
# 이 PC 가 매일 23:17·03:17 에 대신 읽는다 (.github/workflows/korea.yml).
#
# 경북판 실행기를 이미 깐 PC 에 하나 더 깔아도 된다. 폴더(C:\actions-runner-gyeongnam)와 서비스 이름이 달라 서로 겹치지 않는다
#
# 준비
#   1) Python 3.12 설치 (python.org 설치판 또는 py 실행기). 'Install for all users' 가 아니어도 됨 — 아래에서 처리
#   2) Git for Windows 설치 (기본 설정)
#   3) 저장소 Settings → Actions → Runners → New self-hosted runner 화면의
#      'Configure' 칸 명령에 있는 --token 뒤의 값(영문·숫자 29자 안팎)을 복사 (1시간 동안만 유효)
#
# 실행 (PowerShell 을 '관리자 권한으로 실행' 해서)
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\install_korea_runner.ps1 -Token <복사한 토큰>
# 이미 등록된 PC 에서 설정만 고치려면 토큰 없이 다시 실행하면 된다
#
# 지우기: C:\actions-runner-gyeongnam 에서  .\config.cmd remove --token <Remove 토큰>
param(
    [string]$Token = "",  # 처음 등록할 때만 필요. 이미 등록된 PC 에서 다시 실행하면 설정만 고친다
    [string]$Repo = "https://github.com/thskal17-sudo/Gyeongnam-Instructor-Announcement",
    [string]$Branch = "main",
    [string]$Dir = "C:\actions-runner-gyeongnam",
    [switch]$NoSleep  # 전원 연결 상태에서 절전 모드로 들어가지 않게 설정
)
$ErrorActionPreference = "Stop"

function Fail($msg) { Write-Host "`n[중단] $msg" -ForegroundColor Red; exit 1 }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail "PowerShell 을 '관리자 권한으로 실행' 한 뒤 다시 실행하세요 (실행기를 서비스로 등록해야 합니다)." }

# 1. Python 찾기. PATH 의 python 은 Microsoft Store 바로가기(WindowsApps)일 수 있어 믿지 않고
#    py 실행기와 흔한 설치 폴더까지 뒤진다
function Find-Python {
    $cands = @()
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and $c.Source -notlike "*WindowsApps*") { $cands += $c.Source }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $cands += "$exe".Trim() }
    }
    $cands += Get-ChildItem "C:\Program Files\Python3*\python.exe", "C:\Program Files (x86)\Python3*\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "C:\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object FullName
    foreach ($p in $cands) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}
$py = Find-Python
if (-not $py) {
    Write-Host "python 명령: $((Get-Command python -ErrorAction SilentlyContinue).Source)"
    Fail "Python 을 찾지 못했습니다. python.org 에서 3.12 설치판을 받아 'Add python.exe to PATH' 를 체크해 설치한 뒤 다시 실행하세요."
}
$pyDir = Split-Path $py
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git -and (Test-Path "C:\Program Files\Git\cmd\git.exe")) { $git = Get-Item "C:\Program Files\Git\cmd\git.exe" }
if (-not $git) { Fail "Git 을 찾지 못했습니다. git-scm.com 에서 Git for Windows 를 설치하세요." }
$gitDir = Split-Path $git.Source
Write-Host "Python: $(& $py --version)  ($py)"
Write-Host "Git:    $(& $git.Source --version)  ($($git.Source))"

# 실행기는 별도 서비스 계정(NETWORK SERVICE)으로 돌아가므로, 내 사용자 폴더에 깐 Python 도 읽을 수 있게 권한을 준다
if ($pyDir -like "*\Users\*") {
    icacls $pyDir /grant "*S-1-5-20:(OI)(CI)RX" /T /Q | Out-Null
    Write-Host "서비스 계정이 $pyDir 를 읽을 수 있게 했습니다."
}

# 서비스 계정의 PATH(시스템 PATH)에 Python 과 Git 의 bash 폴더를 넣는다. 작업(korea.yml)이 bash 와 python 을 PATH 에서 찾기 때문
$gitRoot = Split-Path $gitDir
$need = @($pyDir, "$pyDir\Scripts", $gitDir, "$gitRoot\bin") | Where-Object { Test-Path $_ }
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$parts = $machinePath -split ";" | Where-Object { $_ }
$add = $need | Where-Object { $d = $_.TrimEnd("\"); -not ($parts | Where-Object { $_.TrimEnd("\") -ieq $d }) }
if ($add) {
    [Environment]::SetEnvironmentVariable("Path", (($parts + $add) -join ";"), "Machine")
    Write-Host "시스템 PATH 에 추가: $($add -join ', ')"
}

# 수집에 필요한 파이썬 패키지를 미리 설치해 둔다. 실행기 서비스 계정은 파이썬 폴더에 쓸 수 없어서
# 작업(korea.yml)은 설치 없이 확인만 한다. 목록은 저장소의 pyproject.toml 에서 읽고,
# 사이트 진단(probe.yml) 이 쓰는 requests·beautifulsoup4·lxml 을 더한다
$toml = Join-Path $env:TEMP "gyeongnam-pyproject.toml"
Invoke-WebRequest "https://raw.githubusercontent.com/thskal17-sudo/Gyeongnam-Instructor-Announcement/$Branch/pyproject.toml" -OutFile $toml
$deps = & $py -c "import sys, tomllib; print('\n'.join(tomllib.load(open(sys.argv[1], 'rb'))['project']['dependencies']))" $toml
if ($LASTEXITCODE -ne 0 -or -not $deps) { Fail "pyproject.toml 을 읽지 못했습니다. Python 3.11 이상인지 확인하세요." }
$req = Join-Path $env:TEMP "gyeongnam-requirements.txt"
(@($deps) + @("requests", "beautifulsoup4", "lxml")) | Set-Content -Encoding ASCII $req
& $py -m pip install -q -r $req
if ($LASTEXITCODE -ne 0) { Fail "파이썬 패키지 설치에 실패했습니다 (위 오류 참고)." }

# 2. 실행기 내려받기 (최신판)
$release = Invoke-RestMethod "https://api.github.com/repos/actions/runner/releases/latest"
$ver = $release.tag_name.TrimStart("v")
$zip = "actions-runner-win-x64-$ver.zip"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Set-Location $Dir
if (-not (Test-Path ".\config.cmd")) {
    Write-Host "실행기 $ver 내려받는 중..."
    Invoke-WebRequest "https://github.com/actions/runner/releases/download/v$ver/$zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath . -Force
    Remove-Item $zip
}

if (Test-Path ".\.path") { Remove-Item ".\.path" }  # 예전 판이 만든 파일. 시스템 PATH 를 쓰므로 필요 없음

# 3. 등록: 라벨 korea, 서비스로 실행 (PC 를 켜면 자동 시작). 이미 등록돼 있으면 서비스만 다시 시작해 바뀐 PATH 를 반영
if (Test-Path ".\.runner") {
    # 경북판 실행기가 같은 PC 에 있을 수 있어 이 폴더의 서비스 이름(.service 파일)으로 찾는다
    $svcName = if (Test-Path ".\.service") { (Get-Content ".\.service" -Raw).Trim() } else { "" }
    $svc = if ($svcName) { Get-Service $svcName -ErrorAction SilentlyContinue } else { $null }
    if ($svc) { Restart-Service $svc.Name; Write-Host "이미 등록된 실행기입니다. 서비스($($svc.Name))를 다시 시작했습니다." }
    else { Write-Host "[주의] 실행기는 등록돼 있는데 서비스가 없습니다. PC 를 다시 시작해 보세요." -ForegroundColor Yellow }
} else {
    if (-not $Token) { Fail "처음 등록할 때는 -Token <토큰> 이 필요합니다 (Settings → Actions → Runners → New self-hosted runner)." }
    & .\config.cmd --unattended --url $Repo --token $Token --name "$env:COMPUTERNAME-gn-korea" `
        --labels korea --work _work --runasservice --replace
    if ($LASTEXITCODE -ne 0) { Fail "실행기 등록에 실패했습니다. 토큰이 만료(1시간)됐으면 New self-hosted runner 화면을 새로 열어 다시 복사하세요." }
}

# 4. 절전 끄기 (선택)
if ($NoSleep) {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "전원 연결 시 절전·최대 절전을 껐습니다."
}

Write-Host "`n[완료] 저장소 Settings → Actions → Runners 에 '$env:COMPUTERNAME-gn-korea' 가 Idle(초록)로 보이면 끝입니다." -ForegroundColor Green
Write-Host "매일 23:17·03:17 에 해외 차단 사이트를 읽습니다. 바로 시험하려면 Actions → korea → Run workflow."
