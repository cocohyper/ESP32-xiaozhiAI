# 固件目录说明

本目录包含从升级后源码重新编译的 ESP32-S3 固件（2026-11-06 15:47 UTC 构建）。

- 版本：`v2.5.3`（源码 PROJECT_VER 未变；内容包含 React 管理后台配套的设备端修改）
- 构建环境：ESP-IDF v6.1，target `esp32s3`，16MB Flash，`bread-compact-wifi` 板型
- 本次源码改动：控制台设备令牌、OTA/WS 上报 `X-Console-Device-Token`、强制升级门禁、OTA 结果上报

文件用途：
- `v2.5.3_bread-compact-wifi/merged-binary.bin`：整片烧录镜像，**不能**作为 OTA 应用镜像
- `v2.5.3_bread-compact-wifi/xiaozhi.bin`：应用镜像，可上传到管理后台/服务端用于 OTA
- `v2.5.3_bread-compact-wifi/v2.5.3_bread-compact-wifi.zip`：官方发布压缩包

> 已装 v2.5.3 的设备若要收到 OTA 推送，需要先把 `device/CMakeLists.txt` 的 `PROJECT_VER` 递增
> （如 2.5.4）再次编译，并按 `{device_model}_{version}.bin` 命名后放入服务端 `backend/data/bin/`。
