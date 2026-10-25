"""Runs over SSH stdin. Only the proxy_url account field may be changed."""
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request


class SafeError(Exception):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def proxy_hash(value):
    return hashlib.sha256((value or '').encode()).hexdigest()


def endpoint(value):
    if not value:
        return '继承全局代理'
    if value == 'direct':
        return '直连'
    try:
        u = urllib.parse.urlsplit(value)
        return f'{u.scheme}://{u.hostname}:{u.port}'
    except (ValueError, TypeError):
        return '已有代理（格式无法显示）'


def validate_proxy(value, restore=False):
    if restore and value in ('', 'direct'):
        return
    try:
        u = urllib.parse.urlsplit(value)
        valid = (u.scheme in ('http', 'https', 'socks5', 'socks5h') and u.hostname
                 and u.port and 1 <= u.port <= 65535 and not u.query and not u.fragment
                 and u.path in ('', '/') and not any(ord(c) < 32 for c in value))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise SafeError('代理格式不正确，未修改。')


class Server:
    def __init__(self):
        self.root = Path('/opt/cpa')
        self.token = (self.root / 'management-key.txt').read_text().strip()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(self, path, data=None, method='GET', timeout=12):
        req = urllib.request.Request('http://127.0.0.1:8317/v0/management' + path,
            data=json.dumps(data).encode() if data is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        with self.opener.open(req, timeout=timeout) as resp:
            return json.load(resp)

    def snapshot(self):
        c = json.loads(subprocess.check_output(['docker', 'inspect', 'cli-proxy-api']))[0]
        cfg = self.api('/config')
        authdir = cfg.get('auth-dir', '/root/.cli-proxy-api')
        hostdir = None
        for mount in sorted(c['Mounts'], key=lambda m: len(m['Destination']), reverse=True):
            dest = mount['Destination'].rstrip('/')
            if authdir == dest or authdir.startswith(dest + '/'):
                hostdir = Path(mount['Source']) / authdir[len(dest):].lstrip('/')
                break
        if hostdir is None:
            raise SafeError('无法定位 CPA 账号目录，未修改。')
        accounts = []
        for a in self.api('/auth-files').get('files', []):
            if str(a.get('provider') or a.get('type') or '').lower() != 'claude':
                continue
            name = a['name']
            if Path(name).name != name:
                raise SafeError('账号文件名不符合预期，未修改。')
            d = json.loads((hostdir / name).read_text())
            proxy = d.get('proxy_url') or ''
            accounts.append({'email': a.get('email') or d.get('email') or '', 'name': name,
                'auth_index': a['auth_index'], 'disabled': bool(a['disabled']),
                'proxy_url': proxy, 'proxy_present': 'proxy_url' in d,
                'proxy_hash': proxy_hash(proxy), 'endpoint': endpoint(proxy),
                'other_hash': digest({k:v for k,v in d.items() if k != 'proxy_url'})})
        status = self.api('/plugins/account-concurrency/status')
        runtime = {'config_hash': hashlib.sha256((self.root/'config.yaml').read_bytes()).hexdigest(),
                   'container_id': c['Id'], 'started_at': c['State']['StartedAt'],
                   'max_per_key': status.get('max_per_key'),
                   'max_per_account': status.get('max_per_account')}
        return {'accounts': accounts, 'runtime': runtime,
                'active_requests': status.get('active_requests')}


def find_account(state, email):
    found = [a for a in state['accounts'] if a['email'].casefold() == email.casefold()]
    if not found:
        raise SafeError('未找到此邮箱的 Claude 账号；请先在 CPA 中导入 OAuth 账号。')
    if len(found) != 1:
        raise SafeError('同一邮箱匹配到多个账号，无法自动确定，请先处理重复账号。')
    return found[0]


def public_account(a):
    return {k:v for k,v in a.items() if k != 'proxy_url'}


def execute(payload, server=None):
    server = server or Server()
    action = payload['action']
    before = server.snapshot()
    if action == 'preview':
        rows = []
        for email in payload['emails']:
            try:
                rows.append({'ok': True, 'account': find_account(before, email)})
            except SafeError as exc:
                rows.append({'ok': False, 'email': email, 'error': str(exc)})
        return {'ok': all(r['ok'] for r in rows), 'rows': rows, 'runtime': before['runtime'],
                'active_requests': before.get('active_requests'),
                'inventory': [public_account(a) for a in before['accounts']]}
    a = find_account(before, payload['email'])
    if action == 'egress':
        if a['proxy_hash'] != payload['expected_proxy_hash']:
            raise SafeError('账号代理已变化，未发送出口查询。')
        result = server.api('/api-call', {'auth_index': a['auth_index'], 'method': 'GET',
            'url': 'https://api.ipify.org?format=json', 'header': {'Accept': 'application/json'}},
            'POST', timeout=65)
        if result.get('status_code') != 200:
            raise SafeError('出口查询失败，未重试；绑定保持，可选择回退。')
        try:
            ip = str(ipaddress.ip_address(json.loads(result['body'])['ip']))
        except (ValueError, KeyError, TypeError):
            raise SafeError('出口查询未返回有效 IP，未重试。') from None
        return {'ok': True, 'ip': ip, 'http_status': 200, 'attempts': 1}
    if action != 'set_proxy':
        raise SafeError('未知操作，未修改。')
    value = payload['new_proxy']
    validate_proxy(value, payload.get('restore', False))
    if (a['name'] != payload['name'] or a['auth_index'] != payload['auth_index']
            or a['disabled'] != payload['expected_disabled']):
        raise SafeError('账号身份或启用状态在预览后已变化，请重新预览。')
    if before['runtime'] != payload['runtime']:
        raise SafeError('服务或全局配置在预览后已变化，请重新预览。')
    if a['proxy_hash'] != payload['expected_proxy_hash']:
        raise SafeError('代理在预览后已被更改，本次没有覆盖。')
    if a['proxy_hash'] == proxy_hash(value):
        return {'ok': True, 'changed': False, 'account': public_account(a)}
    # Only this field is sent. Never upload an entire OAuth document.
    result = server.api('/auth-files/fields', {'name': a['name'], 'proxy_url': value}, 'PATCH')
    if result.get('status') != 'ok':
        raise SafeError('管理接口未确认成功，结果待核对；不自动重试。')
    after = server.snapshot()
    updated = find_account(after, payload['email'])
    checks = {'saved': updated['proxy_hash'] == proxy_hash(value),
              'enabled_state_preserved': updated['disabled'] == a['disabled'],
              'other_account_fields_preserved': updated['other_hash'] == a['other_hash'],
              'runtime_unchanged': after['runtime'] == before['runtime']}
    for old in before['accounts']:
        if old['name'] == a['name']:
            continue
        current = [r for r in after['accounts'] if r['name'] == old['name']]
        checks['non_target_settings_preserved'] = checks.get('non_target_settings_preserved', True) and bool(current) and all(
            current[0][k] == old[k] for k in ('disabled', 'proxy_hash'))
    return {'ok': all(checks.values()), 'changed': True, 'checks': checks,
            'account': public_account(updated),
            'error': '' if all(checks.values()) else '写入后复核发现差异，已停止；请查看记录，不自动重试。'}


def safe_execute(payload, server=None):
    try:
        return execute(payload, server)
    except SafeError as exc:
        return {'ok': False, 'error': str(exc)}
    except Exception as exc:
        # Do not return exception text, URLs, raw responses or traceback locals.
        return {'ok': False, 'error': '连接或接口操作失败，结果待核对；未自动重试。',
                'error_type': type(exc).__name__, 'http_status': getattr(exc, 'code', None)}


if __name__ == '__main__':
    print(json.dumps(safe_execute(PAYLOAD), ensure_ascii=False))
