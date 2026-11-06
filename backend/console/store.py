"""Thread-safe SQLite repository. No third-party dependencies required."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import threading
import uuid
from urllib.parse import urlparse

COLLECTIONS = ('devices firmware rollouts resources models voices voice_rules users memories '
               'conversations deletion_requests vision roles interaction reminders intents safety '
               'feedback evaluations experiments templates events').split()
SECRET_FIELDS = {'api_key', 'token', 'device_token', 'secret', 'password', 'access_token'}
IMMUTABLE = {'id', 'created_at', 'updated_at', 'token_hash', 'test_fingerprint', 'tested_at'}
VERSIONED = {'templates', 'resources', 'interaction', 'roles', 'safety'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def public(value):
    if isinstance(value, list):
        return [public(x) for x in value]
    if isinstance(value, dict):
        result = {k: public(v) for k, v in value.items()
                  if k not in SECRET_FIELDS | {'token_hash', 'test_fingerprint', '_history'}}
        for key in SECRET_FIELDS:
            if value.get(key):
                result[key + '_configured'] = True
        return result
    return value


def fingerprint(model):
    fields = {k: model.get(k, '') for k in ('provider', 'base_url', 'model_name', 'api_key')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


class ValidationError(ValueError):
    pass


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / 'console.sqlite3'
        self._lock = threading.RLock()
        self._init()

    @classmethod
    def from_db(cls, path):
        obj = cls.__new__(cls)
        obj.db_path = Path(path).resolve()
        obj.data_dir = obj.db_path.parent
        obj.data_dir.mkdir(parents=True, exist_ok=True)
        obj._lock = threading.RLock()
        obj._init()
        return obj

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            with conn:
                yield conn
        finally:
            conn.close()

    def _init(self):
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (collection TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(collection,id))')
            db.execute('CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS tests (fingerprint TEXT PRIMARY KEY, tested_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, device_id TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS scheduled (dedup_key TEXT PRIMARY KEY, rule_id TEXT, device_id TEXT, local_day TEXT, command_id TEXT)')
        (self.data_dir / 'uploads').mkdir(exist_ok=True)
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def _collection(self, collection):
        if collection not in COLLECTIONS:
            raise ValidationError('未知数据类型')

    def _all(self, collection):
        self._collection(collection)
        with self._connect() as db:
            rows = db.execute('SELECT data FROM records WHERE collection=? ORDER BY rowid DESC', (collection,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list(self, collection, include_secrets=False):
        rows = self._all(collection)
        return rows if include_secrets else public(rows)

    def get(self, collection, record_id, include_secrets=False):
        self._collection(collection)
        with self._connect() as db:
            row = db.execute('SELECT data FROM records WHERE collection=? AND id=?', (collection, str(record_id))).fetchone()
        if not row:
            return None
        data = json.loads(row[0])
        return data if include_secrets else public(data)

    def _write(self, collection, item):
        with self._connect() as db:
            db.execute('INSERT INTO records(collection,id,data) VALUES(?,?,?) ON CONFLICT(collection,id) DO UPDATE SET data=excluded.data',
                       (collection, item['id'], json.dumps(item, ensure_ascii=False)))

    def save(self, collection, payload, record_id=None, actor='admin'):
        self._collection(collection)
        if not isinstance(payload, dict):
            raise ValidationError('请求内容必须是 JSON 对象')
        with self._lock:
            old = self.get(collection, record_id, True) if record_id else None
            if record_id and not old:
                raise KeyError(record_id)
            item = copy.deepcopy(old or {})
            for key, value in payload.items():
                if key in IMMUTABLE or key.startswith('_') or key.endswith('_configured'):
                    continue
                if key in SECRET_FIELDS and not value:
                    continue
                item[key] = value
            item['id'] = str(record_id or uuid.uuid4().hex)
            item['created_at'] = item.get('created_at', now())
            item['updated_at'] = now()
            if not str(item.get('name', '')).strip():
                item['name'] = str(item.get('device_id') or item.get('version') or item.get('content') or item['id'])[:100]
            self._validate(collection, item)
            if collection in VERSIONED:
                history = (old or {}).get('_history', [])
                if old:
                    history = history + [{k: v for k, v in old.items() if k != '_history'}]
                item['_history'] = history[-20:]
                item['revision'] = (old or {}).get('revision', 0) + 1
            self._write(collection, item)
            if collection != 'events':
                audit_name = collection if collection in ('users', 'memories', 'conversations', 'deletion_requests') else item['name']
                self.record_event('config_updated' if old else 'config_created', collection=collection,
                                  record_id=item['id'], actor=actor, name=audit_name)
            return public(item)

    def _validate(self, collection, item):
        if len(json.dumps(item)) > 256000:
            raise ValidationError('单条配置不可超过 256KB')
        for field in ('enabled', 'force', 'check_environment', 'guest_mode', 'cloned'):
            if field in item and not isinstance(item[field], bool):
                raise ValidationError(field + ' 必须为布尔值')
        for field in ('base_url', 'ota_url', 'url', 'download_url', 'sample_url'):
            if item.get(field):
                url = urlparse(str(item[field]))
                if not (url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password) and not (field == 'download_url' and str(item[field]).startswith('/api/downloads/')):
                    raise ValidationError(field + ' 必须为 HTTP(S) 地址且不包含账号密码')
        for field in ('rollout_percent', 'percentage', 'volume', 'threshold_percent'):
            if field in item:
                value = item[field]
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not 0 <= value <= 100:
                    raise ValidationError(field + ' 必须在 0–100 之间')
        for field in ('window_start', 'window_end', 'quiet_start', 'quiet_end'):
            if item.get(field) and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(item[field])):
                raise ValidationError(field + ' 格式必须为 HH:MM')
        for field in ('start_time', 'end_time'):
            if item.get(field) and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(item[field])):
                raise ValidationError(field + ' 格式必须为 HH:MM')
        if collection == 'devices':
            if item.get('device_id') and any(x.get('device_id') == item['device_id'] and x['id'] != item['id'] for x in self._all('devices')):
                raise ValidationError('该设备 ID 已存在')
            if item.get('chip') not in (None, '', 'ESP32', 'ESP32-S3', 'ESP32-C3', 'ESP32-C6', 'ESP32-P4', 'ESP32-S2'):
                raise ValidationError('不支持的芯片型号')
            if item.get('custom_wake_word') and (item.get('chip') != 'ESP32-S3' or int(item.get('flash_mb', 0)) < 16):
                raise ValidationError('自定义唤醒词仅对 ESP32-S3 且至少 16MB Flash 开放')
            for key, target in (('model_id', 'models'), ('fallback_model_id', 'models'), ('backup_model_id', 'models'), ('role_id', 'roles'), ('voice_id', 'voices'), ('user_id', 'users'), ('template_id', 'templates'), ('interaction_id', 'interaction')):
                if item.get(key) and not self.get(target, item[key]):
                    raise ValidationError(key + ' 引用不存在')
        if collection == 'models':
            if not item.get('model_name') or not item.get('base_url'):
                raise ValidationError('模型名称和接口地址必填')
            if not isinstance(item['model_name'], str) or not isinstance(item['base_url'], str):
                raise ValidationError('模型名称和接口地址必须为文本')
            if item.get('timeout') is not None:
                try:
                    valid_timeout = 1 <= float(item['timeout']) <= 300
                except (TypeError, ValueError):
                    valid_timeout = False
                if not valid_timeout:
                    raise ValidationError('模型超时须为 1–300 秒')
            if item.get('enabled', False):
                with self._connect() as db:
                    test = db.execute('SELECT tested_at FROM tests WHERE fingerprint=?', (fingerprint(item),)).fetchone()
                if not test:
                    raise ValidationError('模型必须先通过连通性测试，才能启用')
                item['tested_at'] = test[0]
        if collection in ('firmware', 'resources'):
            if collection == 'firmware' and not item.get('version'):
                raise ValidationError('固件版本号必填')
            if item.get('upload_id'):
                upload = self.get_upload(item['upload_id'])
                if not upload or upload['kind'] != collection:
                    raise ValidationError('上传文件不存在或类型不匹配')
                item.update({k: upload[k] for k in ('sha256', 'size', 'download_url')})
                if collection == 'firmware' and item.get('chip') and upload.get('chip') and item['chip'] != upload['chip']:
                    raise ValidationError('固件镜像芯片与所选芯片不匹配')
            if item.get('custom_wake_word') and (item.get('chip') != 'ESP32-S3' or int(item.get('flash_mb', 0)) < 16):
                raise ValidationError('该芯片或 Flash 容量不支持自定义唤醒词')
            if collection == 'resources' and item.get('resource_type') == 'emotions' and not (item.get('emotions') or {}).get('neutral'):
                raise ValidationError('表情映射必须包含 neutral 默认图')
            if collection == 'resources' and any(item.get(tag) for tag in ('happy', 'sad', 'thinking')) and not item.get('neutral'):
                raise ValidationError('表情映射必须包含 neutral 默认图')
            if not item.get('upload_id'):
                item['status'] = 'needs_integration' if collection == 'resources' else 'draft'
        if collection == 'rollouts':
            if not self.get('firmware', item.get('firmware_id', '')):
                raise ValidationError('请选择有效的固件版本')
            firmware = self.get('firmware', item['firmware_id'])
            if item.get('enabled') and not firmware.get('upload_id'):
                raise ValidationError('启用发布前必须上传固件文件')
        if collection in ('voices', 'evaluations') and item.get('kind') in ('clone', 'voice_clone', 'hardware'):
            item['status'] = 'needs_integration'
        if collection == 'voices' and item.get('cloned'):
            item['status'] = 'needs_integration'
        if collection == 'deletion_requests' and not item.get('user_id'):
            raise ValidationError('删除申请必须指定用户')
        if collection == 'memories':
            if not item.get('user_id'):
                raise ValidationError('记忆必须指定所属用户')
            if 'scope' in item:
                item['visibility'] = {'private': 'private', 'shared': 'shared_device', 'device': 'shared_device'}.get(item['scope'], item['scope'])
            if item.get('visibility', 'private') not in ('private', 'device', 'shared_device'):
                raise ValidationError('记忆可见范围无效')
        if collection == 'experiments' and item.get('enabled'):
            item['status'] = 'configured' if item.get('target') in ('开场白', '回复风格', '追问策略') else 'pending_integration'
        if collection == 'evaluations':
            item.setdefault('status', 'pending')

    def delete(self, collection, record_id, actor='admin'):
        self._collection(collection)
        if collection == 'events':
            raise ValidationError('审计记录不可删除')
        with self._lock:
            old = self.get(collection, record_id)
            if not old:
                raise KeyError(record_id)
            refs = {'models': ('model_id', 'fallback_model_id', 'backup_model_id'), 'roles': ('role_id',),
                    'voices': ('voice_id',), 'templates': ('template_id',), 'interaction': ('interaction_id',),
                    'safety': ('safety_id',), 'resources': ('resource_id',)}
            for field in refs.get(collection, ()):
                if any(x.get(field) == record_id for x in self._all('devices') + self._all('templates')):
                    raise ValidationError('该配置仍被设备或模板使用，请先解除绑定')
            if collection == 'firmware' and any(x.get('firmware_id') == record_id for x in self._all('rollouts')):
                raise ValidationError('固件仍被发布策略引用，请先删除对应发布策略')
            with self._connect() as db:
                db.execute('DELETE FROM records WHERE collection=? AND id=?', (collection, record_id))
                redacted = {(collection, record_id)}
                if collection == 'users':
                    for related in ('memories', 'conversations'):
                        for row in self._all(related):
                            if row.get('user_id') == record_id:
                                db.execute('DELETE FROM records WHERE collection=? AND id=?', (related, row['id']))
                                redacted.add((related, row['id']))
                    for device in self._all('devices'):
                        if device.get('user_id') == record_id:
                            device.update(user_id='', guest_mode=True, updated_at=now())
                            db.execute('UPDATE records SET data=? WHERE collection=? AND id=?',
                                       (json.dumps(device, ensure_ascii=False), 'devices', device['id']))
                if collection in ('users', 'memories', 'conversations'):
                    self._redact_audits(db, redacted)
            self.record_event('config_deleted', collection=collection, record_id=record_id, actor=actor)
            if collection == 'users':
                self.record_event('user_local_data_deleted', user_id=record_id,
                                  scope=['user_profile', 'voiceprint_mapping', 'memories', 'conversations', 'device_user_binding'],
                                  external_status='needs_integration')
        result = {'deleted': True, 'id': record_id}
        if collection == 'users':
            result['external_status'] = 'needs_integration'
        return result

    def _redact_audits(self, db, deleted_ids):
        """Keep deletion evidence while removing legacy personal display names/content."""
        for event in self._all('events'):
            if (event.get('collection'), event.get('record_id')) in deleted_ids:
                event['name'] = '已删除记录'
                db.execute('UPDATE records SET data=? WHERE collection=? AND id=?',
                           (json.dumps(event, ensure_ascii=False), 'events', event['id']))

    def clone(self, collection, record_id):
        item = self.get(collection, record_id, True)
        if not item:
            raise KeyError(record_id)
        item['name'] += ' · 副本'
        item['enabled'] = False
        if collection == 'devices':
            item.pop('device_id', None)
        for key in IMMUTABLE | SECRET_FIELDS:
            item.pop(key, None)
        return self.save(collection, item)

    def rollback(self, collection, record_id):
        if collection not in VERSIONED:
            raise ValidationError('该类型不支持配置版本回滚')
        with self._lock:
            item = self.get(collection, record_id, True)
            if not item:
                raise KeyError(record_id)
            history = item.get('_history', [])
            if not history:
                raise ValidationError('没有上一可用版本')
            previous = history[-1]
            previous['_history'] = history[:-1]
            previous['updated_at'] = now()
            self._write(collection, previous)
            self.record_event('config_rollback', collection=collection, record_id=record_id)
            return public(previous)

    def record_event(self, kind, device_id=None, **fields):
        event = public(dict(fields, id=uuid.uuid4().hex, kind=kind, device_id=device_id,
                            name=fields.get('name', kind), created_at=now(), updated_at=now()))
        self._write('events', event)
        return event

    def upsert_device(self, device_id, **fields):
        with self._lock:
            existing = self._device(device_id) or {'id': device_id, 'device_id': device_id, 'name': device_id, 'created_at': now()}
            existing.update({k: v for k, v in fields.items() if k not in SECRET_FIELDS | IMMUTABLE})
            existing['last_seen'] = now()
            existing['updated_at'] = now()
            self._write('devices', existing)
            return public(existing)

    def _device(self, device_id):
        return self.get('devices', device_id, True) or next((x for x in self._all('devices') if x.get('device_id') == device_id), None)

    def device_config(self, device_id):
        device = self._device(device_id) or {}
        template = self.get('templates', device.get('template_id', ''), True) or {}
        def linked(field, collection):
            return self.get(collection, device.get(field) or template.get(field) or '', True) or {}
        interaction = linked('interaction_id', 'interaction') or template.get('interaction', {})
        visibility = device.get('memory_scope', device.get('memory_visibility', 'private'))
        visibility = {'仅本人可见': 'private', '共享设备可见': 'shared_device', 'shared': 'shared_device'}.get(visibility, visibility)
        role = linked('role_id', 'roles')
        voice = linked('voice_id', 'voices') or self.get('voices', role.get('voice_id', ''), True) or {}
        return {'device': public(device), 'model': linked('model_id', 'models'),
                'backup_model': linked('fallback_model_id', 'models') or linked('backup_model_id', 'models'), 'role': role,
                'voice': voice, 'interaction': interaction,
                'safety': linked('safety_id', 'safety'),
                'memory': {'guest_mode': device.get('guest_mode', True), 'user_id': device.get('user_id'),
                           'visibility': visibility},
                'templates': [public(template)] if template else []}

    def select_firmware(self, device_id, current_version, board='', environment=None):
        device = self._device(device_id) or {}
        environment = environment or device.get('environment') or {}
        def version(value):
            parts = [int(x) for x in re.findall(r'\d+', str(value))]
            while parts and parts[-1] == 0:
                parts.pop()
            return tuple(parts)
        for rollout in self._all('rollouts'):
            if not rollout.get('enabled'):
                continue
            targets = rollout.get('device_ids', [])
            if targets and device_id not in targets and device.get('id') not in targets:
                continue
            if rollout.get('group') and rollout['group'] != device.get('group'):
                continue
            percent = rollout.get('rollout_percent', rollout.get('percentage', 100))
            bucket = int(hashlib.sha256((rollout['id'] + device_id).encode()).hexdigest()[:8], 16) % 100
            if bucket >= percent:
                continue
            start, end = rollout.get('start_time', rollout.get('window_start')), rollout.get('end_time', rollout.get('window_end'))
            clock = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).strftime('%H:%M')
            if start and end and start != end:
                allowed = start <= clock < end if start < end else clock >= start or clock < end
                if not allowed:
                    continue
            if rollout.get('check_environment', rollout.get('require_power', True)) and environment.get('power_stable') is not True:
                continue
            if rollout.get('check_environment', rollout.get('require_network', True)) and environment.get('network_stable') is not True:
                continue
            fw = self.get('firmware', rollout.get('firmware_id', ''), True)
            if not fw or not fw.get('upload_id') or not self.get_upload(fw['upload_id']):
                continue
            if fw.get('board') and fw['board'] != board:
                continue
            if fw.get('chip') and fw['chip'] != device.get('chip'):
                continue
            if version(fw['version']) <= version(current_version) and not rollout.get('rollback'):
                continue
            return public(dict(fw, force=bool(rollout.get('force') or rollout.get('rollback')),
                               rollback=bool(rollout.get('rollback')), rollout_id=rollout['id']))
        return None

    def register_test(self, model):
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO tests VALUES(?,?)', (fingerprint(model), now()))

    def issue_device_token(self, device_id):
        item = self._device(device_id)
        if not item:
            raise KeyError(device_id)
        token = secrets.token_urlsafe(32)
        item['token_hash'] = hashlib.sha256(token.encode()).hexdigest()
        self._write('devices', item)
        self.record_event('device_token_rotated', device_id)
        return token

    def authenticate_device(self, device_id, token):
        item = self._device(device_id) or {}
        expected = item.get('token_hash', '')
        return bool(expected and token and hmac.compare_digest(expected, hashlib.sha256(token.encode()).hexdigest()))

    def get_upload(self, upload_id):
        with self._connect() as db:
            row = db.execute('SELECT data FROM uploads WHERE id=?', (upload_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_upload(self, kind, filename, content):
        if kind not in ('firmware', 'resources'):
            raise ValidationError('上传类型必须为 firmware 或 resources')
        if not filename or Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValidationError('无效的文件名')
        if not content or len(content) > 32 * 1024 * 1024:
            raise ValidationError('文件大小须为 1B–32MB')
        suffix = Path(filename).suffix.lower()
        if kind == 'firmware':
            if suffix != '.bin' or len(content) < 24 or content[0] != 0xE9 or not 1 <= content[1] <= 16:
                raise ValidationError('固件必须是有效 ESP 应用镜像 .bin（首字节 E9），不能使用合并烧录镜像')
            if len(content) < 36 or struct.unpack_from('<I', content, 32)[0] != 0xABCD5432:
                raise ValidationError('未找到 ESP 应用描述头；请上传 app.bin，不可上传 bootloader 或合并镜像')
            cursor, checksum = 24, 0xEF
            for _ in range(content[1]):
                if cursor + 8 > len(content):
                    raise ValidationError('固件段头不完整')
                segment_size = struct.unpack_from('<I', content, cursor + 4)[0]
                cursor += 8
                if cursor + segment_size > len(content):
                    raise ValidationError('固件段长度超出文件范围')
                for byte in content[cursor:cursor + segment_size]:
                    checksum ^= byte
                cursor += segment_size
            checksum_offset = (cursor // 16 + 1) * 16 - 1
            if checksum_offset >= len(content) or content[checksum_offset] != checksum:
                raise ValidationError('固件校验和不匹配，文件可能损坏')
            if content[23] == 1:
                offset = checksum_offset + 1
                if content[offset:offset + 32] != hashlib.sha256(content[:offset]).digest():
                    raise ValidationError('固件内嵌 SHA256 校验失败')
        elif suffix not in ('.bin', '.png', '.gif'):
            raise ValidationError('资源仅支持 .bin、PNG、GIF')
        elif suffix == '.png' and not content.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValidationError('PNG 文件签名无效')
        elif suffix == '.gif' and content[:6] not in (b'GIF87a', b'GIF89a'):
            raise ValidationError('GIF 文件签名无效')
        dimensions = None
        if kind == 'resources' and suffix in ('.png', '.gif'):
            if suffix == '.png' and len(content) >= 24 and content[12:16] == b'IHDR':
                dimensions = struct.unpack_from('>II', content, 16)
            elif suffix == '.gif' and len(content) >= 10:
                dimensions = struct.unpack_from('<HH', content, 6)
            if not dimensions or not all(1 <= x <= 1024 for x in dimensions):
                raise ValidationError('表情图片尺寸须为 1–1024 像素，且图像头完整')
        upload_id = uuid.uuid4().hex
        path = self.data_dir / 'uploads' / (upload_id + suffix)
        path.write_bytes(content)
        item = {'id': upload_id, 'upload_id': upload_id, 'kind': kind, 'filename': filename,
                'stored_name': path.name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
                'download_url': '/api/downloads/' + upload_id, 'created_at': now()}
        if dimensions:
            item.update(width=dimensions[0], height=dimensions[1])
        if kind == 'firmware':
            chip_id = struct.unpack_from('<H', content, 12)[0]
            chip = {0: 'ESP32', 2: 'ESP32-S2', 5: 'ESP32-C3', 9: 'ESP32-S3', 13: 'ESP32-C6', 18: 'ESP32-P4'}.get(chip_id)
            item.update(chip_id=chip_id, chip=chip)
        with self._connect() as db:
            db.execute('INSERT INTO uploads VALUES(?,?)', (upload_id, json.dumps(item)))
        self.record_event('file_uploaded', collection=kind, upload_id=upload_id, name=filename)
        return item

    def confirm_deletion(self, record_id):
        request = self.get('deletion_requests', record_id, True)
        if not request:
            raise KeyError(record_id)
        if request.get('status') in ('completed', 'completed_local'):
            return public(request)
        user_id = request['user_id']
        deleted = {'memories': 0, 'conversations': 0}
        with self._lock, self._connect() as db:
            redacted = set()
            for collection in deleted:
                for row in self._all(collection):
                    if row.get('user_id') == user_id:
                        db.execute('DELETE FROM records WHERE collection=? AND id=?', (collection, row['id']))
                        redacted.add((collection, row['id']))
                        deleted[collection] += 1
            self._redact_audits(db, redacted)
            request.update(status='completed_local', completed_at=now(), deleted_counts=deleted,
                           external_status='needs_integration', receipt_id=uuid.uuid4().hex)
            db.execute('UPDATE records SET data=? WHERE collection=? AND id=?',
                       (json.dumps(request, ensure_ascii=False), 'deletion_requests', record_id))
        self.record_event('memory_deletion_confirmed', user_id=user_id, receipt_id=request['receipt_id'], deleted_counts=deleted)
        return public(request)

    def queue_command(self, device_id, payload):
        device = self._device(device_id)
        if not device:
            raise KeyError(device_id)
        device_id = device.get('device_id') or device['id']
        if payload.get('type') not in ('self_check', 'check_ota', 'rollback', 'apply_config', 'capture', 'reboot', 'reminder'):
            raise ValidationError('不支持的设备指令')
        command = dict(public(payload), id=uuid.uuid4().hex, device_id=device_id, status='queued', created_at=now())
        with self._connect() as db:
            db.execute('INSERT INTO commands VALUES(?,?,?)', (command['id'], device_id, json.dumps(command)))
        self.record_event('command_queued', device_id, command_id=command['id'], command_type=command['type'])
        return command

    def queue_scheduled_command(self, device_id, payload, dedup_key, rule_id, local_day, daily_limit=20):
        """Queue + durable deduplication in one transaction, safe across scheduler processes."""
        device = self._device(device_id)
        if not device or device.get('enabled') is False or daily_limit <= 0:
            return None
        device_id = device.get('device_id') or device['id']
        if payload.get('type') not in ('check_ota', 'reminder'):
            raise ValidationError('不支持的调度指令')
        command = dict(public(payload), id=uuid.uuid4().hex, device_id=device_id,
                       status='queued', created_at=now(), source='scheduler', rule_id=rule_id)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM scheduled WHERE dedup_key=?', (dedup_key,)).fetchone():
                return None
            count = db.execute('SELECT COUNT(*) FROM scheduled WHERE rule_id=? AND device_id=? AND local_day=?',
                               (rule_id, device_id, local_day)).fetchone()[0]
            if count >= daily_limit:
                return None
            if payload.get('type') == 'check_ota':
                existing = db.execute('SELECT data FROM commands WHERE device_id=?', (device_id,)).fetchall()
                if any(json.loads(row[0]).get('type') == 'check_ota' and json.loads(row[0]).get('status') == 'queued' for row in existing):
                    return None
            db.execute('INSERT INTO commands VALUES(?,?,?)', (command['id'], device_id, json.dumps(command)))
            db.execute('INSERT INTO scheduled VALUES(?,?,?,?,?)', (dedup_key, rule_id, device_id, local_day, command['id']))
        self.record_event('scheduled_command_queued', device_id, command_id=command['id'], command_type=command['type'], rule_id=rule_id)
        return command

    def commands(self, device_id):
        device = self._device(device_id) or {}
        device_id = device.get('device_id') or device.get('id') or device_id
        with self._connect() as db:
            rows = db.execute('SELECT data FROM commands WHERE device_id=? ORDER BY rowid', (device_id,)).fetchall()
        return [x for x in (json.loads(row[0]) for row in rows) if x.get('status') == 'queued']

    def acknowledge(self, device_id, command_id, payload):
        device = self._device(device_id) or {}
        device_id = device.get('device_id') or device.get('id') or device_id
        with self._connect() as db:
            row = db.execute('SELECT data FROM commands WHERE id=? AND device_id=?', (command_id, device_id)).fetchone()
            if not row:
                raise KeyError(command_id)
            item = json.loads(row[0])
            if payload.get('status') not in ('completed', 'failed', 'unsupported'):
                raise ValidationError('回执状态必须为 completed、failed 或 unsupported')
            item.update(status=payload['status'], result=public(payload.get('result')), acknowledged_at=now())
            db.execute('UPDATE commands SET data=? WHERE id=?', (json.dumps(item), command_id))
        self.record_event('command_acknowledged', device_id, command_id=command_id, status=item['status'])
        return item

    def summary(self):
        events = self._all('events')
        devices = self._all('devices')
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()
        online = sum(1 for x in devices if x.get('last_seen', '') > cutoff)
        metrics = [e for e in events if e.get('kind') in ('telemetry', 'llm_request', 'conversation')]
        total_tokens = sum(float(e.get('total_tokens') or 0) for e in metrics if isinstance(e.get('total_tokens', 0), (int, float)))
        latency = [float(e['latency_ms']) for e in metrics if isinstance(e.get('latency_ms'), (int, float))]
        first_token = [float(e.get('llm_first_token_ms', e.get('first_token_ms'))) for e in metrics
                       if isinstance(e.get('llm_first_token_ms', e.get('first_token_ms')), (int, float))]
        today = now()[:10]
        return {'devices': len(devices), 'online_devices': online, 'total_tokens': int(total_tokens),
                'conversations': len(self._all('conversations')), 'feedback': len(self._all('feedback')),
                'models': len(self._all('models')), 'active_models': sum(bool(x.get('enabled')) for x in self._all('models')),
                'avg_latency_ms': round(sum(latency) / len(latency)) if latency else None,
                'avg_first_token_ms': round(sum(first_token) / len(first_token)) if first_token else None,
                'daily_active_devices': len({e['device_id'] for e in events if e.get('device_id') and e.get('created_at', '').startswith(today)}),
                'pending_deletions': sum(x.get('status', 'pending') == 'pending' for x in self._all('deletion_requests')),
                'events': len(events), 'updated_at': now()}

    def bootstrap(self):
        return {'collections': {key: self.list(key) for key in COLLECTIONS}, 'summary': self.summary(),
                'capabilities': {'persistent_storage': True, 'model_connectivity_test': True,
                    'firmware_upload': True, 'resource_upload': True, 'device_telemetry': True,
                    'voice_cloning': 'needs_integration', 'resource_generation': 'needs_integration',
                    'hardware_evaluation': 'needs_integration', 'external_memory_deletion': 'needs_integration',
                    'wakenet': {'ESP32-S3': 'custom_with_assets_16mb', 'ESP32-C3': 'wakenet9s', 'ESP32-C6': 'wakenet9s'}}}
