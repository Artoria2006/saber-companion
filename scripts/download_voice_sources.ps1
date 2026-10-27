param([string]$WorkRoot = 'D:\saber-voice')
$ErrorActionPreference = 'Stop'
# 只下载指定公开页面；不读取浏览器 Cookie，不更改系统代理，不重试风控错误。
$voicePython = Join-Path $WorkRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $voicePython)) { throw "缺少独立 Python 环境：$voicePython" }
$inputFolder = Join-Path $WorkRoot 'input'
$cacheFolder = Join-Path $WorkRoot 'cache\yt-dlp'
New-Item -ItemType Directory -Path $inputFolder,$cacheFolder -Force | Out-Null
& $voicePython -m yt_dlp --ignore-config --no-playlist --retries 0 --extractor-retries 0 --socket-timeout 15 --cache-dir $cacheFolder --paths $inputFolder -f bestaudio -o '%(id)s.%(ext)s' 'https://www.bilibili.com/video/BV1fUK7eREtp/' 'https://www.bilibili.com/video/BV1pmNfeCEBq/'
if ($LASTEXITCODE -ne 0) {
    throw '下载没有全部成功。若输出 HTTP 412，请停止重试，通过平台允许的方式取得文件，放到 input 目录；不要把下载失败当作素材已经准备好。'
}
