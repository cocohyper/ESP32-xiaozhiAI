# Docker + 小智后台 部署进度（2026-11-06）

## 已完成
- Docker Engine **29.1.3**（Ubuntu 源 docker.io 包），Docker Compose **v2.40.3**（docker-compose-v2）
- 服务已启用：`systemctl enable --now docker`，状态 active
- 用户 `dev` 已加入 `docker` 组（新会话直接可用 docker，无需 sudo）
- Docker 守护进程代理已配置（拉取镜像走本机代理 192.168.10.68:7897）：
  - `/etc/systemd/system/docker.service.d/http-proxy.conf`
  - `/etc/docker/daemon.json`（日志限制 + max-download-attempts=30 + max-concurrent-downloads=3）
- ASR 模型已下载并校验通过：
  - `backend/models/SenseVoiceSmall/model.pt`（893 MB）
  - SHA-256 = 833ca2dcfdf8ec91bd4f31cfac36d6124e0c459074d5e909aec9cabe6204a3ea ✅
- 后台运行配置已生成并同步本机 IP：
  - `backend/data/.config.yaml`（由 config.example.yaml 创建）
  - websocket = ws://192.168.10.200:8000/xiaozhi/v1/
  - OTA 默认值（main/Kconfig.projbuild）= http://192.168.10.200:8003/xiaozhi/ota/
- 后台工具依赖：`/home/dev/ESP32-xiaozhiAI/.venv-tools`（Python 3.12 + PyYAML 6.0.3），manage.py 可用
- compose 语法检查通过：`docker compose -f backend/docker-compose.yml config --quiet`
- hello-world 测试镜像拉取/运行正常（验证 docker + 代理链路）

## 未完成 / 待办
1. **基础镜像未完整拉取**
   - 镜像：ghcr.io/xinnan-tech/xiaozhi-esp32-server@sha256:c94ab84085f843a2c329019ff77cffca7bc3832e4cf55878ef8cb613985d4f37
   - 大小：3.25 GB（9 层）；已下载大部分层，中途代理断流（unexpected EOF）导致失败
   - 续拉命令：`docker pull ghcr.io/xinnan-tech/xiaozhi-esp32-server@sha256:c94ab84085f843a2c329019ff77cffca7bc3832e4cf55878ef8cb613985d4f37`
   - 说明：docker 守护进程已配置代理；如再断流可直接重复执行（已下载层会复用）
2. **DeepSeek API Key 未填写**
   - 文件：`backend/data/.config.yaml` 第 41 行附近
   - 需把 `api_key: "REPLACE_WITH_YOUR_DEEPSEEK_API_KEY"` 换成真实密钥（保留引号）
3. **镜像构建方式注意**（拉取完成后再做）
   - `docker compose build` 使用 BuildKit 时，元数据请求不走守护进程代理，可能报 ghcr.io TLS 超时
   - 备选方案 A：`DOCKER_BUILDKIT=0 docker compose -f backend/docker-compose.yml build`
   - 备选方案 B（最稳妥）：先 `docker pull` 基础镜像，再手工创建镜像：
     ```bash
     cd backend
     CID=$(docker create ghcr.io/xinnan-tech/xiaozhi-esp32-server@sha256:c94ab84085f843a2c329019ff77cffca7bc3832e4cf55878ef8cb613985d4f37)
     docker cp upstream/. $CID:/opt/xiaozhi-esp32-server/
     docker cp manage.py upstream-version.json $CID:/opt/xiaozhi-esp32-server/
     docker commit --change 'CMD ["sh","-c","python manage.py check && exec python app.py"]' $CID xiaozhi-deepseek:local
     docker rm $CID
     ```
4. **启动服务（填好 Key 后）**
   ```bash
   cd ~/ESP32-xiaozhiAI/device
   docker compose -f backend/docker-compose.yml up -d --no-build
   docker compose -f backend/docker-compose.yml ps
   docker compose -f backend/docker-compose.yml logs -f --tail 100
   ```
5. **验证**
   - OTA 接口：`curl http://192.168.10.200:8003/xiaozhi/ota/`
   - 设备配网页填 OTA 地址：http://192.168.10.200:8003/xiaozhi/ota/

## 相关日志
- `/home/dev/docker_install.log`（安装日志）
- `/home/dev/docker_pull.log`、`/home/dev/docker_pull2.log`（镜像拉取日志）
- `/home/dev/backend_deploy.log`（构建/测试日志）

## 补充检查结果（2026-11-06 20:35）
- 外网连通性（后台运行必需）：
  - https://api.deepseek.com/v1/models → 401（可达，未带密钥，正常）
  - https://speech.platform.bing.com/ → 400（EdgeTTS 可达，正常）
  - https://modelscope.cn/ → 302（可达，正常）
- 端口 8000/8003 空闲；模型挂载源文件与 data 目录都存在
- ⚠️ 发现项目自带检查脚本的小 bug：backend/manage.py 第 22 行
  KEY_PLACEHOLDER = "DEEPSEEK_API_KEY"，但示例配置里的实际占位符是
  "REPLACE_WITH_YOUR_DEEPSEEK_API_KEY"，两者不匹配，导致
  `python backend/manage.py check` 会误报"本地检查通过"。
  → 仍必须手动把第 41 行 api_key 换成真实密钥，不能依赖 check 的结果。

## 代理已取消（2026-11-06 20:40）
- 已删除 Docker 守护进程代理配置：/etc/systemd/system/docker.service.d/http-proxy.conf
- 已重启 docker，`docker info` 不再显示 HTTP/HTTPS Proxy
- daemon.json 中其他配置（日志限制、下载重试）保留
- 后续拉镜像/下载都走直连；若直连太慢可临时加回代理（192.168.10.68:7897）
