小智 ESP32-S3 固件（bread-compact-wifi）
==========================================
版本: v2.5.3（源码版本；本次已按升级后源码重新编译）
编译时间: 2026-11-06 15:47 (UTC)
构建环境: ESP-IDF v6.1 / target esp32s3 / 16MB Flash / DIO 80MHz / zh-CN
唤醒词: 你好小智 (wn9_nihaoxiaozhi_tts)
板型: bread-compact-wifi (OLED SSD1306 128x32)

本次源码改动（React 管理后台配套）:
- 新增控制台设备令牌支持（NVS wifi/console_token / CONFIG_CONSOLE_DEVICE_TOKEN）
- OTA 与 WebSocket 请求携带 X-Console-Device-Token
- 强制升级门禁：未完成必需升级前不开放正常服务
- OTA 上报 device_status 与 ota_mgmt 升级结果（downloading/installed/failed/booted）

文件说明:
  merged-binary.bin               整片烧录镜像（0x0 起），不能作为 OTA 应用镜像
  xiaozhi.bin                     应用镜像（OTA 升级/管理后台固件上传使用）
  bootloader.bin                  引导程序（0x0）
  partition-table.bin             分区表（0x8000）
  ota_data_initial.bin            OTA 数据分区初始镜像（0xd000）
  generated_assets.bin            资源镜像（0x800000）
  v2.5.3_bread-compact-wifi.zip   官方发布压缩包
  SHA256SUMS.txt                  校验值

整片烧录（Windows）:
  .\flash.ps1                       # 默认 COM3

OTA 应用镜像:
  上传 xiaozhi.bin 到管理后台/服务端 data/bin/bread-compact-wifi_{version}.bin

注意: 若要让已装 v2.5.3 的设备通过 OTA 识别为新版本，请递增 PROJECT_VER 后重新编译。
