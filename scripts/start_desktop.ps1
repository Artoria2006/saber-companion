$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
$python=Join-Path $project '.venv\Scripts\python.exe'
$entry=Join-Path $PSScriptRoot 'desktop_service.py'
if (-not (Test-Path -LiteralPath $python)) { throw "项目 Python 环境不存在：$python" }
if (Get-NetTCPConnection -LocalPort 9882 -State Listen -ErrorAction SilentlyContinue) { throw '9882 端口已被占用，不会结束其他进程。' }
$logs=Join-Path $project 'data\desktop-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$out=Join-Path $logs "desktop-$stamp.out.log"
$err=Join-Path $logs "desktop-$stamp.err.log"
$child=Start-Process -FilePath $python -ArgumentList @(('"'+$entry+'"')) -WorkingDirectory $project -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
@{pid=$child.Id;script=$entry;stdout=$out;stderr=$err} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $project 'data\desktop-process.json') -Encoding utf8
Write-Output "桌面桥已启动 PID=$($child.Id)，端口 9882，仅本机可访问。"
