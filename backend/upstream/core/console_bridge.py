"""Optional local management bridge. Unset XIAOZHI_CONSOLE_DB preserves upstream behavior.

Only an administrator's device binding chooses identity; request headers never do.
The management database must be private to the service account.
"""
import copy
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import re
from datetime import datetime, timezone


def get_store():
    path = os.environ.get("XIAOZHI_CONSOLE_DB", "").strip()
    if not path:
        return None
    backend = str(Path(__file__).resolve().parents[2])
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from console.store import Store
    return Store.from_db(path)


def record(store, kind, device_id=None, **fields):
    """Observability must never turn a successful conversation into a failure."""
    if store is None:
        return
    try:
        store.record_event(kind, device_id=device_id, **fields)
    except Exception:
        pass


def console_authenticated(conn):
    headers = getattr(conn, "headers", None) or {}
    token = headers.get("x-console-device-token", "")
    if not token:
        token = headers.get("authorization", "").removeprefix("Bearer ")
    return bool(conn.console_store.authenticate_device(conn.device_id, token))


def authenticated_policy(conn, policy):
    conn.console_authenticated = console_authenticated(conn)
    if conn.console_authenticated:
        return dict(policy)
    if not getattr(conn, "console_auth_warning", False):
        record(conn.console_store, "console_auth_required", conn.device_id,
               message="Unverified device connection uses guest memory; MCP administration is unavailable")
        conn.console_auth_warning = True
    return {"guest_mode": True, "user_id": None, "visibility": "private"}


def check_ota(store, device_id, payload, current_version, board, device_token=""):
    verified = store.authenticate_device(device_id, device_token)
    if not verified and store.device_config(device_id).get("device"):
        record(store, "ota_unverified", device_id)
        return None
    status = payload.get("device_status", {})
    if not isinstance(status, dict):
        status = {}
    network = status.get("network", {})
    battery = status.get("battery", {})
    environment = {
        "network_stable": network.get("signal") in ("strong", "medium"),
        "battery_level": battery.get("level"),
        "charging": battery.get("charging"),
        "power_known": bool(battery),
        "power_stable": battery.get("charging") is True or isinstance(battery.get("level"), (int, float)) and battery["level"] >= 40,
    }
    if isinstance(payload.get("upgrade_environment"), dict):
        environment.update(payload["upgrade_environment"])
    flash = payload.get("flash_size", 0)
    flash_mb = round(flash / 1048576) if isinstance(flash, (int, float)) else 0
    result = payload.get("ota_result", {})
    store.upsert_device(
        device_id,
        chip=str(payload.get("chip_model_name", "")).upper().replace("ESP32S", "ESP32-S").replace("ESP32C", "ESP32-C").replace("ESP32P", "ESP32-P"),
        flash_mb=flash_mb,
        board=board,
        firmware_version=current_version,
        last_ota_check=datetime.now(timezone.utc).isoformat(),
        environment=environment,
        ota_result=result if isinstance(result, dict) else {},
        console_verified=verified,
    )
    record(store, "ota_check", device_id, firmware_version=current_version)
    if not verified:
        return None
    return store.select_firmware(device_id, current_version, board=board, environment=environment)


def words(value):
    if isinstance(value, list):
        return [str(x).strip().casefold() for x in value if str(x).strip()]
    return [x.strip().casefold() for x in re.split(r"[\n,，;；、]+", str(value or "")) if x.strip()]


def should_route_console_chat(conn, text):
    """Run protected requests through chat's deterministic guard before intent tools."""
    store = getattr(conn, "console_store", None)
    if store is None:
        return False
    try:
        safety = store.device_config(conn.device_id).get("safety") or {}
    except Exception:
        return True
    clean = str(text or "").strip().rstrip("。.!！?？")
    return (clean in ("忘记我", "删除我的记忆", "忘记这段对话", "重新开始", "这个回答不好")
            or bool(getattr(conn, "console_wakeup_pending", False))
            or bool(safety.get("enabled") and any(word in clean.casefold() for word in words(safety.get("keywords")))))


def experiment_overrides(store, device_id, device):
    """Stable allocation for supported text strategies only; no synthetic outcomes."""
    overrides, assignments = {}, []
    clock = (datetime.now(timezone.utc).timestamp() + 8 * 3600) % 86400
    clock = f"{int(clock // 3600):02d}:{int(clock % 3600 // 60):02d}"
    supported = {"开场白": "greeting", "回复风格": "style", "追问策略": "clarification"}
    for experiment in sorted(store.list("experiments"), key=lambda x: x.get("id", "")):
        target = supported.get(experiment.get("target"))
        if not experiment.get("enabled") or not target:
            continue
        if experiment.get("group") and experiment["group"] != device.get("group"):
            continue
        if experiment.get("region") and experiment["region"] != device.get("region"):
            continue
        start, end = experiment.get("start_time"), experiment.get("end_time")
        if start and end and start != end:
            if not (start <= clock < end if start < end else clock >= start or clock < end):
                continue
        bucket = int(hashlib.sha256((experiment["id"] + device_id).encode()).hexdigest()[:8], 16) % 100
        variant = "b" if bucket < float(experiment.get("percentage", 0)) else "a"
        value = experiment.get("variant_" + variant)
        if value:
            overrides[target] = str(value)
            assignments.append({"experiment_id": experiment["id"], "variant": variant, "target": target})
    return overrides, assignments


def configure_runtime(conn, config):
    role, interaction = config.get("role") or {}, config.get("interaction") or {}
    overrides, assignments = experiment_overrides(conn.console_store, conn.device_id, config.get("device") or {})
    conn.console_interaction = interaction
    conn.console_safety = config.get("safety") or {}
    if interaction.get("session_timeout"):
        conn.timeout_seconds = max(10, min(3600, int(interaction["session_timeout"]))) + 60
    prompt = role.get("prompt") or role.get("description") or conn.console_base_prompt
    style = overrides.get("style") or role.get("style") or interaction.get("style")
    if style:
        prompt += "\n回复风格：" + str(style)
    if role.get("max_sentences"):
        prompt += "\n单次回复最多 " + str(max(1, min(20, int(role["max_sentences"])))) + " 句。"
    if role.get("follow_up") is False:
        prompt += "\n不要主动追加追问。"
    if role.get("forbidden_topics"):
        prompt += "\n避免主动讨论这些话题：" + str(role["forbidden_topics"])
    clarification = overrides.get("clarification") or interaction.get("clarification")
    if clarification:
        prompt += "\n信息不清楚时的追问策略：" + str(clarification)
    conn.console_greeting = overrides.get("greeting") or interaction.get("wake_reply") or role.get("greeting")
    if conn.console_greeting:
        prompt += "\n唤醒时的开场白：" + str(conn.console_greeting)
        # Shared audio cache is keyed by voice, not device; it must not override
        # a device-specific greeting.
        conn.config["enable_wakeup_words_response_cache"] = False
    if interaction.get("fallback_llm"):
        conn.config["system_error_response"] = interaction["fallback_llm"]
    conn.config["prompt"] = prompt
    if getattr(conn, "console_runtime_prompt", None) != prompt:
        if getattr(conn, "console_runtime_prompt", None) is not None and hasattr(conn, "change_system_prompt"):
            conn.change_system_prompt(prompt)
        conn.console_runtime_prompt = prompt
    conn.console_assignments = assignments
    already = getattr(conn, "console_seen_assignments", set())
    for assignment in assignments:
        identity = (assignment["experiment_id"], assignment["variant"])
        if identity not in already:
            record(conn.console_store, "experiment_assignment", conn.device_id, session_id=conn.session_id, **assignment)
            already.add(identity)
    conn.console_seen_assignments = already


def memory_policy(policy, interaction):
    result = dict(policy)
    if interaction.get("no_memory") or interaction.get("cross_session_memory") is False:
        result["guest_mode"] = True
    return result


def trim_context(conn, turns):
    history = conn.dialogue.dialogue
    users = [i for i, message in enumerate(history) if message.role == "user"]
    retained = max(0, max(1, min(100, int(turns))) - 1)
    if len(users) > retained:
        start = users[-retained] if retained else len(history)
        conn.dialogue.dialogue = [message for i, message in enumerate(history)
                                 if message.role == "system" or i >= start]


class RoutedLLM:
    """Fail over only before any text/tool delta is emitted; never duplicate a partial answer."""
    def __init__(self, primary, backup=None, store=None, device_id=None):
        self.primary = primary
        self.backup = backup
        self.store = store
        self.device_id = device_id

    def __getattr__(self, name):
        return getattr(self.primary, name)

    def _stream(self, method, *args, **kwargs):
        start = time.monotonic()
        emitted = False
        first_ms = None
        for index, provider in enumerate((self.primary, self.backup)):
            if provider is None:
                continue
            stream = None
            try:
                stream = getattr(provider, method)(*args, **kwargs)
                for part in stream:
                    substantive = bool(part[0] or part[1]) if isinstance(part, tuple) else bool(part)
                    if substantive:
                        emitted = True
                        if first_ms is None:
                            first_ms = round((time.monotonic() - start) * 1000)
                    yield part
                if not emitted:
                    raise RuntimeError("Model returned no content")
                record(self.store, "llm_request", self.device_id, model_name=getattr(provider, "model_name", ""),
                       llm_first_token_ms=first_ms, duration_ms=round((time.monotonic() - start) * 1000),
                       response_mode="streaming" if getattr(provider, "streaming", True) else "buffered",
                       fallback=bool(index), status="success")
                return
            except Exception as exc:
                record(self.store, "model_error", self.device_id,
                       model_name=getattr(provider, "model_name", ""), error_type=type(exc).__name__,
                       partial=emitted)
                if emitted or index or self.backup is None:
                    raise
                record(self.store, "model_fallback", self.device_id,
                       model_name=getattr(self.backup, "model_name", ""))
            finally:
                if stream is not None and hasattr(stream, "close"):
                    stream.close()

    def response(self, *args, **kwargs):
        yield from self._stream("response", *args, **kwargs)

    def response_with_functions(self, *args, **kwargs):
        yield from self._stream("response_with_functions", *args, **kwargs)

    def response_no_stream(self, system_prompt, user_prompt, **kwargs):
        return "".join(self.response("", [{"role": "system", "content": system_prompt},
                                          {"role": "user", "content": user_prompt}], **kwargs))


class ConsoleMemory:
    """Private per-user memory; guest and unidentified sessions cannot read or write it."""
    def __init__(self, store, device_id, policy):
        self.store = store
        self.device_id = device_id
        self.policy = dict(policy or {})
        self.user_id = self.policy.get("user_id") if not self.policy.get("guest_mode", True) else None

    def init_memory(self, role_id, llm, **kwargs):
        self.llm = llm

    def set_llm(self, llm):
        self.llm = llm

    async def query_memory(self, query):
        if not self.user_id:
            return ""
        rows = self.store.list("memories")
        device = self.store.device_config(self.device_id).get("device", {})
        aliases = {self.device_id, device.get("id"), device.get("device_id")} - {None, ""}
        shared = self.policy.get("visibility") in ("device", "shared_device")
        visible = [row for row in rows if (
            row.get("user_id") == self.user_id and row.get("device_id") in aliases | {None, ""}
            or shared and row.get("visibility") in ("device", "shared_device") and row.get("device_id") in aliases)]
        return "\n".join(str(row.get("content", "")) for row in visible)[-6000:]

    async def save_memory(self, msgs, session_id=None):
        # Conversation persistence is explicit below. Do not turn every utterance
        # into permanent personal facts without a separate retention policy.
        return None


def apply_connection(conn, store=None, factory=None):
    store = store if store is not None else get_store()
    if store is None:
        return False
    config = store.device_config(conn.device_id)
    conn.console_store = store
    conn.console_base_prompt = conn.config.get("prompt", "")
    conn.console_policy = authenticated_policy(conn, config.get("memory") or {"guest_mode": True})
    conn.console_voiceprint_config = copy.deepcopy(conn.config.get("voiceprint", {}))
    conn.console_user_id = (conn.console_policy.get("user_id")
                            if not conn.console_policy.get("guest_mode", True) else None)
    # Never reuse upstream's shared mutable memory object across users/devices.
    conn.memory = ConsoleMemory(store, conn.device_id, memory_policy(conn.console_policy, config.get("interaction") or {}))
    conn.config.pop("summaryMemory", None)
    if conn.console_policy.get("guest_mode", True):
        conn.config["voiceprint"] = {}
    interaction = config.get("interaction") or {}
    configure_runtime(conn, config)
    conn.config["close_connection_no_voice_time"] = int(interaction.get("session_timeout", conn.config.get("close_connection_no_voice_time", 120)))
    voice = config.get("voice") or {}
    tts_name = conn.config.get("selected_module", {}).get("TTS")
    if voice.get("voice_id") and tts_name and tts_name in conn.config.get("TTS", {}):
        conn.config["TTS"][tts_name]["voice"] = voice["voice_id"]
    model = config.get("model")
    backup = config.get("backup_model")
    if model:
        if not model.get("enabled") or backup and not backup.get("enabled"):
            raise ValueError("Bound model is disabled; test and enable it in the console")
        if factory is None:
            from core.utils.llm import create_instance
            factory = create_instance
        def create(item):
            settings = copy.deepcopy(item)
            settings.setdefault("timeout", 20)
            settings["_console_usage"] = lambda usage: record(
                store, "telemetry", conn.device_id, model_name=settings.get("model_name", ""), **usage)
            if str(settings.get("provider", "")).lower() in ("claude", "anthropic", "gemini"):
                from core.console_native_llm import NativeLLM
                return NativeLLM(settings)
            return factory("openai", settings)
        conn.llm = RoutedLLM(create(model), create(backup) if backup else None, store, conn.device_id)
    else:
        conn.llm = RoutedLLM(conn.llm, store=store, device_id=conn.device_id)
    store.upsert_device(conn.device_id)
    record(store, "connected", conn.device_id, session_id=conn.session_id)
    return True


def capture_turn(conn, query, response):
    store = getattr(conn, "console_store", None)
    if store is None:
        return
    try:
        store.upsert_device(conn.device_id)
    except Exception:
        pass
    record(store, "conversation", conn.device_id, session_id=conn.session_id,
           experiments=getattr(conn, "console_assignments", []))
    blocked_words = words(getattr(conn, "console_interaction", {}).get("no_memory_rules"))
    if getattr(conn, "console_skip_log", False) or any(word in str(response).casefold() for word in blocked_words):
        conn.dialogue.dialogue = [m for m in conn.dialogue.dialogue if m.role == "system"]
        return
    # Guest logs contain operational metadata only, never personal transcripts.
    if not getattr(conn, "console_user_id", None):
        return
    try:
        store.save("conversations", {"device_id": conn.device_id, "user_id": conn.console_user_id,
                   "session_id": conn.session_id, "query": str(query or "")[:12000],
                   "response": str(response or "")[:12000], "guest_mode": False}, actor="service")
    except Exception:
        pass


def prepare_turn(conn, query):
    """Refresh privacy before each turn and handle deletion/feedback deterministically."""
    store = getattr(conn, "console_store", None)
    if store is None:
        return None
    if getattr(conn, "console_skip_log", False):
        # Also remove a sensitive turn when generation failed before capture_turn.
        conn.dialogue.dialogue = [m for m in conn.dialogue.dialogue if m.role == "system"]
    try:
        config = store.device_config(conn.device_id)
        policy = authenticated_policy(conn, config.get("memory") or {"guest_mode": True})
        configure_runtime(conn, config)
    except Exception:
        return "暂时无法验证你的会话配置，请稍后再试。"
    user_id = policy.get("user_id") if not policy.get("guest_mode", True) else None
    if user_id != getattr(conn, "console_user_id", None):
        conn.dialogue.dialogue = [m for m in conn.dialogue.dialogue if m.role == "system"]
        conn.system_introduced_speakers.clear()
        conn.introduced_speakers.clear()
        conn.console_user_id = user_id
    conn.console_policy = policy
    conn.config["voiceprint"] = {} if policy.get("guest_mode", True) else getattr(conn, "console_voiceprint_config", {})
    if policy.get("guest_mode", True):
        conn.current_speaker = None
    interaction = config.get("interaction") or {}
    conn.memory = ConsoleMemory(store, conn.device_id, memory_policy(policy, interaction))
    if interaction.get("context_turns"):
        trim_context(conn, interaction["context_turns"])
    text = str(query or "").strip()
    try:
        structured = json.loads(text)
        if isinstance(structured, dict):
            text = str(structured.get("content", text)).strip()
    except (ValueError, TypeError):
        pass
    text = text.rstrip("。.!！?？")
    conn.console_skip_log = bool(interaction.get("no_memory")) or any(word in text.casefold() for word in words(interaction.get("no_memory_rules")))
    if text in ("忘记我", "删除我的记忆"):
        if not user_id:
            return "当前是访客模式，没有读取个人记忆。请先在管理台确认你的身份，再申请删除。"
        store.save("deletion_requests", {"user_id": user_id, "device_id": conn.device_id,
                   "scope": "all", "status": "pending", "source": "voice"}, actor="service")
        return "已提交删除记忆申请，请到管理台确认删除范围。确认前，记忆还没有删除。"
    if text in ("忘记这段对话", "重新开始"):
        conn.dialogue.dialogue = [m for m in conn.dialogue.dialogue if m.role == "system"]
        return "已清除本次对话上下文。历史记录可在管理台删除。"
    if text == "这个回答不好":
        store.save("feedback", {"device_id": conn.device_id, "user_id": user_id,
                   "session_id": conn.session_id, "tag": "答非所问", "status": "pending",
                   "source": "voice"}, actor="service")
        return "收到，我已记录这次反馈。你可以告诉我哪里需要改进。"
    safety = conn.console_safety
    if safety.get("enabled") and any(word in text.casefold() for word in words(safety.get("keywords"))):
        conn.console_skip_log = True
        record(store, "safety_blocked", conn.device_id, rule_id=safety.get("id"),
               category=safety.get("category"), action=safety.get("action"), enforcement="literal_keyword")
        return safety.get("reply") or "这个问题超出了当前服务的回答范围，请换一种方式描述你的需求。"
    if getattr(conn, "console_wakeup_pending", False):
        conn.console_wakeup_pending = False
        if conn.console_greeting:
            return str(conn.console_greeting)
    return None


async def process_commands_once(conn, invoke=None):
    store = getattr(conn, "console_store", None)
    if store is None:
        return
    if not console_authenticated(conn):
        return  # An impersonated device must not consume another device's commands.
    commands = await asyncio.to_thread(store.commands, conn.device_id)
    for command in commands:
        status, result = "unsupported", {"reason": "当前固件桥接不支持此指令"}
        if command.get("type") == "self_check":
            client = getattr(conn, "mcp_client", None)
            if client is None and getattr(conn, "features", None) is None:
                continue  # hello has not arrived yet
            if client is not None:
                if not await client.is_ready():
                    continue
                tool = next((key for key, name in client.name_mapping.items() if name == "self.get_device_status"), None)
                if tool:
                    try:
                        if invoke is None:
                            from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
                            invoke = call_mcp_tool
                        raw = await invoke(conn, client, tool, "{}", timeout=10)
                        try:
                            details = json.loads(raw)
                        except (ValueError, TypeError):
                            details = {"raw": str(raw)[:4000]}
                        status, result = "completed", {"device_status": details,
                            "checks": {"connection": "passed", "mcp_status": "passed", "asr_tts_loopback": "not_run"}}
                        await asyncio.to_thread(store.upsert_device, conn.device_id, device_status=details)
                    except Exception as exc:
                        status, result = "failed", {"error_type": type(exc).__name__}
        await asyncio.to_thread(store.acknowledge, conn.device_id, command["id"], {"status": status, "result": result})


async def command_loop(conn):
    try:
        while not conn.stop_event.is_set():
            try:
                await process_commands_once(conn)
            except Exception as exc:
                record(conn.console_store, "command_error", conn.device_id, error_type=type(exc).__name__)
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        raise
