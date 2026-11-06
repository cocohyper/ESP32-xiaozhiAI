"""One scheduler tick. Invoke with cron/systemd; this module installs no system jobs.

python backend/console/scheduler.py --data-dir backend/data/console --ota-check
Commands remain queued until the device reports its real execution result.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from console.store import Store, ValidationError

SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def in_window(clock, start, end, equal_all_day=True):
    if not start or not end:
        return True
    if not all(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value) for value in (start, end)):
        raise ValidationError('时间窗须为 HH:MM')
    if start == end:
        return equal_all_day
    return start <= clock < end if start < end else clock >= start or clock < end


def device_anomaly(device):
    environment = device.get('environment') or {}
    if isinstance(environment.get('battery_level'), (int, float)) and environment['battery_level'] < 20:
        return '设备电量低于 20%，请检查供电。'
    result = device.get('ota_result') or {}
    if isinstance(result, dict) and result.get('status') in ('failed', 'error'):
        return '设备报告升级失败，请检查升级结果。'
    if environment.get('network_stable') is False:
        return '设备报告网络不稳定，请检查连接。'
    return None


def run_once(store, current=None, ota_check=False, ota_interval_minutes=1440, dry_run=False):
    if ota_interval_minutes < 1:
        raise ValidationError('OTA 检查间隔必须至少 1 分钟')
    current = current or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValidationError('调度时间必须带时区')
    local = current.astimezone(SHANGHAI)
    day, clock = local.strftime('%Y-%m-%d'), local.strftime('%H:%M')
    devices = [device for device in store.list('devices') if device.get('enabled') is not False]
    result = {'queued': [], 'skipped': [], 'local_time': local.isoformat(), 'dry_run': dry_run}
    def enqueue(device, payload, dedup, rule, limit):
        identifier = device.get('device_id') or device['id']
        if dry_run:
            result['queued'].append(dict(payload, device_id=identifier, status='would_queue'))
            return
        command = store.queue_scheduled_command(identifier, payload, dedup, rule, day, limit)
        if command:
            result['queued'].append(command)
        else:
            result['skipped'].append({'device_id': identifier, 'rule_id': rule, 'reason': '已排队、已处理或达到当日频率上限'})
    if ota_check:
        bucket = int(current.timestamp()) // (ota_interval_minutes * 60)
        for device in devices:
            if device.get('ota_schedule_enabled') is False:
                continue
            identifier = device.get('device_id') or device['id']
            enqueue(device, {'type': 'check_ota'}, 'ota:%s:%s' % (identifier, bucket), 'ota', 1440)
    for rule in store.list('reminders'):
        if not rule.get('enabled'):
            continue
        kind = rule.get('type')
        if kind not in ('日程提醒', 'schedule', '设备异常', 'device_anomaly'):
            result['skipped'].append({'rule_id': rule['id'], 'reason': 'needs_integration：该提醒类型需要外部数据适配器'})
            continue
        try:
            if not in_window(clock, rule.get('start_time'), rule.get('end_time')):
                continue
            if rule.get('quiet_start') and rule.get('quiet_end') and in_window(clock, rule['quiet_start'], rule['quiet_end'], False):
                continue
            limit = int(rule.get('daily_limit', 2))
            if not 0 <= limit <= 20:
                raise ValidationError('每日频率上限须为 0–20')
            if kind in ('日程提醒', 'schedule'):
                scheduled_time = rule.get('schedule_time')
                if not scheduled_time or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', scheduled_time):
                    raise ValidationError('日程提醒需要明确 schedule_time（HH:MM）')
                if not rule.get('message'):
                    raise ValidationError('日程提醒需要 message 播报内容')
                if clock < scheduled_time:
                    continue
            for device in devices:
                identifier = device.get('device_id') or device['id']
                if rule.get('group') and rule['group'] != device.get('group'):
                    continue
                if rule.get('device_id') and rule['device_id'] not in (identifier, device['id']):
                    continue
                if rule['id'] in device.get('reminder_unsubscribed_ids', []):
                    continue
                anomaly = device_anomaly(device) if kind in ('设备异常', 'device_anomaly') else None
                if kind in ('设备异常', 'device_anomaly') and not anomaly:
                    continue
                # One occurrence per rule/device/day; never repeatedly replay missed reminders.
                dedup = 'reminder:%s:%s:%s' % (rule['id'], identifier, day)
                message = rule.get('message') or anomaly
                enqueue(device, {'type': 'reminder', 'message': str(message)[:2000], 'reminder_id': rule['id']}, dedup, rule['id'], limit)
        except (ValidationError, ValueError, TypeError) as exc:
            result['skipped'].append({'rule_id': rule['id'], 'reason': str(exc)})
    return result


def main():
    parser = argparse.ArgumentParser(description='小智外部调度单次执行器；仅排队，设备回执后才算执行')
    parser.add_argument('--data-dir', default=str(Path(__file__).resolve().parents[1] / 'data' / 'console'))
    parser.add_argument('--ota-check', action='store_true')
    parser.add_argument('--ota-interval-minutes', type=int, default=1440)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    result = run_once(Store(args.data_dir), ota_check=args.ota_check,
                      ota_interval_minutes=args.ota_interval_minutes, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
