# XiaoZhi ESP32 + DeepSeek Backend

## 新增中文管理后台

```bash
python backend/console/server.py --host 127.0.0.1 --port 8004 --data-dir backend/data/console
```

使用 Python 3.10+，管理后台本身仅依赖标准库。浏览器打开 <http://127.0.0.1:8004>。
后台配置、上传文件和审计记录保存在 `backend/data/console`。首次使用为空数据，不包含虚构设备或运行指标。

设备/语音服务接入、容器部署和测试步骤见 [后台部署说明](docs/console-deployment.md)；
每项功能的实际覆盖和待接入项见 [功能清单验收对照](docs/feature-coverage.md)。
上传固件须为 ESP 应用镜像，不能使用整片合并烧录镜像。当前交付未连接真实设备或调用付费模型/克隆服务。
`firmware/` 中随原工程保留的 `.bin` 是旧版 v2.5.3，**不含本次源码修改**；见 [固件目录说明](firmware/README.md)。

Repository layout (four categories):

```
ESP32-xiaozhiAI/
├── backend/                          # 1) Backend service source (xiaozhi-esp32-server + DeepSeek)
│   ├── upstream/                     #    Python backend source
│   ├── manage.py                     #    config tool: configure / check / test-api / download-model
│   ├── config.example.yaml           #    config template (runtime config: data/.config.yaml, not tracked)
│   ├── data/                         #    runtime config (not tracked)
│   ├── models/                       #    ASR model SenseVoiceSmall (not tracked)
│   ├── Dockerfile / docker-compose.yml
│   └── requirements-tools.txt
├── device/                           # 2) Device firmware source (ESP32-S3 / ESP-IDF v6.1)
│   ├── main/                         #    application source (audio / display / protocol / boards)
│   ├── scripts/                      #    build scripts (scripts/build.py is the entry point)
│   ├── partitions/                   #    partition tables
│   ├── docs/                         #    upstream firmware docs
│   └── sdkconfig.defaults*           #    per-chip / per-board defaults
├── firmware/                         # 3) Built firmware (bin / merged image / flash script / checksums)
│   └── v2.5.3_bread-compact-wifi/
├── docs/                             # 4) Documentation
│   ├── backend-native-deployment.md
│   ├── docker-deployment-progress.md
│   ├── deepseek-deployment-guide.md
│   ├── deepseek-validation-record.txt
│   └── delivery-sha256sums.txt
├── archive/                          #    Legacy copy (xiaozhi-esp32-deepseek)
└── README.md
```

## Backend service (server 192.168.10.200)

```bash
sudo systemctl status xiaozhi-backend
sudo systemctl restart xiaozhi-backend
tail -f /home/dev/xiaozhi_backend.log
```

- OTA URL: `http://192.168.10.200:8003/xiaozhi/ota/`
- WebSocket: `ws://192.168.10.200:8000/xiaozhi/v1/`
- DeepSeek key: `/etc/xiaozhi-backend.env` (`DEEPSEEK_API_KEY=sk-...`), restart service after change

## Serial WiFi provisioning (firmware v2.5.4+)

Connect the device by USB/UART, then open `tools/serial-wifi-provision/index.html`
in Chrome/Edge (or run `start-local-server.ps1`) to pick the COM port, scan WiFi
and save credentials. Protocol and troubleshooting: `docs/serial-wifi-provision.md`.

## Build firmware

```bash
get_idf
cd ~/ESP32-xiaozhiAI/device
python scripts/build.py --list-boards
python scripts/build.py bread-compact-wifi --name bread-compact-wifi --language zh-CN --zip
```

Build output: `device/build/`; copy merged image to `firmware/` for release.

## Flash firmware (Windows)

```powershell
cd firmware\v2.5.3_bread-compact-wifi
.\flash.ps1
```

See `firmware/v2.5.3_bread-compact-wifi/README.txt` and `docs/backend-native-deployment.md`.
