【原始旧版固件，不含本次源码修改】
本目录 .bin 和固件压缩包均为用户原工程附带的 v2.5.3 构建产物。
本次未运行 ESP-IDF 编译，也未连接真实设备；新版源码需重新编译后验证。
以下部署、串口和构建信息为原交付记录。

小智 ESP32 固件 v2.5.3 · bread-compact-wifi
================================================
构建日期：2026-11-06
芯片：ESP32-S3（Xtensa 双核 240MHz，带 PSRAM）
板型：bread-compact-wifi（面包板 DIY 方案，默认 OLED 屏）
Flash：16MB（DIO / 80MHz）
分区表：partitions/v2/16m.csv
语言：中文（zh-CN），唤醒词：你好小智（nihaoxiaozhi）
ESP-IDF：v6.1

后台信息（本次编译已写入固件）
- OTA 地址：http://192.168.10.200:8003/xiaozhi/ota/
- WebSocket：ws://192.168.10.200:8000/xiaozhi/v1/

文件说明
--------
merged-binary.bin                整片镜像（推荐烧录，地址 0x0，已包含所有分区）
bootloader.bin                   引导（0x0）
partition-table.bin              分区表（0x8000）
ota_data_initial.bin             OTA 数据（0xd000）
xiaozhi.bin                      应用主程序（0x20000）
generated_assets.bin             资源包（0x800000）
v2.5.3_bread-compact-wifi.zip    官方格式合并包（内容即 merged-binary.bin）

烧录方法 A（推荐：整片烧录）
---------------------------
1. 安装 esptool（本机已安装 5.6.0，如换电脑执行）：
   python -m pip install esptool
2. 用 USB 数据线连接 ESP32-S3 开发板，查看串口号（本机当前为 COM3）
3. 执行烧录（把 COM3 换成你的实际串口）：
   python -m esptool --chip esp32s3 -p COM3 -b 460800 --before default-reset --after hard-reset write-flash --flash-mode dio --flash-freq 80m --flash-size 16MB 0x0 merged-binary.bin
   或者直接双击/运行 flash.ps1（默认 COM3）
4. 烧录完成后按一下开发板复位键

烧录方法 B（分文件烧录，与 build/flash_args 一致）
------------------------------------------------
python -m esptool --chip esp32s3 -p COM3 -b 460800 --before default-reset --after hard-reset write-flash --flash-mode dio --flash-freq 80m --flash-size 16MB 0x0 bootloader.bin 0x8000 partition-table.bin 0xd000 ota_data_initial.bin 0x20000 xiaozhi.bin 0x800000 generated_assets.bin

首次配网（让设备连上后台）
-------------------------
1. 设备开机后会创建热点 Xiaozhi-XXXX（部分板卡开机时按 BOOT 键进入配网模式）
2. 手机/电脑连接该热点，浏览器打开 http://192.168.4.1
3. 选择家里的 Wi-Fi 并输入密码
4. 打开「高级 / 高级设置」，把 OTA 地址填为：
   http://192.168.10.200:8003/xiaozhi/ota/
5. 保存并重启设备

重要提示
--------
1. 如果设备之前连接过官方服务器，设备 NVS 里保存的旧 OTA 地址会「覆盖」固件里的默认值，
   所以烧录后必须按上面第 4 步把 OTA 地址改成你的后台地址。
   也可以烧录前先整片擦除（会清除所有配置）：
   python -m esptool --chip esp32s3 -p COM3 -b 460800 erase-flash
2. 固件中不包含任何 DeepSeek API Key（安全设计）；Key 只配置在后台。
3. 后台服务已部署在 192.168.10.200（systemd 服务 xiaozhi-backend，开机自启）。
   当前后台还差真实 DeepSeek API Key，填入后执行：sudo systemctl restart xiaozhi-backend
4. 对讲/语音链路验证：设备连上后台后，说「你好小智」唤醒，提问应能听到回复。

文件校验（SHA-256）
------------------
见同目录 SHA256SUMS.txt
