import asyncio
import io
import json
import os
from pathlib import Path
import sys
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "upstream")]
from console.store import Store
from core.console_bridge import (ConsoleMemory, RoutedLLM, apply_connection, capture_turn,
                                 check_ota, get_store, prepare_turn)
from core.console_bridge import experiment_overrides, process_commands_once, should_route_console_chat
from core.console_native_llm import NativeLLM, NoRedirect


class Provider:
    model_name = "fake-model"
    def __init__(self, parts=(), fail=False):
        self.parts, self.fail, self.called = parts, fail, 0
    def response(self, *args, **kwargs):
        self.called += 1
        yield from self.parts
        if self.fail:
            raise TimeoutError("simulated timeout")
    response_with_functions = response


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)

    def connection(self, user="alice", guest=False):
        self.store.upsert_device("desk", user_id=user, guest_mode=guest)
        token = self.store.issue_device_token("desk")
        return SimpleNamespace(device_id="desk", session_id="session", llm=Provider(["ok"]),
            headers={"x-console-device-token": token},
            config={"prompt": "Assistant", "selected_module": {}, "TTS": {}},
            dialogue=SimpleNamespace(dialogue=[SimpleNamespace(role="system", content="Assistant"),
                                              SimpleNamespace(role="user", content="private")]),
            system_introduced_speakers=set(), introduced_speakers=set())

    def test_disabled_bridge_does_not_import_store_or_mutate_connection(self):
        with patch.dict(os.environ, {}, clear=True):
            conn = self.connection()
            original = conn.llm
            self.assertIsNone(get_store())
            self.assertFalse(apply_connection(conn))
            self.assertIs(conn.llm, original)

    def test_fallback_before_output_records_actual_failure(self):
        primary, backup = Provider(fail=True), Provider(["hello"])
        routed = RoutedLLM(primary, backup, self.store, "desk")
        self.assertEqual(list(routed.response("s", [])), ["hello"])
        self.assertEqual(backup.called, 1)
        self.assertIn("model_fallback", [e["kind"] for e in self.store.list("events")])

    def test_partial_output_never_retries_or_duplicates_answer(self):
        backup = Provider(["duplicate"])
        routed = RoutedLLM(Provider(["partial"], fail=True), backup)
        stream = routed.response("s", [])
        self.assertEqual(next(stream), "partial")
        with self.assertRaises(TimeoutError):
            next(stream)
        self.assertEqual(backup.called, 0)

    def test_tool_delta_prevents_fallback(self):
        backup = Provider([("", ["duplicate tool"])])
        routed = RoutedLLM(Provider([("", ["tool"])], fail=True), backup)
        stream = routed.response_with_functions("s", [], [])
        self.assertEqual(next(stream), ("", ["tool"]))
        with self.assertRaises(TimeoutError):
            next(stream)
        self.assertEqual(backup.called, 0)

    def test_empty_primary_can_fallback(self):
        routed = RoutedLLM(Provider(), Provider(["backup"]))
        self.assertEqual(list(routed.response("s", [])), ["backup"])

    def test_memory_private_user_and_guest_isolation_and_deletion(self):
        row = self.store.save("memories", {"user_id": "alice", "content": "Alice secret"})
        self.store.save("memories", {"user_id": "bob", "content": "Bob secret"})
        alice = ConsoleMemory(self.store, "desk", {"guest_mode": False, "user_id": "alice"})
        guest = ConsoleMemory(self.store, "desk", {"guest_mode": True, "user_id": "alice"})
        self.assertEqual(asyncio.run(alice.query_memory("?")), "Alice secret")
        self.assertEqual(asyncio.run(guest.query_memory("?")), "")
        self.store.delete("memories", row["id"])
        self.assertEqual(asyncio.run(alice.query_memory("?")), "")

    def test_shared_memory_requires_both_device_and_visibility(self):
        self.store.save("memories", {"user_id": "bob", "content": "shared", "device_id": "desk", "visibility": "shared_device"})
        self.store.save("memories", {"user_id": "bob", "content": "private", "device_id": "desk", "visibility": "private"})
        mem = ConsoleMemory(self.store, "desk", {"guest_mode": False, "user_id": "alice", "visibility": "shared_device"})
        self.assertEqual(asyncio.run(mem.query_memory("?")), "shared")

    def test_guest_transcript_is_never_persisted(self):
        conn = self.connection(guest=True)
        apply_connection(conn, self.store)
        capture_turn(conn, "personal question", "private answer")
        self.assertEqual(self.store.list("conversations"), [])
        self.assertNotIn("personal question", json.dumps(self.store.list("events")))

    def test_switching_owner_clears_previous_context(self):
        conn = self.connection()
        apply_connection(conn, self.store)
        self.store.upsert_device("desk", user_id="bob", guest_mode=False)
        prepare_turn(conn, "hello")
        self.assertEqual(conn.console_user_id, "bob")
        self.assertEqual([x.role for x in conn.dialogue.dialogue], ["system"])

    def test_forget_me_creates_pending_task_without_deleting(self):
        conn = self.connection()
        apply_connection(conn, self.store)
        self.store.save("memories", {"user_id": "alice", "content": "keep until confirmed"})
        reply = prepare_turn(conn, '{"content":"删除我的记忆。"}')
        self.assertIn("确认前", reply)
        self.assertEqual(len(self.store.list("memories")), 1)
        self.assertEqual(self.store.list("deletion_requests")[0]["status"], "pending")

    def test_ota_registers_real_hardware_and_respects_environment(self):
        self.store.upsert_device("desk")
        token = self.store.issue_device_token("desk")
        header = bytearray(24)
        header[:2] = b"\xe9\x01"
        struct.pack_into("<H", header, 12, 9)
        data = struct.pack("<I", 0xABCD5432) + bytes(252)
        checksum = 0xEF
        for byte in data:
            checksum ^= byte
        firmware = bytes(header) + struct.pack("<II", 0, len(data)) + data + bytes(15) + bytes([checksum])
        upload = self.store.save_upload("firmware", "test.bin", firmware)
        fw = self.store.save("firmware", {"version": "2.1.0", "board": "board-a", "chip": "ESP32-S3", "upload_id": upload["id"]})
        self.store.save("rollouts", {"name": "safe rollout", "firmware_id": fw["id"], "enabled": True, "percentage": 100, "check_environment": True})
        payload = {"chip_model_name": "esp32s3", "flash_size": 16777216,
                   "device_status": {"battery": {"level": 20, "charging": False}, "network": {"signal": "strong"}}}
        self.assertIsNone(check_ota(self.store, "desk", payload, "2.0.0", "board-a", token))
        payload["device_status"]["battery"]["charging"] = True
        self.assertEqual(check_ota(self.store, "desk", payload, "2.0.0", "board-a", token)["id"], fw["id"])
        self.assertEqual(self.store.get("devices", "desk")["chip"], "ESP32-S3")
        self.assertIsNone(check_ota(self.store, "desk", payload, "2.0.0", "wrong-board", token))

    def test_disabled_bound_model_is_not_called(self):
        model = self.store.save("models", {"provider": "openai", "model_name": "test", "base_url": "https://example.com/v1", "enabled": False})
        conn = self.connection()
        self.store.upsert_device("desk", model_id=model["id"])
        with self.assertRaises(ValueError):
            apply_connection(conn, self.store, lambda *args: self.fail("disabled model called"))

    def test_native_claude_tools_and_usage(self):
        usage = []
        provider = NativeLLM({"provider": "claude", "model_name": "test", "base_url": "https://api.example.com/v1", "api_key": "test-only", "_console_usage": usage.append})
        payload = {"content": [{"type": "tool_use", "id": "call", "name": "weather", "input": {"city": "Beijing"}}], "usage": {"input_tokens": 10, "output_tokens": 5}}
        with patch("core.console_native_llm.open_request", return_value=io.BytesIO(json.dumps(payload).encode())) as open_url:
            result = list(provider.response_with_functions("s", [{"role": "user", "content": "weather"}], [{"type": "function", "function": {"name": "weather", "parameters": {"type": "object", "properties": {}}}}]))
        self.assertEqual(result[0][1][0].function.name, "weather")
        self.assertEqual(usage[0]["total_tokens"], 15)
        self.assertEqual(open_url.call_args.args[0].full_url, "https://api.example.com/v1/messages")

    def test_native_credentials_cannot_follow_redirect(self):
        request = Request("https://models.example/v1/messages", headers={"x-api-key": "test-only"})
        with self.assertRaises(HTTPError):
            NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.example/")

    def test_client_headers_cannot_choose_personal_identity(self):
        conn = self.connection("alice")
        conn.headers.update({"user-id": "bob", "guest-mode": "false"})
        apply_connection(conn, self.store)
        self.assertEqual(conn.console_user_id, "alice")

    def test_bridge_database_failure_does_not_silently_use_shared_memory(self):
        conn = self.connection()
        with patch.object(self.store, "device_config", side_effect=OSError("unavailable")):
            with self.assertRaises(OSError):
                apply_connection(conn, self.store)
        apply_connection(conn, self.store)
        with patch.object(self.store, "device_config", side_effect=OSError("unavailable")):
            self.assertIn("无法验证", prepare_turn(conn, "question"))
            self.assertTrue(should_route_console_chat(conn, "question"))

    def test_role_prompt_context_limit_and_memory_switch_apply(self):
        conn = self.connection()
        role = self.store.save("roles", {"name": "Focus", "prompt": "Be helpful", "style": "简洁", "max_sentences": 2, "greeting": "我在"})
        strategy = self.store.save("interaction", {"name": "short", "context_turns": 2, "cross_session_memory": False, "fallback_llm": "稍后再试"})
        self.store.upsert_device("desk", role_id=role["id"], interaction_id=strategy["id"])
        apply_connection(conn, self.store)
        self.assertIn("简洁", conn.config["prompt"])
        self.assertIn("2 句", conn.config["prompt"])
        self.assertEqual(conn.config["system_error_response"], "稍后再试")
        conn.dialogue.dialogue.extend([SimpleNamespace(role="assistant", content="old"), SimpleNamespace(role="user", content="latest"), SimpleNamespace(role="assistant", content="latest answer")])
        prepare_turn(conn, "new question")
        self.assertEqual([m.content for m in conn.dialogue.dialogue], ["Assistant", "latest", "latest answer"])
        self.store.save("memories", {"user_id": "alice", "content": "permanent"})
        self.assertEqual(asyncio.run(conn.memory.query_memory("?")), "")
        conn.console_wakeup_pending = True
        self.assertEqual(prepare_turn(conn, "你好"), "我在")

    def test_keyword_guard_is_enforced_before_legacy_intent_and_audited(self):
        conn = self.connection()
        rule = self.store.save("safety", {"name": "Privacy", "keywords": "私人密码\n银行卡密码", "reply": "请不要分享密码", "enabled": True})
        self.store.upsert_device("desk", safety_id=rule["id"])
        apply_connection(conn, self.store)
        self.assertTrue(should_route_console_chat(conn, "帮我获取私人密码"))
        self.assertEqual(prepare_turn(conn, "帮我获取私人密码"), "请不要分享密码")
        event = next(e for e in self.store.list("events") if e["kind"] == "safety_blocked")
        self.assertEqual(event["enforcement"], "literal_keyword")
        self.assertNotIn("帮我获取私人密码", json.dumps(event, ensure_ascii=False))

    def test_sensitive_keyword_is_not_logged_or_left_in_context(self):
        conn = self.connection()
        strategy = self.store.save("interaction", {"name": "private", "no_memory_rules": "密码、支付信息"})
        self.store.upsert_device("desk", interaction_id=strategy["id"])
        apply_connection(conn, self.store)
        prepare_turn(conn, "我的密码是123")
        capture_turn(conn, "我的密码是123", "收到")
        self.assertEqual(self.store.list("conversations"), [])
        self.assertEqual([m.role for m in conn.dialogue.dialogue], ["system"])

    def test_experiments_are_stable_and_unsupported_targets_not_applied(self):
        exp = self.store.save("experiments", {"name": "Tone", "target": "回复风格", "variant_a": "natural", "variant_b": "brief", "percentage": 100, "enabled": True, "group": "desk"})
        self.store.save("experiments", {"name": "Voice", "target": "音色", "variant_a": "a", "variant_b": "b", "percentage": 100, "enabled": True})
        first = experiment_overrides(self.store, "device", {"group": "desk"})
        self.assertEqual(first, experiment_overrides(self.store, "device", {"group": "desk"}))
        self.assertEqual(first[0], {"style": "brief"})
        self.assertEqual(experiment_overrides(self.store, "device", {"group": "other"})[0], {})
        self.store.save("experiments", {"percentage": 0}, exp["id"])
        self.assertEqual(experiment_overrides(self.store, "device", {"group": "desk"})[0], {"style": "natural"})

    def test_self_check_uses_real_mcp_result_and_does_not_claim_audio_loopback(self):
        conn = self.connection()
        apply_connection(conn, self.store)
        class Client:
            name_mapping = {"self_get_device_status": "self.get_device_status"}
            async def is_ready(self):
                return True
        conn.mcp_client = Client()
        self.store.queue_command("desk", {"type": "self_check"})
        async def invoke(*args, **kwargs):
            return '{"audio_speaker":{"volume":30}}'
        with patch.object(self.store, "acknowledge", wraps=self.store.acknowledge) as ack:
            asyncio.run(process_commands_once(conn, invoke))
            result = ack.call_args.args[2]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["checks"]["asr_tts_loopback"], "not_run")
        self.assertEqual(result["result"]["device_status"]["audio_speaker"]["volume"], 30)
        self.assertEqual(self.store.commands("desk"), [])

    def test_unsupported_command_is_not_reported_as_completed(self):
        conn = self.connection()
        apply_connection(conn, self.store)
        self.store.queue_command("desk", {"type": "rollback"})
        with patch.object(self.store, "acknowledge", wraps=self.store.acknowledge) as ack:
            asyncio.run(process_commands_once(conn))
            self.assertEqual(ack.call_args.args[2]["status"], "unsupported")

    def test_device_id_alone_cannot_read_memory_or_consume_commands(self):
        conn = self.connection("alice")
        conn.headers = {"device-id": "desk", "user-id": "alice"}
        self.store.save("memories", {"user_id": "alice", "content": "private"})
        self.store.queue_command("desk", {"type": "self_check"})
        apply_connection(conn, self.store)
        self.assertIsNone(conn.console_user_id)
        self.assertFalse(conn.console_authenticated)
        self.assertEqual(asyncio.run(conn.memory.query_memory("?")), "")
        asyncio.run(process_commands_once(conn))
        self.assertEqual(len(self.store.commands("desk")), 1)

    def test_token_rotation_revokes_existing_private_session(self):
        conn = self.connection("alice")
        apply_connection(conn, self.store)
        self.store.issue_device_token("desk")
        prepare_turn(conn, "hello")
        self.assertIsNone(conn.console_user_id)
        self.assertEqual([m.role for m in conn.dialogue.dialogue], ["system"])

    def test_unverified_ota_cannot_overwrite_registered_device(self):
        conn = self.connection()
        self.store.upsert_device("desk", chip="ESP32-S3", firmware_version="2.0.0")
        self.assertIsNone(check_ota(self.store, "desk", {"chip_model_name": "esp32c3"}, "9.9.9", "fake"))
        device = self.store.get("devices", "desk")
        self.assertEqual(device["chip"], "ESP32-S3")
        self.assertEqual(device["firmware_version"], "2.0.0")


if __name__ == "__main__":
    unittest.main()
