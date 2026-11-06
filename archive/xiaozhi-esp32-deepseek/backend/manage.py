"""Configure and validate the local XiaoZhi/DeepSeek deployment without logging keys."""
import argparse
import hashlib
import ipaddress
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

try:
    import yaml
except ImportError:
    raise SystemExit("缺少 PyYAML。请运行 python -m pip install -r backend/requirements-tools.txt")

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "data" / ".config.yaml"
MODEL = ROOT / "models" / "SenseVoiceSmall" / "model.pt"
API_BASE = "https://api.deepseek.com/v1"
KEY_PLACEHOLDER = "DEEPSEEK_API_KEY"


class SetupError(Exception):
    pass


def load_config(path=CONFIG):
    try:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        # YAML parser errors may include the line containing a secret.
        raise SetupError("无法读取配置：请检查 backend/data/.config.yaml 的路径、UTF-8 编码和 YAML 缩进。") from None
    if not isinstance(config, dict):
        raise SetupError("配置顶层必须是 YAML 对象。")
    return config


def normalize_host(host):
    host = host.strip()
    if not host or "YOUR_" in host.upper() or any(c in host for c in "/\\@?# "):
        raise SetupError("请填写设备可访问的服务器 IP 或域名，不带协议、端口或路径。")
    raw = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        if ":" in raw or not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", raw):
            raise SetupError("服务器 IP 或域名格式无效。") from None
        if raw.lower() == "localhost" or raw.lower().endswith(".localhost") or re.fullmatch(r"[0-9.]+", raw):
            raise SetupError("请使用有效的局域网 IP 或域名，不能使用 localhost。")
        if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in raw.split(".")):
            raise SetupError("服务器域名格式无效。")
        return raw
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise SetupError("请使用设备可访问的局域网 IP，不能使用回环、未指定、组播或链路本地地址。")
    return f"[{address}]" if address.version == 6 else str(address)


def configure_server(host, config_path=CONFIG, kconfig_path=None):
    host = normalize_host(host)
    kconfig_path = Path(kconfig_path or ROOT.parent / "main" / "Kconfig.projbuild")
    config_path = Path(config_path)
    config = load_config(config_path)
    source = kconfig_path.read_text(encoding="utf-8")
    ota_url = f"http://{host}:8003/xiaozhi/ota/"
    updated, count = re.subn(
        r'(config OTA_URL\s+string "Default OTA URL"\s+default )"[^"\n]*"',
        lambda match: match.group(1) + json.dumps(ota_url), source, count=1,
    )
    if count != 1:
        raise SetupError("未找到固件 OTA_URL 默认值，请手动在 menuconfig 中设置 OTA URL。")
    config.setdefault("server", {})["websocket"] = f"ws://{host}:8000/xiaozhi/v1/"
    config["server"]["vision_explain"] = f"http://{host}:8003/mcp/vision/explain"
    # Replace only address strings to preserve comments and the user's key exactly.
    text = config_path.read_text(encoding="utf-8")
    for name in ("websocket", "vision_explain"):
        text, matches = re.subn(
            rf"^(  {name}:).*$", lambda m: m.group(1) + " " + json.dumps(config["server"][name]),
            text, count=1, flags=re.MULTILINE,
        )
        if matches != 1:
            raise SetupError(f"配置中缺少 server.{name}，请按示例恢复该字段。")
    config_path.write_text(text, encoding="utf-8")
    kconfig_path.write_text(updated, encoding="utf-8")
    return ota_url


def get_llm(config):
    try:
        if config["selected_module"]["LLM"] != "DeepSeekLLM":
            raise SetupError("selected_module.LLM 必须是 DeepSeekLLM。")
        llm = config["LLM"]["DeepSeekLLM"]
        if llm["type"] != "openai" or llm["base_url"].rstrip("/") != API_BASE:
            raise SetupError("DeepSeekLLM 必须使用 openai 类型及 https://api.deepseek.com/v1 地址。")
        key = llm["api_key"]
        if not isinstance(key, str) or key == KEY_PLACEHOLDER or not key.strip() or key != key.strip() or any(c.isspace() for c in key):
            raise SetupError("请填写 backend/data/.config.yaml → LLM.DeepSeekLLM.api_key（当前为空、占位符或含空白）。")
        if not isinstance(llm["model_name"], str) or not llm["model_name"].strip():
            raise SetupError("LLM.DeepSeekLLM.model_name 不能为空。")
    except (KeyError, TypeError, AttributeError):
        raise SetupError("缺少 DeepSeek 模型配置，请参照 backend/config.example.yaml 恢复字段。") from None
    return llm


def validate(config, model_path=MODEL, skip_model=False):
    get_llm(config)
    try:
        server = config["server"]
        ws = urlsplit(server["websocket"])
        host = normalize_host(ws.hostname or "")
        if ws.scheme != "ws" or ws.netloc != f"{host}:8000" or ws.path != "/xiaozhi/v1/" or ws.query or ws.fragment:
            raise SetupError("server.websocket 必须使用 ws://服务器IP:8000/xiaozhi/v1/；请运行 configure 命令。")
        if server["port"] != 8000 or server["http_port"] != 8003:
            raise SetupError("当前部署固定使用 8000/8003 端口；修改端口需要同步 Compose 和固件配置。")
        if config.get("manager-api", {}).get("url") or config.get("read_config_from_api"):
            raise SetupError("当前交付使用本地配置，请关闭 manager-api.url 和 read_config_from_api。")
        if server.get("mqtt_gateway"):
            raise SetupError("当前交付使用 WebSocket，请保持 server.mqtt_gateway 为空。")
        for name, expected in {"ASR": "FunASR", "TTS": "EdgeTTS", "VAD": "SileroVAD"}.items():
            if config["selected_module"].get(name) != expected:
                raise SetupError(f"当前部署的 selected_module.{name} 应为 {expected}。")
    except (KeyError, TypeError, ValueError):
        raise SetupError("服务器配置格式无效，请检查 server 与 selected_module。") from None
    if not skip_model:
        model_path = Path(model_path)
        if not model_path.is_file() or model_path.stat().st_size < 1024 * 1024:
            raise SetupError("缺少有效的 SenseVoiceSmall/model.pt；请运行 python backend/manage.py download-model。")


def test_api(config, opener=urllib.request.urlopen):
    llm = get_llm(config)
    payload = {
        "model": llm["model_name"],
        "messages": [{"role": "user", "content": "请只回复：DeepSeek连接成功"}],
        "stream": True, "max_tokens": 64, "thinking": {"type": "disabled"},
    }
    request = urllib.request.Request(
        API_BASE + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + llm["api_key"], "Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    pieces = []
    try:
        with opener(request, timeout=60) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("error"):
                    raise SetupError("DeepSeek 返回流式错误，请检查账号、额度和模型可用性。")
                choices = event.get("choices") or []
                if choices:
                    content = choices[0].get("delta", {}).get("content")
                    if isinstance(content, str):
                        pieces.append(content)
    except urllib.error.HTTPError as error:
        reasons = {400: "请求参数不被模型支持", 401: "密钥无效", 402: "账号余额不足", 404: "模型或接口不可用", 429: "请求限流或额度不足"}
        raise SetupError(f"DeepSeek HTTP {error.code}：{reasons.get(error.code, '服务请求失败')}。") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError, AttributeError):
        raise SetupError("DeepSeek 连接失败或响应格式异常，请检查网络、代理及模型设置。") from None
    answer = "".join(pieces).strip()
    if not answer:
        raise SetupError("DeepSeek 未返回可朗读的文本，请检查模型设置。")
    return answer[:1024]


def download_model():
    meta = json.loads((ROOT / "upstream-version.json").read_text(encoding="utf-8"))
    expected = meta["model_sha256"]
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if MODEL.is_file():
        with MODEL.open("rb") as existing:
            existing_digest = hashlib.sha256()
            while block := existing.read(1024 * 1024):
                existing_digest.update(block)
            if existing_digest.hexdigest() == expected:
                print("模型已存在，SHA-256 校验通过。")
                return
    temp = MODEL.with_suffix(".pt.download")
    print("正在下载 SenseVoiceSmall 权重，文件较大；请等待完成。")
    try:
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(meta["model_url"], timeout=120) as response, temp.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
                digest.update(block)
                total += len(block)
        if digest.hexdigest() != expected:
            raise SetupError("模型 SHA-256 不匹配；下载可能中断或上游文件已变化，未替换现有模型。")
        temp.replace(MODEL)
        print(f"模型下载完成，SHA-256 校验通过，大小 {total // (1024 * 1024)} MiB。")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SetupError("模型下载失败，请检查网络后重试；也可按说明手动下载并校验。") from None
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure", help="同步服务器 IP 到后台与固件默认配置")
    configure.add_argument("--host", required=True)
    check = sub.add_parser("check", help="离线检查配置、密钥占位符和模型文件")
    check.add_argument("--skip-model", action="store_true")
    sub.add_parser("test-api", help="实际发送一次小额计费的 DeepSeek 流式请求")
    sub.add_parser("download-model", help="下载并校验本地 ASR 模型权重")
    args = parser.parse_args()
    try:
        if args.command == "configure":
            url = configure_server(args.host)
            print(f"后台地址和固件 OTA 默认值已同步：{url}")
            print("已有 sdkconfig/NVS 仍须按说明手动更新 OTA URL。密钥内容未改动。")
        elif args.command == "check":
            validate(load_config(), skip_model=args.skip_model)
            print("本地检查通过；密钥是否有效需运行 test-api 验证。")
        elif args.command == "test-api":
            print("DeepSeek 流式接口返回：" + test_api(load_config()))
        else:
            download_model()
        return 0
    except (SetupError, OSError) as error:
        print(f"检查未通过：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
