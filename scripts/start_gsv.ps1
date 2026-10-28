param([string]$WorkRoot='D:\saber-voice')
$ErrorActionPreference='Stop'
$voicePython=Join-Path $WorkRoot '.venv\Scripts\python.exe'
$entry=Join-Path $PSScriptRoot 'run_gsv_api.py'
if (-not (Test-Path -LiteralPath $voicePython)) { throw "独立环境不存在：$voicePython" }
if (Get-NetTCPConnection -LocalPort 9880 -State Listen -ErrorAction SilentlyContinue) { throw '9880 端口已被占用；请先核对现有服务，不会自动结束其他进程。' }
$logs=Join-Path $WorkRoot 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$outLog=Join-Path $logs "gsv-$stamp.out.log"
$errLog=Join-Path $logs "gsv-$stamp.err.log"
$arguments=@(('"'+$entry+'"'),'--root',('"'+$WorkRoot+'"'))
$child=Start-Process -FilePath $voicePython -ArgumentList $arguments -WorkingDirectory $WorkRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
@{pid=$child.Id;stdout=$outLog;stderr=$errLog} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $WorkRoot 'gsv-process.json') -Encoding utf8
Write-Output "已启动本机推理进程 PID=$($child.Id)，等待模型加载后检查 http://127.0.0.1:9880/health"
Write-Output "日志：$outLog 和 $errLog"
