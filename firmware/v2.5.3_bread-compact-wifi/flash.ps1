# 小智 ESP32 固件烧录脚本（bread-compact-wifi / ESP32-S3 / 16MB）
# 用法：右键“使用 PowerShell 运行”，或在 PowerShell 中执行：
#   .\flash.ps1               # 默认 COM3
#   .\flash.ps1 -Port COM5    # 指定串口

param(
    [string]$Port = "COM3"
)

$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir

$Python = "C:\Python314\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

Write-Host "=========================================="
Write-Host " 小智固件 v2.5.3 (ESP32-S3 / bread-compact-wifi)"
Write-Host " 串口: $Port   镜像: merged-binary.bin"
Write-Host " 后台 OTA: http://192.168.10.200:8003/xiaozhi/ota/"
Write-Host "=========================================="

& $Python -m esptool --chip esp32s3 -p $Port -b 460800 `
    --before default-reset --after hard-reset `
    write-flash --flash-mode dio --flash-freq 80m --flash-size 16MB `
    0x0 .\merged-binary.bin

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ 烧录完成！请按开发板复位键，然后连 Xiaozhi-XXXX 热点配网。"
    Write-Host "   配网页面 http://192.168.4.1 → 高级 → OTA 地址填 http://192.168.10.200:8003/xiaozhi/ota/"
} else {
    Write-Host ""
    Write-Host "❌ 烧录失败：请检查串口号（设备管理器查看）、USB 数据线、驱动是否安装。"
}
