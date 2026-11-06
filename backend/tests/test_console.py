import json
import datetime as dt
from pathlib import Path
import sys
import tempfile
import struct
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from console.server import ConsoleServer, test_model
from console.store import Store, ValidationError
from console.scheduler import run_once, in_window


def firmware_image():
    header = bytearray(b'\xe9\x01' + b'\0' * 22)
    struct.pack_into('<H', header, 12, 9)
    segment = struct.pack('<I', 0xABCD5432) + b'\0' * 252
    checksum = 0xEF
    for byte in segment:
        checksum ^= byte
    return bytes(header) + struct.pack('<II', 0x3F400020, len(segment)) + segment + b'\0' * 15 + bytes([checksum])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def model(self, enabled=False):
        return {'name': 'Test model', 'provider': 'openai', 'base_url': 'https://example.com/v1',
                'model_name': 'test', 'api_key': 'never-return-this-secret', 'enabled': enabled}

    def test_persistence_and_secret_preservation(self):
        record = self.store.save('models', self.model())
        self.assertNotIn('api_key', record)
        self.assertTrue(record['api_key_configured'])
        other = Store.from_db(self.store.db_path)
        other.save('models', {'name': 'renamed', 'api_key': ''}, record['id'])
        self.assertEqual(other.get('models', record['id'], True)['api_key'], 'never-return-this-secret')
        self.assertNotIn('never-return-this-secret', json.dumps(other.bootstrap()))

    def test_enabled_model_requires_exact_tested_configuration(self):
        model = self.model(True)
        with self.assertRaises(ValidationError):
            self.store.save('models', model)
        self.store.register_test(model)
        saved = self.store.save('models', model)
        with self.assertRaises(ValidationError):
            self.store.save('models', {'model_name': 'changed'}, saved['id'])
        with self.assertRaises(ValidationError):
            self.store.save('models', {'api_key': 'changed'}, saved['id'])

    def test_chip_guard_and_device_merge(self):
        with self.assertRaises(ValidationError):
            self.store.save('devices', {'chip': 'ESP32-C3', 'flash_mb': 16, 'custom_wake_word': 'hello'})
        with self.assertRaises(ValidationError):
            self.store.save('resources', {'chip': 'ESP32-S3', 'flash_mb': 4, 'custom_wake_word': 'hello'})
        device = self.store.save('devices', {'device_id': 'aa:bb', 'chip': 'ESP32-S3', 'flash_mb': 16, 'name': 'desk'})
        self.store.upsert_device('aa:bb', firmware_version='2.0')
        self.assertEqual(len(self.store.list('devices')), 1)
        self.assertEqual(self.store.get('devices', device['id'])['firmware_version'], '2.0')
        with self.assertRaises(ValidationError):
            self.store.save('devices', {'device_id': 'aa:bb'})

    def test_ota_gate_requires_environment_and_respects_percent(self):
        device = self.store.save('devices', {'device_id': 'mac', 'chip': 'ESP32-S3', 'group': 'friends'})
        upload = self.store.save_upload('firmware', 'app.bin', firmware_image())
        fw = self.store.save('firmware', {'version': '2.5.4', 'chip': 'ESP32-S3', 'board': 'test', 'upload_id': upload['id']})
        rollout = self.store.save('rollouts', {'firmware_id': fw['id'], 'group': 'friends', 'percentage': 100, 'enabled': True})
        self.assertIsNone(self.store.select_firmware('mac', '2.5.3', 'test'))
        environment = {'power_stable': True, 'network_stable': True}
        self.assertEqual(self.store.select_firmware('mac', '2.5.3', 'test', environment)['id'], fw['id'])
        self.assertIsNone(self.store.select_firmware('mac', '2.5.3', 'other', environment))
        self.assertIsNone(self.store.select_firmware('mac', '2.5.4', 'test', environment))
        self.store.save('rollouts', {'percentage': 0}, rollout['id'])
        self.assertIsNone(self.store.select_firmware('mac', '2.5.3', 'test', environment))

    def test_upload_validation_and_hash(self):
        for kind, filename, body in [('firmware', '../a.bin', b'\xe9' * 32), ('firmware', 'a.bin', b'bad'), ('resources', 'a.png', b'fake')]:
            with self.assertRaises(ValidationError):
                self.store.save_upload(kind, filename, body)
        saved = self.store.save_upload('resources', 'assets.bin', b'assets')
        self.assertEqual(len(saved['sha256']), 64)
        self.assertEqual(self.store.get_upload(saved['id'])['size'], 6)
        image = firmware_image()
        self.store.save_upload('firmware', 'good.bin', image)
        with self.assertRaises(ValidationError):
            self.store.save_upload('firmware', 'bad-checksum.bin', image[:-1] + b'\0')
        with self.assertRaises(ValidationError):
            self.store.save_upload('resources', 'huge.gif', b'GIF89a' + struct.pack('<HH', 2000, 100))

    def test_versions_and_clone(self):
        original = self.store.save('templates', {'name': 'work', 'prompt': 'first'})
        updated = self.store.save('templates', {'prompt': 'second'}, original['id'])
        self.assertEqual(updated['revision'], 2)
        reverted = self.store.rollback('templates', original['id'])
        self.assertEqual(reverted['prompt'], 'first')
        copy = self.store.clone('templates', original['id'])
        self.assertNotEqual(copy['id'], original['id'])
        with self.assertRaises(ValidationError):
            self.store.rollback('templates', original['id'])

    def test_deletion_is_scoped_and_audited(self):
        secret_memory = self.store.save('memories', {'user_id': 'alice', 'content': 'unique-erasure-phrase'})
        self.store.record_event('legacy', collection='memories', record_id=secret_memory['id'], name='unique-erasure-phrase')
        self.store.save('memories', {'user_id': 'bob', 'content': 'keep'})
        self.store.save('conversations', {'user_id': 'alice', 'content': 'chat'})
        req = self.store.save('deletion_requests', {'user_id': 'alice', 'status': 'pending'})
        result = self.store.confirm_deletion(req['id'])
        self.assertEqual(result['status'], 'completed_local')
        self.assertEqual(result['external_status'], 'needs_integration')
        self.assertEqual([x['user_id'] for x in self.store.list('memories')], ['bob'])
        self.assertEqual(self.store.list('conversations'), [])
        self.assertTrue(any(e['kind'] == 'memory_deletion_confirmed' for e in self.store.list('events')))
        self.assertEqual(self.store.confirm_deletion(req['id'])['receipt_id'], result['receipt_id'])
        self.assertNotIn('unique-erasure-phrase', json.dumps(self.store.bootstrap()))

    def test_device_auth_command_ack_and_no_fake_success(self):
        item = self.store.save('devices', {'device_id': 'mac'})
        token = self.store.issue_device_token(item['id'])
        self.assertTrue(self.store.authenticate_device('mac', token))
        self.assertFalse(self.store.authenticate_device('mac', 'wrong'))
        self.assertNotIn('token_hash', json.dumps(self.store.bootstrap()))
        cmd = self.store.queue_command(item['id'], {'type': 'self_check'})
        self.assertEqual(self.store.commands('mac')[0]['status'], 'queued')
        self.store.acknowledge('mac', cmd['id'], {'status': 'unsupported'})
        self.assertEqual(self.store.commands(item['id']), [])

    def test_summary_uses_only_real_data(self):
        self.assertEqual(self.store.summary()['total_tokens'], 0)
        self.assertIsNone(self.store.summary()['avg_latency_ms'])
        self.store.record_event('llm_request', 'mac', total_tokens=21, latency_ms=300)
        self.assertEqual(self.store.summary()['total_tokens'], 21)
        self.assertEqual(self.store.summary()['avg_latency_ms'], 300)

    def test_user_deletion_clears_personal_data_and_device_binding(self):
        user = self.store.save('users', {'name': 'Alice', 'voiceprint_id': 'private-voiceprint'})
        device = self.store.save('devices', {'device_id': 'mac', 'user_id': user['id'], 'guest_mode': False})
        self.store.save('memories', {'user_id': user['id'], 'content': 'private'})
        self.store.save('conversations', {'user_id': user['id'], 'query': 'private'})
        result = self.store.delete('users', user['id'])
        self.assertEqual(result['external_status'], 'needs_integration')
        self.assertEqual(self.store.list('memories'), [])
        self.assertEqual(self.store.list('conversations'), [])
        self.assertTrue(self.store.get('devices', device['id'])['guest_mode'])
        self.assertEqual(self.store.get('devices', device['id'])['user_id'], '')

    def test_frontend_field_mapping_and_template_inheritance(self):
        role = self.store.save('roles', {'name': 'Helper', 'prompt': 'Short answers'})
        strategy = self.store.save('interaction', {'name': 'Quick', 'session_timeout': 60})
        template = self.store.save('templates', {'name': 'Everyday', 'role_id': role['id'], 'interaction_id': strategy['id']})
        device = self.store.save('devices', {'device_id': 'mac', 'template_id': template['id'], 'memory_scope': '共享设备可见'})
        config = self.store.device_config('mac')
        self.assertEqual(config['role']['id'], role['id'])
        self.assertEqual(config['interaction']['id'], strategy['id'])
        self.assertEqual(config['memory']['visibility'], 'shared_device')
        memory = self.store.save('memories', {'user_id': 'user', 'scope': 'shared', 'device_id': device['id']})
        self.assertEqual(memory['visibility'], 'shared_device')
        self.store.save('devices', {'template_id': ''}, device['id'])
        self.assertEqual(self.store.device_config('mac')['role'], {})


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.save('devices', {'device_id': 'mac', 'group': 'friends'})
        self.current = dt.datetime(2026, 11, 6, 2, 0, tzinfo=dt.timezone.utc)  # 10:00 Shanghai

    def tearDown(self):
        self.tmp.cleanup()

    def reminder(self, **extra):
        return self.store.save('reminders', dict({'name': 'Daily', 'type': '日程提醒', 'enabled': True,
                               'schedule_time': '09:30', 'message': 'Check your plan', 'daily_limit': 2,
                               'start_time': '09:00', 'end_time': '21:00', 'quiet_start': '22:00', 'quiet_end': '08:00'}, **extra))

    def test_cross_midnight_window(self):
        self.assertTrue(in_window('23:00', '22:00', '08:00'))
        self.assertTrue(in_window('07:59', '22:00', '08:00'))
        self.assertFalse(in_window('08:00', '22:00', '08:00'))
        self.assertFalse(in_window('12:00', '22:00', '08:00'))

    def test_persistent_dedup_disabled_and_daily_limit(self):
        rule = self.reminder()
        self.assertEqual(len(run_once(self.store, self.current)['queued']), 1)
        reopened = Store.from_db(self.store.db_path)
        self.assertEqual(len(run_once(reopened, self.current)['queued']), 0)
        self.store.save('reminders', {'enabled': False}, rule['id'])
        self.assertEqual(run_once(self.store, self.current + dt.timedelta(days=1))['queued'], [])
        self.store.save('reminders', {'enabled': True, 'daily_limit': 0}, rule['id'])
        self.assertEqual(run_once(self.store, self.current + dt.timedelta(days=1))['queued'], [])

    def test_no_fake_weather_anomaly_or_ota_completion(self):
        self.reminder(type='天气变化')
        self.reminder(type='设备异常')
        result = run_once(self.store, self.current, ota_check=True)
        self.assertEqual(len(result['queued']), 1)
        self.assertEqual(result['queued'][0]['status'], 'queued')
        self.assertTrue(any('needs_integration' in x['reason'] for x in result['skipped']))
        self.assertEqual(run_once(self.store, self.current + dt.timedelta(days=1), ota_check=True)['queued'], [])
        self.store.upsert_device('mac', environment={'battery_level': 10})
        self.assertEqual(len(run_once(self.store, self.current)['queued']), 1)

    def test_quiet_hours_and_unsubscribe(self):
        rule = self.reminder(start_time='00:00', end_time='00:00', schedule_time='00:00')
        self.assertEqual(run_once(self.store, self.current.replace(hour=23))['queued'], [])  # 07:00 local
        self.store.upsert_device('mac', reminder_unsubscribed_ids=[rule['id']])
        self.assertEqual(run_once(self.store, self.current)['queued'], [])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.server = ConsoleServer(('127.0.0.1', 0), self.store, 'administrator-secret')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, path, body=None, method='GET', token='administrator-secret', origin=None):
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_admin_auth_origin_and_crud(self):
        self.assertEqual(self.request('/api/bootstrap', token='bad')[0], 401)
        self.assertEqual(self.request('/api/bootstrap', origin='https://evil.example')[0], 403)
        code, body = self.request('/api/roles', {'name': '效率助手', 'prompt': '简洁回答'}, 'POST')
        self.assertEqual(code, 201)
        self.assertEqual(self.request('/api/roles/' + body['id'])[1]['name'], '效率助手')
        self.assertEqual(self.request('/api/events', {'kind': 'fake'}, 'POST')[0], 400)
        self.assertEqual(self.request('/api/roles/' + body['id'], method='DELETE')[0], 200)

    def test_device_credentials_are_independent_and_private_config_is_redacted(self):
        model = self.store.save('models', {'name': 'private', 'model_name': 'test', 'base_url': 'https://example.com/v1', 'api_key': 'top-secret'})
        device = self.store.save('devices', {'device_id': 'mac', 'model_id': model['id']})
        token = self.store.issue_device_token(device['id'])
        self.assertEqual(self.request('/api/device/mac/config')[0], 401)
        code, config = self.request('/api/device/mac/config', token=token)
        self.assertEqual(code, 200)
        self.assertNotIn('model', config)
        self.assertNotIn('top-secret', json.dumps(config))
        self.assertEqual(self.request('/api/device/mac/telemetry', {'latency_ms': 120}, 'POST', token=token)[0], 200)
        self.assertEqual(self.request('/api/bootstrap', token=token)[0], 401)
        self.request('/api/device/mac/telemetry', {'model_id': 'attacker-model', 'guest_mode': False, 'user_id': 'attacker', 'token_hash': 'attacker'}, 'POST', token=token)
        saved = self.store.get('devices', device['id'], True)
        self.assertEqual(saved['model_id'], model['id'])
        self.assertNotEqual(saved.get('user_id'), 'attacker')
        self.assertTrue(self.store.authenticate_device('mac', token))
        reminder = self.store.save('reminders', {'name': 'Reminder', 'allow_unsubscribe': True})
        status, response = self.request('/api/device/mac/reminders/unsubscribe', {'reminder_id': reminder['id']}, 'POST', token=token)
        self.assertEqual(status, 200)
        self.assertTrue(response['unsubscribed'])
        self.assertIn(reminder['id'], self.store._device('mac')['reminder_unsubscribed_ids'])

    def test_localhost_mode_rejects_dns_rebinding_host(self):
        self.server.admin_token = ''
        request = urllib.request.Request(self.base + '/api/bootstrap', headers={'Host': 'attacker.example'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.request('/api/bootstrap', token='')[0], 200)


class ModelTestTests(unittest.TestCase):
    def test_actual_connectivity_probe_and_provider_paths(self):
        requests = []
        class ModelHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                requests.append(self.path)
                if self.path.startswith('/redirect'):
                    self.send_response(307)
                    self.send_header('Location', '/v1/chat/completions')
                    self.end_headers()
                    return
                data = json.dumps({'choices': [{'message': {'content': 'OK'}}], 'content': [{'text': 'OK'}], 'candidates': [{'content': {'parts': [{'text': 'OK'}]}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store = Store(tmp)
                root = 'http://127.0.0.1:%d' % server.server_address[1]
                for provider, base, suffix in [('openai', root + '/v1', '/v1/chat/completions'),
                                               ('claude', root, '/v1/messages'),
                                               ('gemini', root, '/v1beta/models/test:generateContent')]:
                    config = {'provider': provider, 'base_url': base, 'model_name': 'test', 'api_key': 'mock-secret'}
                    result = test_model(store, config)
                    self.assertTrue(result['ok'])
                    self.assertEqual(requests[-1], suffix)
                    store.save('models', dict(config, enabled=True))
                with self.assertRaises(ValidationError):
                    test_model(store, {'provider': 'openai', 'base_url': root + '/redirect', 'model_name': 'test', 'api_key': 'not-forwarded'})
                self.assertEqual(requests[-1], '/redirect/chat/completions')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
