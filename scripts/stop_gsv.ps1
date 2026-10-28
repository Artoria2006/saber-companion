param([string]$WorkRoot='D:\saber-voice')
$ErrorActionPreference='Stop'
# 只结束本项目的推理进程，不能按 python.exe 名称批量结束程序。
$taskProcesses=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -like '*run_gsv_api.py*' -and $_.CommandLine -like "*$WorkRoot*" }
foreach ($taskProcess in $taskProcesses) {
    if (Get-Process -Id $taskProcess.ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $taskProcess.ProcessId -ErrorAction SilentlyContinue
        Write-Output "已停止本项目推理进程 PID=$($taskProcess.ProcessId)"
    }
}
