# 固件目录说明

| 目录 | 版本 | 说明 |
|---|---|---|
| `v2.5.4_bread-compact-wifi/` | **v2.5.4（最新）** | 新增串口配网（浏览器 Web Serial 工具）；含控制台配套改动 |
| `v2.5.3_bread-compact-wifi/` | v2.5.3 | 上一版（控制台配套改动，可用于回退） |

- 构建环境：ESP-IDF v6.1，target `esp32s3`，16MB Flash，`bread-compact-wifi` 板型
- v2.5.4 固件包含：串口配网（`WIFICFG:` 协议，UART0 115200）、控制台设备令牌、OTA/WS 上报 `X-Console-Device-Token`、强制升级门禁、OTA 结果上报
- `merged-binary.bin`：整片烧录镜像，**不能**作为 OTA 应用镜像
- `xiaozhi.bin`：应用镜像，可上传到管理后台/服务端用于 OTA

工具与文档：
- 串口配网网页工具：`tools/serial-wifi-provision/index.html`（Chrome/Edge，Web Serial）
- 协议与排查：`docs/serial-wifi-provision.md`

> 已装 v2.5.3 的设备可通过 OTA 升级到 v2.5.4（管理台上传 xiaozhi.bin 并创建发布策略；
> 或按 `{device_model}_{version}.bin` 命名放入服务端 `backend/data/bin/` 后走兼容扫描）。
