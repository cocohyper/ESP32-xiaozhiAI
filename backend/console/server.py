"""Run: python backend/console/server.py --host 127.0.0.1 --port 8004."""
from __future__ import annotations

import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from console.store import Store, ValidationError, COLLECTIONS, now, public


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValidationError('模型接口发生重定向，请填写最终接口地址后重试')


def test_model(store, payload):
    config = dict(payload)
    if config.get('id'):
        saved = store.get('models', config['id'], True)
        if not saved:
            raise KeyError(config['id'])
        config = dict(saved, **{k: v for k, v in payload.items() if not (k == 'api_key' and not v)})
    store._validate('models', dict(config, enabled=False))
    url = config['base_url'].rstrip('/')
    model = config['model_name']
    key = config.get('api_key', '')
    provider = str(config.get('provider', '')).lower()
    headers = {'Content-Type': 'application/json'}
    if provider in ('claude', 'anthropic'):
        endpoint = url if url.endswith('/messages') else url + ('/messages' if url.endswith('/v1') else '/v1/messages')
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        body = {'model': model, 'max_tokens': 8, 'messages': [{'role': 'user', 'content': 'Reply OK.'}]}
    elif provider == 'gemini':
        if not url.endswith(('/v1', '/v1beta')):
            url += '/v1beta'
        endpoint = url + '/models/' + urllib.parse.quote(model, safe='') + ':generateContent'
        headers['x-goog-api-key'] = key
        body = {'contents': [{'parts': [{'text': 'Reply OK.'}]}], 'generationConfig': {'maxOutputTokens': 8}}
    else:
        endpoint = url + ('' if url.endswith('/chat/completions') else '/chat/completions')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        body = {'model': model, 'messages': [{'role': 'user', 'content': 'Reply OK.'}], 'max_tokens': 8, 'stream': False}
    started = time.monotonic()
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=headers, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=min(max(float(config.get('timeout', 15)), 1), 30)) as response:
            data = json.loads(response.read(1024 * 1024))
        if not isinstance(data, dict) or data.get('error') or not any(data.get(k) for k in ('choices', 'content', 'candidates')):
            raise ValidationError('接口响应不包含有效的模型回答')
    except urllib.error.HTTPError as exc:
        raise ValidationError('模型接口返回 HTTP ' + str(exc.code) + '，请检查地址、模型名和密钥') from None
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        raise ValidationError('模型接口连接失败或超时，请检查网络与地址') from None
    except ValidationError:
        raise
    except (ValueError, UnicodeDecodeError):
        raise ValidationError('模型接口没有返回有效 JSON') from None
    store.register_test(config)
    store.record_event('model_test_passed', model_name=model, provider=provider)
    return {'ok': True, 'tested_at': now(), 'latency_ms': round((time.monotonic() - started) * 1000)}


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, admin_token='', static_dir=None):
        self.store = store
        self.admin_token = admin_token
        self.static_dir = Path(static_dir or Path(__file__).parent / 'static').resolve()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'XiaoZhiConsole/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(35)

    def log_message(self, fmt, *args):
        # Avoid logging URLs, headers, submitted configuration, or API keys.
        sys.stderr.write('%s %s\n' % (self.log_date_time_string(), self.command))

    def _send(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        if 'application/json' not in self.headers.get('Content-Type', ''):
            raise ValidationError('请使用 application/json 请求')
        body = self._body(1024 * 1024)
        try:
            def reject_constant(value):
                raise ValueError('Non-finite JSON value')
            value = json.loads(body or b'{}', parse_constant=reject_constant)
        except (ValueError, UnicodeDecodeError):
            raise ValidationError('JSON 格式错误') from None
        if not isinstance(value, dict):
            raise ValidationError('请求内容必须是 JSON 对象')
        return value

    def _body(self, limit):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            raise ValidationError('Content-Length 无效') from None
        if length < 0 or length > limit:
            raise ValidationError('请求内容过大')
        return self.rfile.read(length)

    def _authorized(self):
        origin = self.headers.get('Origin')
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get('Host'):
            self._send({'error': '不允许跨站请求'}, 403)
            return False
        expected = self.server.admin_token
        if not expected:
            host = urllib.parse.urlparse('http://' + self.headers.get('Host', '')).hostname
            try:
                local = host == 'localhost' or ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = False
            if not local:
                self._send({'error': '本地模式只能通过 localhost 或回环地址访问'}, 403)
                return False
        if expected:
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            if not hmac.compare_digest(expected, token):
                self._send({'error': '请输入管理员访问令牌'}, 401)
                return False
        return True

    def _file(self, path, attachment=False):
        if not path.is_file():
            self._send({'error': '文件不存在'}, 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(path.stat().st_size))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-cache')
        if attachment:
            self.send_header('Content-Disposition', 'attachment')
        self.end_headers()
        with path.open('rb') as stream:
            while chunk := stream.read(65536):
                self.wfile.write(chunk)

    def _handle(self):
        store = self.server.store
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        parts = [urllib.parse.unquote(part) for part in path.strip('/').split('/') if part]
        if not parts or parts[0] != 'api':
            if self.command != 'GET':
                self._send({'error': '不支持的请求'}, 405)
                return
            target = (self.server.static_dir / urllib.parse.unquote(path.lstrip('/') or 'index.html')).resolve()
            if not target.is_relative_to(self.server.static_dir):
                self._send({'error': '禁止访问'}, 403)
                return
            if not target.is_file() and not target.suffix:
                target = self.server.static_dir / 'index.html'
            self._file(target)
            return
        if len(parts) == 3 and parts[1] == 'downloads' and self.command == 'GET':
            # The unguessable 128-bit upload ID is a download capability used by ESP OTA.
            upload = store.get_upload(parts[2])
            if not upload:
                raise KeyError(parts[2])
            self._file(store.data_dir / 'uploads' / upload['stored_name'], attachment=True)
            return
        if len(parts) >= 4 and parts[1] == 'device':
            return self._device(parts)
        if not self._authorized():
            return
        if parts == ['api', 'health']:
            self._send({'ok': True, 'service': 'xiaozhi-console', 'version': '1.0.0'})
            return
        if parts == ['api', 'bootstrap'] and self.command == 'GET':
            self._send(store.bootstrap())
            return
        if parts == ['api', 'summary'] and self.command == 'GET':
            self._send(store.summary())
            return
        if parts == ['api', 'models', 'test'] and self.command == 'POST':
            self._send(test_model(store, self._json()))
            return
        if parts == ['api', 'uploads'] and self.command == 'POST':
            query = urllib.parse.parse_qs(parsed.query)
            item = store.save_upload(query.get('kind', [''])[0], query.get('filename', [''])[0], self._body(32 * 1024 * 1024))
            self._send(public(item), 201)
            return
        if len(parts) < 2 or parts[1] not in COLLECTIONS:
            raise KeyError(path)
        collection = parts[1]
        if collection == 'events' and self.command != 'GET':
            raise ValidationError('审计记录只读')
        if len(parts) == 2:
            if self.command == 'GET':
                self._send(store.list(collection))
                return
            if self.command == 'POST':
                payload = self._json()
                if collection == 'deletion_requests':
                    payload['status'] = 'pending'
                self._send(store.save(collection, payload), 201)
                return
        if len(parts) == 3:
            record_id = parts[2]
            if self.command == 'GET':
                item = store.get(collection, record_id)
                if not item:
                    raise KeyError(record_id)
                self._send(item)
                return
            if self.command == 'PUT':
                payload = self._json()
                if collection == 'deletion_requests' and 'status' in payload:
                    raise ValidationError('删除任务状态只能通过确认接口变更')
                self._send(store.save(collection, payload, record_id))
                return
            if self.command == 'DELETE':
                self._send(store.delete(collection, record_id))
                return
        if len(parts) == 4 and self.command == 'POST':
            record_id, action = parts[2:]
            payload = self._json()
            if action == 'clone':
                self._send(store.clone(collection, record_id), 201)
                return
            if action == 'rollback':
                self._send(store.rollback(collection, record_id))
                return
            if collection == 'deletion_requests' and action == 'confirm':
                self._send(store.confirm_deletion(record_id))
                return
            if collection == 'devices' and action == 'token':
                self._send({'device_id': record_id, 'token': store.issue_device_token(record_id)})
                return
            if collection == 'devices' and action == 'commands':
                self._send(store.queue_command(record_id, payload), 201)
                return
        if len(parts) == 4 and collection == 'devices' and parts[3] == 'commands' and self.command == 'GET':
            self._send(store.commands(parts[2]))
            return
        self._send({'error': '不支持的请求方法或操作'}, 405)

    def _device(self, parts):
        store = self.server.store
        device_id, action = parts[2:4]
        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
        if not store.authenticate_device(device_id, token):
            self._send({'error': '设备认证失败'}, 401)
            return
        if action == 'config' and self.command == 'GET':
            config = store.device_config(device_id)
            # Model credentials belong to the server, never to the device/browser.
            config.pop('model', None)
            config.pop('backup_model', None)
            self._send(public(config))
            return
        if action == 'telemetry' and self.command == 'POST':
            payload = self._json()
            allowed = ('firmware_version', 'board', 'chip', 'flash_mb', 'environment', 'ota_result')
            store.upsert_device(device_id, **{key: payload[key] for key in allowed if key in payload})
            event = store.record_event('telemetry', device_id, metrics=public(payload),
                                       **{key: payload[key] for key in ('total_tokens', 'latency_ms') if isinstance(payload.get(key), (int, float))})
            self._send({'accepted': True, 'event_id': event['id']})
            return
        if action == 'commands' and self.command == 'GET':
            self._send(store.commands(device_id))
            return
        if action == 'reminders' and len(parts) == 5 and parts[4] == 'unsubscribe' and self.command == 'POST':
            payload = self._json()
            reminder_id = payload.get('reminder_id', '')
            rule = store.get('reminders', reminder_id)
            if not rule:
                raise KeyError(reminder_id)
            if rule.get('allow_unsubscribe', True) is False:
                raise ValidationError('该提醒由管理员管理，请联系管理员关闭')
            device = store._device(device_id)
            unsubscribed = list(set(device.get('reminder_unsubscribed_ids', []) + [reminder_id]))
            store.upsert_device(device_id, reminder_unsubscribed_ids=unsubscribed)
            store.record_event('reminder_unsubscribed', device_id, reminder_id=reminder_id)
            self._send({'unsubscribed': True, 'reminder_id': reminder_id})
            return
        if action == 'commands' and len(parts) == 6 and parts[5] == 'ack' and self.command == 'POST':
            self._send(store.acknowledge(device_id, parts[4], self._json()))
            return
        self._send({'error': '设备接口不存在'}, 404)

    def _dispatch(self):
        try:
            self._handle()
        except ValidationError as exc:
            self._send({'error': str(exc)}, 400)
        except KeyError:
            self._send({'error': '记录不存在'}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._send({'error': '操作失败，请检查服务日志与输入配置'}, 500)

    do_GET = _dispatch
    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch


def main():
    parser = argparse.ArgumentParser(description='小智管理控制台')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8004)
    parser.add_argument('--data-dir', default=str(Path(__file__).resolve().parents[1] / 'data' / 'console'))
    args = parser.parse_args()
    token = os.environ.get('CONSOLE_ADMIN_TOKEN', '')
    if args.host not in ('127.0.0.1', 'localhost', '::1') and len(token) < 24:
        parser.error('非回环监听需设置至少 24 字符的 CONSOLE_ADMIN_TOKEN；建议通过 HTTPS 反向代理访问')
    server = ConsoleServer((args.host, args.port), Store(args.data_dir), token)
    print('XiaoZhi console: http://%s:%d' % server.server_address[:2], flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
