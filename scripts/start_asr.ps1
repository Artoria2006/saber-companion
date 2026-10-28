param([string]$WorkRoot='D:\saber-voice')
$ErrorActionPreference='Stop'
$asrPython=Join-Path $WorkRoot '.venv\Scripts\python.exe'
$entry=Join-Path $PSScriptRoot 'run_asr_api.py'
if (-not (Test-Path -LiteralPath $asrPython)) { throw "独立环境不存在：$asrPython" }
if (Get-NetTCPConnection -LocalPort 9881 -State Listen -ErrorAction SilentlyContinue) { throw '9881 端口已被占用，不会自动结束其他进程。' }
$logs=Join-Path $WorkRoot 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$outLog=Join-Path $logs "asr-$stamp.out.log"
$errLog=Join-Path $logs "asr-$stamp.err.log"
$arguments=@(('"'+$entry+'"'),'--root',('"'+$WorkRoot+'"'))
$child=Start-Process -FilePath $asrPython -ArgumentList $arguments -WorkingDirectory $WorkRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
@{pid=$child.Id;stdout=$outLog;stderr=$errLog} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $WorkRoot 'asr-process.json') -Encoding utf8
Write-Output "识别服务启动中，PID=$($child.Id)，健康地址 http://127.0.0.1:9881/health"
Write-Output "日志：$outLog 和 $errLog"
