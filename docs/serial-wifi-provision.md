# 串口配网（浏览器 Web Serial 工具）

本功能让设备通过 **USB/UART 串口** 接收 WiFi 配网指令，配合浏览器页面（无需安装串口助手）完成配网。

- 固件：`device/main/serial_provision.{h,cc}`（`CONFIG_SERIAL_PROVISION_ENABLED`，默认开启）
- 网页工具：`tools/serial-wifi-provision/`（`index.html` + 本地服务脚本）
- 适用固件版本：v2.5.4 及以上

## 1. 使用步骤

1. 用 **Chrome / Edge** 打开网页工具（任选一种方式）：
   - 直接双击 `tools/serial-wifi-provision/index.html`（Chrome 将 `file://` 视为安全上下文），或
   - 运行 `tools/serial-wifi-provision/start-local-server.ps1`，自动在 `http://127.0.0.1:8099/` 打开。
   - ⚠️ 不要用 `http://192.168.10.200:8004`（非 localhost 的 http 页面没有 Web Serial 权限）。
2. 设备用 USB 线连接电脑，确认设备管理器中对应的 COM 口（烧录固件用的同一个口即可）。
3. 关闭占用该串口的程序（串口监视器、idf.py monitor、烧录工具等）。
4. 点击「选择串口并连接」→ 选择对应 COM 口 → 自动以 115200 打开并发送 `PING`。
5. 点击「扫描附近 WiFi」→ 从下拉框选择或手动输入 SSID、密码 → 「保存并连接 WiFi」。
6. 设备收到指令后立即尝试连接；日志区会显示 `OK` → `CONNECTING`，随后点「刷新状态」查看 IP。

## 2. 串口协议（115200 8N1，UART0，行分隔）

| 电脑 → 设备 | 说明 |
|---|---|
| `WIFICFG:PING` | 测试通讯 |
| `WIFICFG:STATUS` | 查询设备 WiFi 状态 |
| `WIFICFG:SCAN` | 扫描附近 WiFi（阻塞约 1~3 秒） |
| `WIFICFG:SET:{"ssid":"名称","password":"密码"}` | 保存 WiFi 并立即连接 |
| `WIFICFG:RESET` | 清除已保存 WiFi 并重启进入配网模式 |

设备 → 电脑（前缀均为 `WIFICFG:`，可与启动日志噪声共存）：

| 响应 | 说明 |
|---|---|
| `WIFICFG:READY` | 串口配网模块已启动 |
| `WIFICFG:PONG` | PING 响应 |
| `WIFICFG:STATUS:{...}` | 状态 JSON：`initialized/connected/config_mode/ssid/ip/rssi/ap_ssid/saved_ssids` |
| `WIFICFG:SCAN:[{"ssid":..,"rssi":..}, ...]` | 扫描结果（按信号强度排序，最多 20 个） |
| `WIFICFG:OK:{"ssid":"...","saved":true}` | 保存成功 |
| `WIFICFG:CONNECTING` | 正在连接 WiFi |
| `WIFICFG:RESET_OK` | 已清除，设备即将重启 |
| `WIFICFG:ERR:...` | 错误（`bad_json`/`ssid_required`/`scan_failed:...`/`not_initialized` 等） |

## 3. 固件编译

```bash
get_idf
cd ~/ESP32-xiaozhiAI/device
python scripts/build.py bread-compact-wifi --name bread-compact-wifi --language zh-CN --zip
```

- 版本：`device/CMakeLists.txt` 中 `PROJECT_VER`（v2.5.4）
- 配置项：`idf.py menuconfig` → Xiaozhi Assistant → `Enable UART serial WiFi provisioning`（默认 y）
- 产物：`device/build/merged-binary.bin`（整片烧录）、`device/build/xiaozhi.bin`（OTA 应用镜像）

## 4. 注意事项与排查

1. **串口类型**：默认控制台使用 UART0（`CONFIG_ESP_CONSOLE_UART_DEFAULT=y`），请使用设备 DevKit 的 **UART/USB 转串口口**（CH340/CP210x 等）；若使用 ESP32-S3 原生 USB 口，则需要改用 USB Serial/JTAG 方案（当前未启用）。
2. **浏览器要求**：Chrome/Edge 89+，页面必须处于安全上下文（`file://`、`http://localhost`、`https://`）。不支持 Firefox/Safari。
3. **串口被占用**：报错 `Failed to open serial port` 时，关闭串口监视器/IDE 串口窗口后重试。
4. **收不到响应**：确认波特率 115200；按一下设备复位键，日志区出现 `WIFICFG:READY` 即模块正常。
5. **日志噪声**：设备启动日志与配网响应共用串口，网页工具会自动筛选 `WIFICFG:` 行，其余内容以灰色显示。
6. **忘记 WiFi / 换网络**：点「清除已保存 WiFi」，设备重启后进入原有 AP 配网模式，也可再次用本工具配网。
7. **保留原有 AP 网页配网**：AP 配网（手机连 `Xiaozhi-XXXX` 打开 192.168.4.1）与本工具互不冲突，任选其一。
