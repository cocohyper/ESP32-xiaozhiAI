# 小智后台（DeepSeek）原生部署说明（不用 Docker）

## 运行方式
- 服务名：`xiaozhi-backend`（systemd，已开机自启、崩溃自动重启）
- 运行目录：`/home/dev/ESP32-xiaozhiAI/backend/upstream`
- Python 环境：`/home/dev/ESP32-xiaozhiAI/.venv-server`（Python 3.12.16 + torch 2.2.2+cpu）
- 日志：`/home/dev/xiaozhi_backend.log`
- 配置：`backend/data/.config.yaml`（通过 `backend/upstream/data` 软链读取）
- ASR 模型：`backend/models/SenseVoiceSmall/model.pt`（通过软链挂到 upstream/models/SenseVoiceSmall/）

## 常用命令
```bash
sudo systemctl status xiaozhi-backend     # 状态
sudo systemctl restart xiaozhi-backend    # 重启（改配置后）
sudo systemctl stop xiaozhi-backend       # 停止
tail -f /home/dev/xiaozhi_backend.log     # 看日志
```
或直接用脚本：`~/xiaozhi-backend-start.sh`、`~/xiaozhi-backend-stop.sh`、`~/xiaozhi-backend-status.sh`

## 地址
- 设备 OTA 地址：http://192.168.10.200:8003/xiaozhi/ota/
- WebSocket：ws://192.168.10.200:8000/xiaozhi/v1/
- 端口：8000（WebSocket）、8003（OTA HTTP）

## 已验证
- 服务启动成功；LLM(DeepSeekLLM)/VAD(SileroVAD)/ASR(FunASR+SenseVoiceSmall) 组件全部初始化成功
- ASR 模型加载成功：Loading ckpt: models/SenseVoiceSmall/model.pt, All keys matched successfully
- OTA 接口返回 200，正确下发 ws://192.168.10.200:8000/xiaozhi/v1/
- 8000/8003 端口正常监听

## 还差什么
- `backend/data/.config.yaml` 第 41 行仍需填真实 DeepSeek API Key（当前仍是占位符）
- 填写后执行：`sudo systemctl restart xiaozhi-backend`
- 验证：`~/ESP32-xiaozhiAI/.venv-tools/bin/python backend/manage.py test-api`（会发一次小额计费请求）

## 说明
- Docker 已安装但未使用（可保留，也可以后 `sudo apt remove docker.io docker-compose-v2` 卸载）
- torch 是本机新安装的：Windows 本机与服务器此前都没有 torch（RT-DETR 用的是 PaddlePaddle）

## 环境变量配置 DeepSeek Key（2026-11-06 更新）
后台已支持从环境变量 `DEEPSEEK_API_KEY` 读取密钥（优先级高于配置文件）。

### 配置方式（推荐）
```bash
sudo nano /etc/xiaozhi-backend.env
# 写入（去掉行首 #）：
# DEEPSEEK_API_KEY=sk-你的真实密钥
sudo systemctl restart xiaozhi-backend
```

### 验证
```bash
sudo systemctl status xiaozhi-backend
tail -n 30 /home/dev/xiaozhi_backend.log     # 看到 401 就说明 Key 无效；正常对话日志无 ERROR
~/ESP32-xiaozhiAI/.venv-tools/bin/python backend/manage.py test-api   # 可选，发一次小额请求
```

### 说明
- 配置文件中 api_key 仍可填写作为后备（环境变量优先）
- 修改键后必须重启服务生效
- 环境变量文件 `/etc/xiaozhi-backend.env` 权限 600，仅 root 可读
- 已修复 manage.py 占位符检查 bug（此前会把占位符误判为通过）

## 故障说明："主人，小智现在有点忙，我们稍后再试吧"
- 这是后台 LLM 调用失败时的兜底播报（TTS 固定文案），不是设备故障
- 2026-11-06 本次原因：DeepSeek 返回 401（api_key 填的是占位符 "DEEPSEEK_API_KEY"，不是真实密钥）
- 解决：填真实 Key（环境变量或配置文件）→ 重启服务

## 目录误删恢复记录（2026-11-06 14:30）
- 误删目录：`/home/dev/ESP32-xiaozhiAI/device`（整个项目）
- 恢复来源：本地 git 远程引用 `remotes/github/main`（提交 6ff4103，含 2074 个文件）；
  用户上传的 `ESP32-xiaozhiAI-main.zip` 已核对，源码与恢复结果一致（仅差环境变量补丁）
- 恢复内容：
  1. 源码目录（42MB/2074 文件）从 git 恢复
  2. `backend/data/.config.yaml` 从 config.example.yaml 重建，并同步服务器 IP 192.168.10.200
  3. ASR 模型重新下载：893MB，SHA-256 校验通过
  4. upstream 的 data / model 软链重建
  5. 环境变量 Key 补丁、manage.py 修复补丁重新应用
  6. managed_components 重建：73 个组件（771MB，来自本地缓存，无大额下载）
- 验证结果：后台服务 active，OTA 200，设备连接后正常对话（你好呀 / 我是小智…），
  LLM/VAD/ASR/TTS 全部初始化成功
- 压缩包备份保存在：`/home/dev/ESP32-xiaozhiAI/backups/ESP32-xiaozhiAI-main.zip`
- 注意：仓库远程 `6ff4103` 里包含 .venv-server/.venv-tools 等虚拟环境目录（不建议提交），
  建议加入 .gitignore 并 `git rm -r --cached` 清理
