param([string]$WorkRoot='D:\saber-voice')
$ErrorActionPreference='Stop'
if ([string]::IsNullOrWhiteSpace($WorkRoot)) { throw '必须提供本项目独立环境的路径' }
$taskProcesses=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -like '*run_asr_api.py*' -and $_.CommandLine -like "*$WorkRoot*" }
foreach ($taskProcess in $taskProcesses) {
    if (Get-Process -Id $taskProcess.ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $taskProcess.ProcessId -ErrorAction SilentlyContinue
        Write-Output "已停止本项目识别进程 PID=$($taskProcess.ProcessId)"
    }
}
