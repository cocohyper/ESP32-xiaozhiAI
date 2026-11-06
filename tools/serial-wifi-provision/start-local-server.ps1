# 本机启动一个 http://127.0.0.1 服务，供浏览器使用 Web Serial API 给设备串口配网
# 用法：右键 → 使用 PowerShell 运行（或在 PowerShell 中执行本脚本）

$ErrorActionPreference = "Stop"
$Port = 8099
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path

$python = $null
foreach ($candidate in @("py", "python")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $python = $candidate; break }
}
if (-not $python) {
    Write-Host "未找到 Python。请先安装 Python 3，或直接用 Chrome/Edge 打开 index.html（file:// 方式）。" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

Write-Host "本地配网页面: http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host "浏览器需使用 Chrome 或 Edge；按 Ctrl+C 停止服务。" -ForegroundColor Yellow
Start-Process "http://127.0.0.1:$Port/"
& $python -m http.server $Port --bind 127.0.0.1 --directory $Dir
