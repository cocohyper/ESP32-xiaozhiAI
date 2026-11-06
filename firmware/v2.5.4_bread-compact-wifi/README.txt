小智 ESP32-S3 固件 v2.5.4（bread-compact-wifi）
================================================
版本: v2.5.4
编译时间: 2026-11-06 16:23 (UTC)
构建环境: ESP-IDF v6.1 / target esp32s3 / 16MB Flash / DIO 80MHz / zh-CN
唤醒词: 你好小智 (wn9_nihaoxiaozhi_tts)
板型: bread-compact-wifi (OLED SSD1306 128x32)

本版新增功能
------------
1. 串口配网（浏览器 Web Serial 工具）
   - 设备在 UART0 (115200 8N1) 监听行命令:
       WIFICFG:PING / STATUS / SCAN
       WIFICFG:SET:{"ssid":"...","password":"..."}
       WIFICFG:RESET
   - 电脑端用 Chrome/Edge 打开 tools/serial-wifi-provision/index.html
     （或运行 start-local-server.ps1），选择设备 COM 口即可扫描/配网。
   - 协议与排查见 docs/serial-wifi-provision.md。
   - 配置项: CONFIG_SERIAL_PROVISION_ENABLED（默认 y）
2. 继承 v2.5.3 的全部改动（控制台设备令牌 / OTA 结果上报 / 强制升级门禁等）

文件说明
--------
  merged-binary.bin               整片烧录镜像（0x0 起），不能作为 OTA 应用镜像
  xiaozhi.bin                     应用镜像（OTA 升级/管理后台上传使用）
  bootloader.bin                  引导程序（0x0）
  partition-table.bin             分区表（0x8000）
  ota_data_initial.bin            OTA 数据分区初始镜像（0xd000）
  generated_assets.bin            资源镜像（0x800000）
  v2.5.4_bread-compact-wifi.zip   官方发布压缩包
  SHA256SUMS.txt                  校验值

整片烧录（Windows）:
  .\flash.ps1                       # 默认 COM3

注意: 旧版 v2.5.3 固件在 ../v2.5.3_bread-compact-wifi/，可用于回退。
