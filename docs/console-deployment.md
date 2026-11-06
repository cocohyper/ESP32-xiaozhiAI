# 小智中文管理后台：部署与验收

这次新增独立 Python 管理服务、SQLite 数据库及中文网页界面；通过可选桥接接入原有语音服务。它不替代 ESP-IDF 工具链、模型服务或设备固件。功能边界逐项列在 [功能清单验收对照](feature-coverage.md)。

## 1. 本机启动

在仓库根目录执行（Python 3.10+）：

```bash
python backend/console/server.py --host 127.0.0.1 --port 8004 --data-dir backend/data/console
```

打开 `http://127.0.0.1:8004`。管理服务仅使用 Python 标准库；交付的 `backend/console/static/` 为已构建页面，直接运行时无需安装前端依赖。首次启动没有演示设备和伪造指标；保存配置后写入 SQLite，刷新或重启后仍保留。

修改 React 页面源码后，在 `backend/console/frontend/` 执行 `npm ci`、`npm run build`，构建结果写入相邻的 `static/`。需要 Node.js 22+（推荐 24）。

`--data-dir` 内含 `console.sqlite3`、SQLite WAL 文件和 `uploads/`。请保留整个目录。模型密钥仅通过写入接口提交，不在管理 API 中回显；数据库本身仍保存这些密钥，备份应作为私密配置保管。

默认回环监听可直接访问。绑定非回环地址必须先设置至少 24 字符的 `CONSOLE_ADMIN_TOKEN`：

```powershell
$env:CONSOLE_ADMIN_TOKEN = '<自行生成的长随机访问令牌>'
python backend/console/server.py --host 0.0.0.0 --port 8004 --data-dir backend/data/console
```

浏览器需要输入同一访问令牌。部署至网络时，推荐通过已有 HTTPS 反向代理访问。不要将示例占位值用作真实令牌。

## 2. 与原有语音服务连接

管理服务与语音服务必须使用同一个数据库文件，并都能读取其目录。语音服务启动前设置绝对路径：

```bash
export XIAOZHI_CONSOLE_DB=/absolute/path/ESP32-xiaozhiAI-main/backend/data/console/console.sqlite3
cd backend/upstream
python app.py
```

Windows 对应设置：

```powershell
$env:XIAOZHI_CONSOLE_DB = (Resolve-Path 'backend/data/console/console.sqlite3').Path
Set-Location backend/upstream
python app.py
```

未设置 `XIAOZHI_CONSOLE_DB` 时保留原服务行为。该开关不等于启用旧 `manager-api`，不要为此修改 `read_config_from_api`。原有语音服务仍需其 ASR、TTS、模型及系统依赖。

设备原 OTA 地址仍为语音服务的 `/xiaozhi/ota/`，WebSocket 地址仍为 `/xiaozhi/v1/`。桥接通过 OTA / 对话链路采集设备信息、读取绑定配置并记录事件。管理页面保存配置与设备实际执行是不同状态。

## 3. 首次配置顺序

1. 启动管理服务，添加或等待设备通过 OTA 被发现。填写设备芯片、Flash、分组等资料。
2. 在模型网关创建通道，填写服务商、接口地址、模型名和密钥。先测试连通性，再启用。测试会发送一次轻量请求，可能产生服务商用量。
3. 创建角色、音色和交互配置，再在设备中绑定。原有 ASR / TTS 服务仍由语音服务配置提供。
4. 上传 ESP **应用镜像** `.bin`，登记版本及适配板型/芯片。整片合并烧录镜像不适合 OTA。
5. 创建发布策略，选择固件、分组或指定设备、比例及允许时间窗。默认要求设备报告供电和网络稳定，否则暂缓下发。
6. 连接真实设备后观察最近上报、事件和升级结果；没有回执的命令保持排队状态。

固件回退需要一份仍可使用的旧应用镜像。在发布策略中选择该旧版本并勾选“回退到指定旧版本（需已验证可用）”；后台将 `rollback=true` 的选版结果自动带上强制选版标志，无需另外勾选“强制升级”。通过正常 OTA 查询下发后才由终端执行。单独建立 `rollback` 队列命令不会触发当前桥接回退。回退固件仍须匹配板型/芯片、分区和升级环境。

私人记忆与设备管理指令需要额外的设备身份验证。在设备记录“更多操作”中生成独立接入凭证，将其写入该设备的 NVS `wifi/console_token` 字符串。固件也提供 `CONFIG_CONSOLE_DEVICE_TOKEN` 构建选项，可用于单设备测试；正式共享的固件包不应嵌入某台设备的凭证。优先使用 NVS 配置，且每台设备使用不同令牌。

修改后的固件在 OTA 与 WebSocket 请求中发送 `X-Console-Device-Token`。设备未提供或使用失效凭证时强制访客模式，不读取个人记忆、不执行管理 MCP 指令；已登记设备的未认证 OTA 请求不会覆盖管理资料或获取托管固件。轮换凭证后，旧连接下一轮会撤销个人上下文。请使用 HTTPS / WSS 传输凭证。MQTT 仍需网关转发认证字段，未完成该适配时保持访客。

桥接启用后默认采用访客模式，不读取个人记忆，也不保存个人对话正文。需要个人记忆时，先在管理台明确绑定用户并关闭该设备的访客模式。当前桥接使用本地按用户隔离的 `ConsoleMemory`，不会在后台继续调用原 mem0 / PowerMem；外部长记忆迁移与删除需要额外适配。用户身份取自管理员绑定，不信任请求头中的自报身份。

资源包可上传现成 `assets.bin` 或 PNG/GIF 素材。上传和映射配置不会自动训练 WakeNet/MultiNet，也不会自动将任意图片编译为兼容的 `assets.bin`。当前生成链路须另外接入。

## 4. API 契约

管理 API 在启用令牌时使用 `Authorization: Bearer <CONSOLE_ADMIN_TOKEN>`；JSON 请求需要 `Content-Type: application/json`。

| 方法与路径 | 用途 |
|---|---|
| `GET /api/bootstrap` | 全量管理集合、真实汇总、能力状态 |
| `GET /api/summary` | 已采集设备、事件、Token 等汇总 |
| `GET/POST /api/{collection}` | 列表 / 创建 |
| `GET/PUT/DELETE /api/{collection}/{id}` | 读取 / 修改 / 删除；审计事件只读 |
| `POST /api/models/test` | 测试模型连接；服务器记录与配置一致的指纹 |
| `POST /api/uploads?kind=firmware&filename=app.bin` | 原始二进制上传；资源使用 `kind=resources` |
| `GET /api/downloads/{upload_id}` | 设备文件下载；128 位随机标识作为下载能力凭据 |
| `POST /api/{collection}/{id}/clone` | 复制配置 |
| `POST /api/{collection}/{id}/rollback` | 支持版本化集合的配置回滚 |
| `POST /api/deletion_requests/{id}/confirm` | 确认删除本地记忆/对话并生成凭证 |
| `POST /api/devices/{id}/token` | 签发 / 轮换设备令牌；仅此次返回明文 |
| `POST /api/devices/{id}/commands` | 建立命令队列；不直接表示硬件已执行 |

集合包括设备、固件、发布、资源、模型、音色与切换规则、用户、记忆、对话、删除任务、视觉配置、角色、交互、提醒、快捷指令、安全规则、反馈、评测、实验、模板和事件。`resources`、`templates`、`interaction`、`roles`、`safety` 支持配置版本回滚。

设备扩展接口使用单独的设备 Bearer 令牌：

| 方法与路径 | 用途 |
|---|---|
| `GET /api/device/{device_id}/config` | 读取设备可见配置，不包含模型密钥 |
| `POST /api/device/{device_id}/telemetry` | 上报遥测与环境信息 |
| `GET /api/device/{device_id}/commands` | 获取待执行命令 |
| `POST /api/device/{device_id}/commands/{command_id}/ack` | 上报 `completed` / `failed` / `unsupported` 回执 |
| `POST /api/device/{device_id}/reminders/unsubscribe` | 传入 `reminder_id`，持久记录该设备退订 |

这些扩展接口需要终端或接入代理主动调用；旧固件不会自动轮询新接口。`queued` 状态仅表示任务已创建。当前 WebSocket 桥接可消费 `self_check`，通过真实 MCP `self.get_device_status` 检查连接与状态回环；ASR/TTS 回环仍为 `not_run`。其余未实现命令会得到 `unsupported` 回执，而不是伪造成功。`completed_local` 删除状态只证明本地 SQLite 已删除；外部 mem0 / PowerMem 删除状态仍需单独处理。

## 5. Docker

保留原语音服务部署方式。新增 Compose 覆盖文件共享管理数据库目录，后台端口默认仅发布到宿主机回环：

```bash
cd backend
export CONSOLE_ADMIN_TOKEN='<自行生成的至少24字符随机令牌>'
docker compose -f docker-compose.yml -f docker-compose.console.yml up -d --build
```

原服务所需 `data/` 配置和 `models/SenseVoiceSmall/model.pt` 必须按原部署说明准备。`Dockerfile.console` 先用 Node 24 构建 React 页面，再以 Python 3.12 标准库运行；原 `Dockerfile` 增加 `console/` 文件复制，原启动命令不变。两个服务共同使用 `console-data` 卷。若自行改运行用户，应保证两个容器的数据库读写身份一致。

Docker 镜像构建和真实 ASR/TTS 运行未在本次离线代码验收中执行。此处提供的是部署文件与操作步骤，不是已部署证明。

## 6. 外部调度

新增单次执行器可由 cron / systemd timer 调用；它不会自行安装或启用系统任务。先预览本次会建立的命令：

```bash
python backend/console/scheduler.py --data-dir backend/data/console --ota-check --ota-interval-minutes 1440 --dry-run
```

移除 `--dry-run` 后写入设备命令队列，等待设备/接入代理消费与回执。重复执行时 SQLite 去重，已有待执行 OTA 检查不会不断复制。建议外部调度每 5 分钟调用一次，OTA 检查间隔仍由 `--ota-interval-minutes` 控制。

日程提醒需设置 `enabled=true`、`type=日程提醒`、`schedule_time=HH:MM` 和 `message`；设备异常提醒会读取已上报的低电量（<20%）、升级失败和网络不稳定情况。两类提醒均遵守分组/设备筛选、允许时间窗、跨午夜免打扰、每日次数及设备退订记录。当前每个规则/设备每天至多排队一次，即使每日上限设置更高也不会增加频率。天气变化与长时间未互动提醒跳过并报告 `needs_integration`。

cron 示例（仅供部署人员按实际绝对路径安装）：

```cron
*/5 * * * * /usr/bin/python3 /opt/xiaozhi/backend/console/scheduler.py --data-dir /var/lib/xiaozhi-console --ota-check --ota-interval-minutes 1440
```

systemd 示例服务 `xiaozhi-console-scheduler.service`：

```ini
[Unit]
Description=XiaoZhi console scheduler tick

[Service]
Type=oneshot
User=xiaozhi
ExecStart=/usr/bin/python3 /opt/xiaozhi/backend/console/scheduler.py --data-dir /var/lib/xiaozhi-console --ota-check --ota-interval-minutes 1440
```

对应 timer `xiaozhi-console-scheduler.timer`：

```ini
[Unit]
Description=Run XiaoZhi scheduler every five minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit=xiaozhi-console-scheduler.service

[Install]
WantedBy=timers.target
```

`User` 和数据库目录应与实际管理服务一致。此交付未安装这些服务。命令入队不等于设备已响铃或已经检查升级；当前 WebSocket 消费桥接对提醒和主动 OTA 检查返回 `unsupported`，需提供对应终端/接入代理处理器。设备自主 OTA 查询链路仍可按发布策略选版。

## 7. 验证

```bash
python -m pip install -r backend/requirements-tools.txt
python -m unittest discover -s backend/tests -p "test_*.py" -v
```

管理服务核心测试仅依赖标准库；原部署回归测试需要 PyYAML。建议使用临时 `--data-dir` 做试验，不将测试记录混入实际管理库。2026-11-06 在 Python 3.12.14 上执行的后台回归共 **60 项通过**（管理服务与调度 19 项、桥接 25 项、原部署 16 项）；真实模型网络调用以本地 HTTP 测试服务替代，未消耗服务商凭证。

Chrome + Playwright 浏览器验收通过 23 个流程，包括 23 个导航页签、设备/角色/模板创建编辑、模板回滚与解绑、搜索、未测试模型禁启用、删除确认、服务异常重连、管理员登录和刷新持久化；另验证了芯片限制、PNG 上传预览与 neutral 默认图校验、摄像头拒绝授权错误、键盘跳转和弹出菜单。1440 × 1000 桌面及 390 × 844 移动尺寸检查未发现页面级横向溢出或 JavaScript 异常。

原设备 host 测试在当前 Windows 环境执行 147 项，其中 25 项跳过、12 项环境相关错误（临时目录被占用、文本默认编码、缺 bash / C++ 编译器）。这些不构成固件编译通过证明；本机没有 ESP-IDF，须在项目指定的 ESP-IDF 6.1 环境重新编译并完成设备验收。

验收至少覆盖：新建后刷新仍存在；模型密钥不回显；未测试模型不能启用；不兼容芯片不能开启自定义唤醒词；无环境报告时不发布；上传非法固件被拒绝；待执行设备任务不误标成功；删除只影响指定用户；缺少真实数据时看板显示空态。

真实上线还需提供服务商凭证和已接线设备，验证 OTA、音频、声纹、相机、分区、供电及回滚。源码测试和管理界面检查不替代这些硬件验证。
