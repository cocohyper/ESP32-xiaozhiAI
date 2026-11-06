import ast
import asyncio
import copy
import importlib.util
import io
import json
import tempfile
import time
import unittest
import urllib.error
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deployment_manage", ROOT / "manage.py")
manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manage)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.config = manage.load_config(ROOT / "config.example.yaml")

    def ready_config(self):
        config = copy.deepcopy(self.config)
        config["LLM"]["DeepSeekLLM"]["api_key"] = "sk-unit-test-not-a-real-key"
        config["server"]["websocket"] = "ws://192.168.1.100:8000/xiaozhi/v1/"
        return config

    def test_delivered_placeholder_is_blocked(self):
        with self.assertRaisesRegex(manage.SetupError, "api_key"):
            manage.validate(self.config, skip_model=True)

    def test_realistic_config_passes_without_network(self):
        manage.validate(self.ready_config(), skip_model=True)

    def test_invalid_and_unreachable_hosts_are_rejected(self):
        for host in ["", "YOUR_SERVER_IP", "127.0.0.1", "0.0.0.0", "localhost", "::1", "224.0.0.1", "169.254.1.1", "http://192.168.1.1", "a/b", "999.1.1.1", "host:8000", "a..b", "-host"]:
            with self.subTest(host=host), self.assertRaises(manage.SetupError):
                manage.normalize_host(host)

    def test_lan_domain_and_ipv6_hosts_are_supported(self):
        for host, expected in [("192.168.1.100", "192.168.1.100"), ("xiaozhi.lan", "xiaozhi.lan"), ("fd00::123", "[fd00::123]"), ("[fd00::123]", "[fd00::123]")]:
            with self.subTest(host=host):
                self.assertEqual(manage.normalize_host(host), expected)

    def test_configure_preserves_secret_and_comments_and_updates_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, kconfig_path = Path(tmp) / ".config.yaml", Path(tmp) / "Kconfig.projbuild"
            source = (ROOT / "config.example.yaml").read_text(encoding="utf-8").replace(manage.KEY_PLACEHOLDER, "sk-preserve-test-key")
            config_path.write_text(source, encoding="utf-8")
            original = (ROOT.parent / "main/Kconfig.projbuild").read_text(encoding="utf-8")
            kconfig_path.write_text(original, encoding="utf-8")
            url = manage.configure_server("192.168.1.123", config_path, kconfig_path)
            self.assertEqual(url, "http://192.168.1.123:8003/xiaozhi/ota/")
            updated = config_path.read_text(encoding="utf-8")
            self.assertIn("# <<< 在这里填写 DeepSeek 密钥", updated)
            self.assertIn("sk-preserve-test-key", updated)
            self.assertIn('default "' + url + '"', kconfig_path.read_text(encoding="utf-8"))
            config = manage.load_config(config_path)
            self.assertEqual(config["server"]["websocket"], "ws://192.168.1.123:8000/xiaozhi/v1/")
            self.assertEqual(config["server"]["vision_explain"], "http://192.168.1.123:8003/mcp/vision/explain")
            manage.validate(config, skip_model=True)
            manage.configure_server("192.168.1.123", config_path, kconfig_path)
            self.assertEqual(config_path.read_text(encoding="utf-8"), updated)

    def test_failed_configure_leaves_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, kconfig_path = Path(tmp) / ".config.yaml", Path(tmp) / "Kconfig.projbuild"
            source = (ROOT / "config.example.yaml").read_text(encoding="utf-8").replace("  vision_explain:", "  renamed_field:")
            config_path.write_text(source, encoding="utf-8")
            original = (ROOT.parent / "main/Kconfig.projbuild").read_text(encoding="utf-8")
            kconfig_path.write_text(original, encoding="utf-8")
            with self.assertRaises(manage.SetupError):
                manage.configure_server("192.168.1.123", config_path, kconfig_path)
            self.assertEqual(config_path.read_text(encoding="utf-8"), source)
            self.assertEqual(kconfig_path.read_text(encoding="utf-8"), original)

    def test_invalid_yaml_does_not_echo_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text('api_key: "sk-do-not-print', encoding="utf-8")
            with self.assertRaises(manage.SetupError) as error:
                manage.load_config(path)
            self.assertNotIn("sk-do-not-print", str(error.exception))

    def test_key_is_never_forwarded_to_another_provider(self):
        config = self.ready_config()
        config["LLM"]["DeepSeekLLM"]["base_url"] = "https://example.invalid/v1"
        with self.assertRaises(manage.SetupError):
            manage.test_api(config, opener=lambda *a, **k: self.fail("network must not be called"))

    def test_missing_model_and_lfs_pointer_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.pt"
            for content in [None, b"version https://git-lfs.github.com/spec/v1\n"]:
                if content:
                    path.write_bytes(content)
                with self.assertRaisesRegex(manage.SetupError, "model.pt"):
                    manage.validate(self.ready_config(), path)

    def test_streaming_api_request_and_chunks(self):
        def opener(request, timeout):
            self.assertEqual(request.full_url, "https://api.deepseek.com/v1/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer sk-unit-test-not-a-real-key")
            body = json.loads(request.data)
            self.assertTrue(body["stream"])
            self.assertEqual(body["model"], "deepseek-v4-flash")
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertEqual(timeout, 60)
            events = [b": keep-alive\n", b"data: {\"choices\": []}\n", 'data: {"choices":[{"delta":{"content":"连接"}}]}\n'.encode(), 'data: {"choices":[{"delta":{"content":"成功"}}]}\n'.encode(), b"data: [DONE]\n"]
            return io.BytesIO(b"".join(events))
        self.assertEqual(manage.test_api(self.ready_config(), opener=opener), "连接成功")

    def test_api_http_error_is_actionable_and_redacted(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "sk-do-not-print", {}, None)
        with self.assertRaisesRegex(manage.SetupError, "401") as error:
            manage.test_api(self.ready_config(), opener=opener)
        self.assertNotIn("sk-do-not-print", str(error.exception))

    def test_empty_or_malformed_stream_is_rejected(self):
        for data in [b"data: [DONE]\n", b"data: invalid-json\n", b'data: {"error":{"message":"sk-do-not-print"}}\n']:
            with self.subTest(data=data), self.assertRaises(manage.SetupError) as error:
                manage.test_api(self.ready_config(), opener=lambda *a, **k: io.BytesIO(data))
            self.assertNotIn("sk-do-not-print", str(error.exception))

    def test_manager_api_and_mqtt_cannot_override_this_deployment(self):
        for path, value in [("manager-api", {"url": "http://other-server"}), ("read_config_from_api", True)]:
            config = self.ready_config()
            config[path] = value
            with self.assertRaises(manage.SetupError):
                manage.validate(config, skip_model=True)
        config = self.ready_config()
        config["server"]["mqtt_gateway"] = "other-server:1883"
        with self.assertRaises(manage.SetupError):
            manage.validate(config, skip_model=True)

    def test_real_upstream_merge_uses_only_deepseek_for_selected_llm(self):
        # Exercise the exact vendored merge function without importing runtime/audio dependencies.
        tree = ast.parse((ROOT / "upstream/config/config_loader.py").read_text(encoding="utf-8"))
        function = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "merge_configs")
        namespace = {"Mapping": Mapping}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "upstream_merge", "exec"), namespace)
        default = yaml.safe_load((ROOT / "upstream/config.yaml").read_text(encoding="utf-8"))
        merged = namespace["merge_configs"](default, self.ready_config())
        self.assertEqual(merged["selected_module"]["LLM"], "DeepSeekLLM")
        self.assertEqual(merged["LLM"]["DeepSeekLLM"]["base_url"], manage.API_BASE)
        self.assertEqual(merged["Intent"]["function_call"]["functions"], [])
        self.assertIsNone(merged["selected_module"]["VLLM"])
        for name in ["VAD", "ASR", "LLM", "TTS", "Memory", "Intent"]:
            provider = merged["selected_module"][name]
            self.assertIn("type", merged[name][provider])
        self.assertIn("log", merged)

    def test_actual_ota_response_overrides_old_device_protocol_version(self):
        tree = ast.parse((ROOT / "upstream/core/api/ota_handler.py").read_text(encoding="utf-8"))
        handler = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "OTAHandler")
        post = next(item for item in handler.body if isinstance(item, ast.AsyncFunctionDef) and item.name == "handle_post")
        get_url = next(item for item in handler.body if isinstance(item, ast.FunctionDef) and item.name == "_get_websocket_url")
        namespace = {"json": json, "time": time, "TAG": "test", "get_local_ip": lambda: "172.17.0.2", "web": SimpleNamespace(Response=lambda **kw: SimpleNamespace(**kw))}
        exec(compile(ast.Module(body=[post, get_url], type_ignores=[]), "ota_handler", "exec"), namespace)
        config = self.ready_config()
        fake = SimpleNamespace(config=config, logger=MagicMock(), auth_enable=False, _bin_cache={}, _refresh_bin_cache_if_needed=lambda: None, _add_cors_headers=lambda response: None)
        fake._get_websocket_url = lambda ip, port: namespace["_get_websocket_url"](fake, ip, port)
        async def text():
            return json.dumps({"board": {"type": "test-board"}, "application": {"version": "2.5.3"}})
        request = SimpleNamespace(text=text, method="POST", headers={"device-id": "11:22:33:44:55:66", "client-id": "test-client"})
        result = json.loads(asyncio.run(namespace["handle_post"](fake, request)).text)
        self.assertEqual(result["websocket"], {"url": "ws://192.168.1.100:8000/xiaozhi/v1/", "token": "", "version": 1})
        self.assertNotIn("mqtt", result)
        self.assertNotIn("api_key", json.dumps(result))
        self.assertEqual(result["firmware"]["version"], "2.5.3")
        self.assertEqual(result["firmware"]["url"], "")
        self.assertEqual(result["server_time"]["timezone_offset"], 480)

    def test_actual_llm_adapter_streams_and_forwards_device_tools(self):
        tree = ast.parse((ROOT / "upstream/core/providers/llm/openai/openai.py").read_text(encoding="utf-8"))
        definitions = [item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "LLMProvider"]
        from urllib.parse import urlparse
        client = MagicMock()
        openai = SimpleNamespace(OpenAI=MagicMock(return_value=client))
        namespace = {"LLMProviderBase": object, "logger": MagicMock(), "TAG": "test", "httpx": SimpleNamespace(Timeout=MagicMock()), "openai": openai, "check_model_key": lambda *a: None, "THINKING_DISABLED_DOMAINS": {}, "THINKING_DISABLED_MODEL_EXCLUSIONS": {}, "urlparse": urlparse, "CompletionUsage": type("CompletionUsage", (), {})}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), "llm_adapter", "exec"), namespace)
        llm_config = self.ready_config()["LLM"]["DeepSeekLLM"]
        provider = namespace["LLMProvider"](llm_config)
        self.assertEqual(openai.OpenAI.call_args.kwargs["base_url"], manage.API_BASE)
        self.assertEqual(openai.OpenAI.call_args.kwargs["api_key"], "sk-unit-test-not-a-real-key")
        stream = MagicMock()
        stream.__iter__.return_value = iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="你好", tool_calls=None))])])
        client.chat.completions.create.return_value = stream
        self.assertEqual(list(provider.response("session", [{"role": "user", "content": "你好"}])), ["你好"])
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["model"], "deepseek-v4-flash")
        self.assertEqual(kwargs["extra_body"]["thinking"], {"type": "disabled"})
        stream.close.assert_called_once()
        tools = [{"type": "function", "function": {"name": "self.audio_speaker.set_volume"}}]
        tool_calls = [SimpleNamespace(id="call-1")]
        stream = MagicMock()
        stream.__iter__.return_value = iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=tool_calls))])])
        client.chat.completions.create.return_value = stream
        self.assertEqual(list(provider.response_with_functions("session", [{"role": "user", "content": "调整音量"}], tools)), [(None, tool_calls)])
        self.assertEqual(client.chat.completions.create.call_args.kwargs["tools"], tools)
        stream.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
