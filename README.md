# XiaoZhi ESP32 + DeepSeek Backend

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

- OTA URL: `http://HOST_IP:8003/xiaozhi/ota/`
- WebSocket: `ws://HOST_IP:8000/xiaozhi/v1/`
- DeepSeek key: `/etc/xiaozhi-backend.env` (`DEEPSEEK_API_KEY=sk-...`), restart service after change

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

## Security

- No private API keys are stored in this repository.
- Runtime secrets (DeepSeek API key) live outside the repo: `/etc/xiaozhi-backend.env` (root-only, 0600).
- `.gitignore` excludes runtime config (`backend/data/`), ASR models (`backend/models/`), virtual environments and backups.
- Third-party demo/share keys from upstream source (e.g. QWeather shared key in `upstream/config.yaml`) are replaced with placeholders (`YOUR_...`).
