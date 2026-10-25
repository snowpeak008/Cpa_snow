"""Local input parsing, SSH transport and encrypted rollback journal."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / 'runs'
SSH_HOST = 'root@104.160.39.169'
SSH_KEY = Path.home() / '.ssh' / 'bandwagon_codex'


class InputError(ValueError):
    pass


def proxy_hash(value):
    return hashlib.sha256((value or '').encode()).hexdigest()


def email_valid(email):
    return bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", email))


def normalize_proxy(raw, username='', password='', scheme='http', port='12323'):
    raw = raw.strip()
    if not raw or any(ord(c) < 32 for c in raw):
        raise InputError('请填写代理地址。')
    if '://' in raw:
        try:
            u = urlsplit(raw)
            host, parsed_port = u.hostname, u.port
        except ValueError:
            raise InputError('代理 URL 或端口格式不正确。') from None
        if u.query or u.fragment or u.path not in ('', '/'):
            raise InputError('代理 URL 不应包含路径、查询参数或片段。')
        scheme, port = u.scheme.lower(), str(parsed_port or port)
        if u.username is not None:
            username, password = unquote(u.username), unquote(u.password or '')
    else:
        parts = raw.split(':', 3)
        if len(parts) == 4:
            host, port, username, password = parts
        elif len(parts) == 2:
            host, port = parts
        elif len(parts) == 1:
            host = raw
        else:
            raise InputError('格式应为 IP:端口:用户名:密码，或 IP:端口。IPv6 请使用完整代理 URL。')
    if scheme not in ('http', 'https', 'socks5', 'socks5h'):
        raise InputError('仅支持 HTTP、HTTPS、SOCKS5、SOCKS5H 代理。')
    host = (host or '').strip()
    try:
        ip = ipaddress.ip_address(host)
        host = str(ip)
    except ValueError:
        if not host or len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', s) for s in host.split('.')):
            raise InputError('IP 或代理主机名格式不正确。') from None
        if re.fullmatch(r'[\d.]+', host):
            raise InputError('IPv4 地址格式不正确。') from None
    try:
        port_num = int(port)
        if not 1 <= port_num <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise InputError('端口必须是 1–65535 的整数。') from None
    if password and not username:
        raise InputError('填写代理密码时，也需要填写代理用户名。')
    if any(ord(c) < 32 for c in username + password):
        raise InputError('代理用户名或密码不能包含换行或控制字符。')
    credentials = quote(username, safe='') + ':' + quote(password, safe='') + '@' if username else ''
    authority = '[' + host + ']' if ':' in host else host.lower()
    return f'{scheme}://{credentials}{authority}:{port_num}'


def display_proxy(value):
    u = urlsplit(value)
    return f'{u.scheme}://{u.hostname}:{u.port}'


@dataclass(frozen=True)
class Binding:
    email: str
    proxy_url: str = field(repr=False)

    @property
    def endpoint(self):
        return display_proxy(self.proxy_url)


def parse_entries(text, **defaults):
    lines = [(i, s.strip()) for i, s in enumerate(text.splitlines(), 1) if s.strip() and not s.lstrip().startswith('#')]
    result, pending = [], None
    for number, line in lines:
        if pending:
            if email_valid(line):
                raise InputError(f'第 {pending[0]} 行邮箱后缺少代理地址。')
            email, raw = pending[1], line
            pending = None
        elif email_valid(line):
            pending = (number, line)
            continue
        else:
            pair = re.split(r'[\s,]+', line, maxsplit=1)
            if len(pair) != 2 or not email_valid(pair[0]):
                raise InputError(f'第 {number} 行应为邮箱，或“邮箱 代理地址”。')
            email, raw = pair
        try:
            result.append(Binding(email, normalize_proxy(raw, **defaults)))
        except InputError as exc:
            raise InputError(f'第 {number} 行：{exc}') from None
    if pending:
        raise InputError(f'第 {pending[0]} 行邮箱后缺少代理地址。')
    if not result:
        raise InputError('请先填写或粘贴账号与代理信息。')
    emails = [b.email.casefold() for b in result]
    if len(emails) != len(set(emails)):
        raise InputError('同一个邮箱出现多次，请保留一条绑定关系。')
    if len(result) > 100:
        raise InputError('每批最多 100 个账号，请分批导入。')
    return result


class SSHRemote:
    def call(self, payload):
        if not SSH_KEY.is_file():
            return {'ok': False, 'error': '未找到现有 SSH 密钥，请确认在原电脑和 Windows 用户下运行。'}
        source = (ROOT / 'remote_agent.py').read_text(encoding='utf-8')
        script = 'PAYLOAD=' + repr(payload) + '\n' + source
        args = [str(Path(os.environ.get('WINDIR', r'C:\Windows'))/'System32/OpenSSH/ssh.exe'),
                '-i', str(SSH_KEY), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
                SSH_HOST, 'python3 -']
        try:
            p = subprocess.run(args, input=script.encode(), capture_output=True, timeout=95,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if p.returncode:
                return {'ok': False, 'error': 'SSH 执行失败；检查服务器连接和 SSH 密钥。未自动重试。'}
            return json.loads(p.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {'ok': False, 'error': '连接超时或返回无法解析，操作结果待核对；未自动重试。'}


class DPAPIVault:
    """Windows current-user authenticated encryption; plaintext never hits disk."""
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    def transform(self, data, decrypt=False):
        if os.name != 'nt':
            raise InputError('加密备份需要 Windows，请在原电脑运行。')
        buf = ctypes.create_string_buffer(data)
        src = self.Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        dst = self.Blob()
        api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
        if not api(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
            raise InputError('无法加密或解密回退记录；请使用原 Windows 用户。')
        try:
            return ctypes.string_at(dst.data, dst.size)
        finally:
            ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            ctypes.windll.kernel32.LocalFree(ctypes.cast(dst.data, ctypes.c_void_p))

    def seal(self, data):
        return self.transform(json.dumps(data, ensure_ascii=False).encode())

    def open(self, data):
        return json.loads(self.transform(data, decrypt=True))


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def public_plan(bindings):
    return [{'email': b.email, 'endpoint': b.endpoint, 'proxy_hash': proxy_hash(b.proxy_url)} for b in bindings]


class Controller:
    def __init__(self, remote=None, vault=None, runs=RUNS):
        self.remote = remote or SSHRemote()
        self.vault = vault or DPAPIVault()
        self.runs = Path(runs)

    def preview(self, bindings):
        return self.remote.call({'action': 'preview', 'emails': [b.email for b in bindings]})

    def apply(self, bindings, preview, egress=False, notify=lambda _:None):
        if not preview.get('ok') or len(preview['rows']) != len(bindings):
            raise InputError('请先完成有效的账号预览。')
        backup = {'runtime': preview['runtime'], 'accounts': [], 'server': SSH_HOST}
        for binding, row in zip(bindings, preview['rows']):
            a = row['account']
            if a['email'].casefold() != binding.email.casefold():
                raise InputError('预览与输入不一致，请重新预览。')
            backup['accounts'].append({**a, 'new_proxy_hash': proxy_hash(binding.proxy_url)})
        run = self.runs / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        run.mkdir(parents=True, exist_ok=False)
        sealed = self.vault.seal(backup)
        with (run/'before.dpapi').open('xb') as f:
            f.write(sealed)
            f.flush()
            os.fsync(f.fileno())
        report = {'created': datetime.now().isoformat(timespec='seconds'), 'server': SSH_HOST,
                  'plan': public_plan(bindings), 'results': [], 'complete': False,
                  'model_requests': 0, 'quota_refreshes': 0, 'egress_requested': egress}
        atomic_json(run/'report.json', report)
        for b, old in zip(bindings, backup['accounts']):
            row = {'email': b.email, 'endpoint': b.endpoint, 'status': 'attempted', 'disabled_before': old['disabled']}
            report['results'].append(row)
            atomic_json(run/'report.json', report)  # Persist BEFORE touching production.
            notify(f'正在绑定：{b.email}')
            result = self.remote.call({'action': 'set_proxy', 'email': b.email, 'name': old['name'],
                'auth_index': old['auth_index'], 'expected_disabled': old['disabled'],
                'expected_proxy_hash': old['proxy_hash'], 'runtime': preview['runtime'], 'new_proxy': b.proxy_url})
            row['result'] = result
            row['status'] = 'bound' if result.get('ok') else 'needs_review'
            atomic_json(run/'report.json', report)
            if not result.get('ok'):
                notify('已停止：' + result.get('error', '结果待核对；不自动重试。'))
                break
            notify('已绑定：' + b.email + ('（原代理相同，无需改写）' if not result.get('changed') else ''))
            if egress:
                row['egress'] = {'attempted': True}
                atomic_json(run/'report.json', report)
                result = self.remote.call({'action': 'egress', 'email': b.email, 'expected_proxy_hash': proxy_hash(b.proxy_url)})
                row['egress'] = result
                atomic_json(run/'report.json', report)
                if not result.get('ok'):
                    notify('出口查询失败，已停止后续账号；已写入的绑定仍保留，可回退。')
                    break
                notify('出口 IP：' + result['ip'])
        else:
            report['complete'] = True
        atomic_json(run/'report.json', report)
        return run, report

    def restore(self, run, notify=lambda _:None):
        run = Path(run).resolve()
        if not run.is_relative_to(self.runs.resolve()):
            raise InputError('只能回退本工具 runs 目录中的记录。')
        backup = self.vault.open((run/'before.dpapi').read_bytes())
        report = json.loads((run/'report.json').read_text(encoding='utf-8'))
        if backup.get('server') != SSH_HOST:
            raise InputError('备份服务器不匹配。')
        attempted = {r['email'].casefold() for r in report['results']}
        rows = [a for a in backup['accounts'] if a['email'].casefold() in attempted]
        log = {'complete': False, 'results': []}
        path = run/('rollback-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6] + '.json')
        atomic_json(path, log)
        for old in reversed(rows):
            notify('正在核对回退：' + old['email'])
            current = self.remote.call({'action':'preview', 'emails':[old['email']]})
            if not current.get('ok'):
                log['results'].append({'email':old['email'], 'ok':False, 'error':'无法读取当前状态，未继续回退。'})
                break
            a = current['rows'][0]['account']
            if a['proxy_hash'] == old['proxy_hash']:
                log['results'].append({'email':old['email'], 'ok':True, 'already_restored':True})
                atomic_json(path, log)
                continue
            if (a['proxy_hash'] != old['new_proxy_hash'] or a['name'] != old['name']
                    or a['auth_index'] != old['auth_index']):
                log['results'].append({'email':old['email'], 'ok':False, 'error':'代理或账号身份后来已变化，拒绝覆盖。'})
                break
            result = self.remote.call({'action':'set_proxy', 'email':old['email'], 'name':old['name'],
                'auth_index':old['auth_index'], 'expected_disabled':a['disabled'],
                'expected_proxy_hash':old['new_proxy_hash'], 'runtime':current['runtime'],
                'new_proxy':old['proxy_url'], 'restore':True})
            log['results'].append({'email':old['email'], **result})
            atomic_json(path, log)
            if not result.get('ok'):
                break
        else:
            log['complete'] = True
        atomic_json(path, log)
        return log
