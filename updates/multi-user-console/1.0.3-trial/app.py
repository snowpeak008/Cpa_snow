"""Isolated Snow Console control-plane candidate. No production writes or model calls."""
import argparse
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Error(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def require(condition, code='invalid_input', status=400):
    if not condition:
        raise Error(status, code)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    require(isinstance(password, str) and 8 <= len(password) <= 256, 'password_8_to_256_chars')
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()


def password_matches(password, saved):
    if not isinstance(password, str) or not 8 <= len(password) <= 256:
        return False
    return hmac.compare_digest(password_hash(password, saved.split(':')[0]), saved)


def clean_name(value):
    require(isinstance(value, str) and 1 <= len(value.strip()) <= 80)
    require(not any(ord(c) < 32 for c in value))
    return value.strip()


def canonical_host(value):
    host = value.lower().rstrip('.')
    try:
        ip = ipaddress.ip_address(host)
        return str(ip.ipv4_mapped or ip) if isinstance(ip, ipaddress.IPv6Address) else str(ip)
    except ValueError:
        try:
            return host.encode('idna').decode('ascii')
        except UnicodeError:
            raise Error(400, 'invalid_url')


def api_url(value, forbidden_hosts=()):
    require(isinstance(value, str) and len(value) <= 2048)
    require(not re.search(r'[\s\\]', value), 'invalid_url')
    try:
        u = urlsplit(value)
        require(u.scheme == 'https' and u.hostname and not u.username and not u.password
                and not u.query and not u.fragment and u.port != 0, 'https_base_url_required')
    except ValueError:
        raise Error(400, 'invalid_url')
    require(not re.search(r'/(messages|chat/completions|responses)/?$', u.path), 'use_api_base_url')
    host = canonical_host(u.hostname)
    require(host not in forbidden_hosts, 'self_upstream_forbidden')
    require(host != 'localhost' and not host.endswith(('.localhost', '.local', '.internal')),
            'nonpublic_upstream_forbidden')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        require('.' in host, 'nonpublic_upstream_forbidden')
    else:
        require(ip.is_global, 'nonpublic_upstream_forbidden')
    return value.rstrip('/')


def resolved_targets(value, forbidden_hosts, resolver):
    """Connection-time validator for future bridge; caller must pin IPs and forbid redirects.

    Not used to claim live protection: this candidate makes no outbound API calls.
    Resolver is injected so tests never perform external DNS requests.
    """
    u = urlsplit(api_url(value, forbidden_hosts))
    results = resolver(u.hostname, u.port or 443)
    ips = {canonical_host(r) for r in results}
    require(bool(ips), 'upstream_dns_unavailable')
    for ip in ips:
        require(ipaddress.ip_address(ip).is_global and ip not in forbidden_hosts,
                'unsafe_upstream_destination')
    return sorted(ips)


DEFAULT_LIMITS = {'max_keys': 3, 'max_accounts': 10, 'max_upstreams': 5, 'max_concurrency': 5}


class Store:
    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            self.root.chmod(0o700)
        self.lock = threading.RLock()
        policy = json.loads(pathlib.Path(__file__).with_name('upstream-policy.json').read_text(encoding='utf-8'))
        require(isinstance(policy.get('cpa_origins'), list) and policy['cpa_origins'], 'upstream_policy_required', 503)
        self.forbidden_hosts = frozenset(canonical_host(urlsplit(v).hostname) for v in policy['cpa_origins'])
        self.db = sqlite3.connect(self.root / 'console.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA foreign_keys=ON;
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            role TEXT NOT NULL, enabled INTEGER NOT NULL, limits TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS resources (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
            name TEXT NOT NULL, provider TEXT NOT NULL, payload TEXT NOT NULL, creator TEXT NOT NULL,
            fingerprint TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL, revision INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS client_keys (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
            value TEXT NOT NULL, enabled INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS audit (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT NOT NULL,
            action TEXT NOT NULL, target TEXT NOT NULL);
        ''')
        self.db.commit()
        # Additive migration keeps the existing local demo/development inventory.
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(resources)')}
        for name, default in (('weight', 1), ('admin_disabled', 0)):
            if name not in columns:
                self.db.execute('ALTER TABLE resources ADD COLUMN ' + name + ' INTEGER NOT NULL DEFAULT ' + str(default))
        self.db.commit()
        if os.name != 'nt':
            (self.root / 'console.sqlite3').chmod(0o600)
        # Make nonexistent-user verification take the same KDF path.
        self.dummy_hash = password_hash(secrets.token_urlsafe(24))

    @contextlib.contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    def audit(self, db, actor, action, target):
        db.execute('INSERT INTO audit(at,actor,action,target) VALUES(?,?,?,?)',
                   (time.time(), actor, action, target))

    def create_user(self, actor, username, password):
        require(isinstance(username, str) and re.fullmatch('[a-zA-Z0-9_.-]{3,40}', username), 'invalid_username')
        hashed = password_hash(password)
        with self.transaction() as db:
            count = db.execute('SELECT count(*) FROM users').fetchone()[0]
            if count:
                require(actor and self.user(db, actor)['role'] == 'admin', 'forbidden', 403)
            else:
                require(actor is None, 'bootstrap_only', 403)
            uid = uuid.uuid4().hex
            try:
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',
                           (uid, username.lower(), hashed, 'admin' if count == 0 else 'user', 1, json.dumps(DEFAULT_LIMITS)))
            except sqlite3.IntegrityError:
                raise Error(409, 'username_unavailable')
            self.audit(db, actor or uid, 'user.create', uid)
            return uid

    def user(self, db, uid):
        row = db.execute('SELECT * FROM users WHERE id=? AND enabled=1', (uid,)).fetchone()
        require(row is not None, 'unauthorized', 401)
        return row

    def login(self, username, password):
        require(isinstance(username, str), 'invalid_credentials', 401)
        with self.transaction() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username.lower(),)).fetchone()
            good = password_matches(password, row['password'] if row else self.dummy_hash)
            require(good and row is not None and row['enabled'], 'invalid_credentials', 401)
            now = time.time()
            db.execute('DELETE FROM sessions WHERE expires<?', (now,))
            require(db.execute('SELECT count(*) FROM sessions').fetchone()[0] < 4096, 'session_limit', 503)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), row['id'], csrf, now + 28800))
            self.audit(db, row['id'], 'session.login', row['id'])
            return token, csrf

    def session(self, token):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (digest(token), time.time())).fetchone()
            require(row is not None, 'unauthorized', 401)
            return dict(self.user(db, row['user_id'])), row['csrf']

    def view(self, uid):
        with self.transaction() as db:
            user = self.user(db, uid)
            admin = user['role'] == 'admin'
            where, args = ('', ()) if admin else (' WHERE owner=?', (uid,))
            resources = []
            for r in db.execute('SELECT * FROM resources' + where, args):
                data = json.loads(r['payload'])
                editable = admin or r['kind'] == 'upstream' and r['creator'] == uid and r['owner'] == uid
                controllable = admin or r['owner'] == uid and r['kind'] == 'account' and not r['admin_disabled'] or editable
                resources.append({k: r[k] for k in ('id', 'owner', 'kind', 'name', 'provider', 'enabled', 'revision', 'weight', 'admin_disabled')} |
                                 {'base_url': data.get('base_url'), 'models': data.get('models'), 'state': 'staged',
                                  'writable': editable, 'controllable': bool(controllable)})
            keys = [dict(r) | {'state': 'staged'} for r in db.execute(
                "SELECT id,owner,name,enabled,substr(value,1,8)||'…'||substr(value,-4) AS masked FROM client_keys" + where, args)]
            users = []
            if admin:
                users = [dict(r) for r in db.execute('SELECT id,username,role,enabled,limits FROM users')]
                for r in users:
                    r['limits'] = json.loads(r['limits'])
            return {'me': {k: user[k] for k in ('id', 'username', 'role')}, 'limits': json.loads(user['limits']),
                    'users': users, 'resources': resources, 'keys': keys, 'mode': 'offline_candidate',
                    'runtime_connected': False, 'registration': 'disabled'}

    def target_owner(self, db, actor, body):
        user = self.user(db, actor)
        target = body.get('owner', actor)
        require(target == actor or user['role'] == 'admin', 'forbidden', 403)
        self.user(db, target)
        return target

    def resource_payload(self, body):
        kind, provider = body.get('kind'), body.get('provider')
        if kind == 'account':
            data = body.get('credential')
            require(isinstance(data, dict), 'credential_json_required')
            require(provider in ('claude', 'codex') and data.get('type') == provider, 'unsupported_account_type')
            allowed = {'type', 'email', 'access_token', 'refresh_token', 'id_token', 'account_id', 'expired', 'last_refresh'}
            require(not set(data) - allowed, 'unsupported_credential_fields')
            require(all(isinstance(v, str) and len(v) <= 32768 for v in data.values()), 'invalid_credential')
            require(bool(data.get('access_token')) and bool(data.get('refresh_token')), 'tokens_required')
            # Credentials are stored locally for a future explicit CPA migration, never sent upstream here.
            return data, digest(provider + '\0' + data['refresh_token'])
        require(kind == 'upstream' and provider in ('gpt', 'claude', 'grok'), 'unsupported_provider')
        key = body.get('key')
        require(isinstance(key, str) and 1 <= len(key) <= 8192 and not any(c.isspace() for c in key), 'invalid_upstream_key')
        base = api_url(body.get('base_url'), self.forbidden_hosts)
        models = body.get('models')
        require(isinstance(models, list) and 1 <= len(models) <= 100, 'models_required')
        require(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,150}', v) for v in models), 'invalid_models')
        require(len(set(models)) == len(models), 'duplicate_models')
        return {'key': key, 'base_url': base, 'models': models}, digest(provider + '\0' + base + '\0' + key)

    def mutate(self, actor, action, body):
        require(isinstance(body, dict))
        with self.transaction() as db:
            me = self.user(db, actor)
            if action == 'logout':
                db.execute('DELETE FROM sessions WHERE token=?', (digest(body['_token']),))
                return {'ok': True}
            if action == 'password':
                require(password_matches(body.get('current'), me['password']), 'invalid_credentials', 403)
                hashed = password_hash(body.get('password'))
                db.execute('UPDATE users SET password=? WHERE id=?', (hashed, actor))
                db.execute('DELETE FROM sessions WHERE user_id=?', (actor,))
                self.audit(db, actor, 'password.change', actor)
                return {'ok': True, 'login_required': True}
            if action == 'users/reset-password':
                require(me['role'] == 'admin', 'forbidden', 403)
                target = db.execute('SELECT * FROM users WHERE id=?', (body.get('id'),)).fetchone()
                require(target is not None, 'not_found', 404)
                require(target['role'] != 'admin', 'admin_policy_immutable', 403)
                hashed = password_hash(body.get('password'))
                db.execute('UPDATE users SET password=? WHERE id=?', (hashed, target['id']))
                db.execute('DELETE FROM sessions WHERE user_id=?', (target['id'],))
                self.audit(db, actor, 'user.password_reset', target['id'])
                return {'ok': True}
            if action == 'users/update':
                require(me['role'] == 'admin', 'forbidden', 403)
                target = body.get('id')
                row = db.execute('SELECT * FROM users WHERE id=?', (target,)).fetchone()
                require(row is not None, 'not_found', 404)
                require(row['role'] != 'admin', 'admin_policy_immutable', 403)
                require(type(body.get('enabled')) is bool)
                limits = body.get('limits')
                require(isinstance(limits, dict) and set(limits) == set(DEFAULT_LIMITS), 'invalid_limits')
                require(all(type(v) is int and 0 <= v <= (100 if k == 'max_concurrency' else 1000)
                            for k, v in limits.items()), 'invalid_limits')
                db.execute('UPDATE users SET enabled=?,limits=? WHERE id=?', (int(body['enabled']), json.dumps(limits), target))
                db.execute('DELETE FROM sessions WHERE user_id=?', (target,))
                self.audit(db, actor, 'user.update', target)
                return {'ok': True}
            if action == 'keys/create':
                owner = self.target_owner(db, actor, body)
                limit = json.loads(self.user(db, owner)['limits'])['max_keys']
                count = db.execute('SELECT count(*) FROM client_keys WHERE owner=? AND enabled=1', (owner,)).fetchone()[0]
                require(count < limit, 'key_limit', 409)
                key, kid = 'snow-' + secrets.token_urlsafe(36), uuid.uuid4().hex
                db.execute('INSERT INTO client_keys VALUES(?,?,?,?,1)', (kid, owner, clean_name(body.get('name')), key))
                self.audit(db, actor, 'key.create', kid)
                return {'id': kid, 'key': key, 'state': 'staged', 'usable_in_cpa': False}
            if action in ('keys/revoke', 'resources/delete', 'resources/toggle', 'resources/assign', 'resources/update', 'resources/weight'):
                table = 'client_keys' if action.startswith('keys/') else 'resources'
                row = db.execute('SELECT * FROM ' + table + ' WHERE id=?', (body.get('id'),)).fetchone()
                require(row is not None and (row['owner'] == actor or me['role'] == 'admin'), 'not_found', 404)
                if table == 'resources':
                    if row['kind'] == 'account':
                        require(me['role'] == 'admin' or action in ('resources/toggle', 'resources/weight'), 'account_admin_only', 403)
                        require(me['role'] == 'admin' or not row['admin_disabled'], 'account_admin_disabled', 403)
                    else:
                        require(me['role'] == 'admin' or row['creator'] == actor, 'assigned_resource_readonly', 403)
                if action == 'resources/assign':
                    require(me['role'] == 'admin', 'forbidden', 403)
                    owner = self.target_owner(db, actor, body)
                    require(owner != row['owner'], 'already_assigned')
                    self.resource_room(db, owner, row['kind'])
                    db.execute('UPDATE resources SET owner=?,revision=revision+1 WHERE id=?', (owner, row['id']))
                elif action == 'keys/revoke':
                    db.execute('UPDATE client_keys SET enabled=0 WHERE id=?', (row['id'],))
                elif action == 'resources/delete':
                    require(body.get('revision') == row['revision'], 'stale_revision', 409)
                    db.execute('DELETE FROM resources WHERE id=?', (row['id'],))
                elif action == 'resources/weight':
                    require(row['kind'] == 'account', 'account_required')
                    require(type(body.get('weight')) is int and 1 <= body['weight'] <= 10, 'weight_1_to_10')
                    require(body.get('revision') == row['revision'], 'stale_revision', 409)
                    db.execute('UPDATE resources SET weight=?,revision=revision+1 WHERE id=?', (body['weight'], row['id']))
                elif action == 'resources/update':
                    require(body.get('revision') == row['revision'], 'stale_revision', 409)
                    require(body.get('kind') == row['kind'] and body.get('provider') == row['provider'], 'identity_immutable')
                    replacement = dict(body)
                    if row['kind'] == 'upstream' and body.get('key') == '':
                        replacement['key'] = json.loads(row['payload'])['key']
                    payload, fp = self.resource_payload(replacement)
                    try:
                        db.execute('UPDATE resources SET name=?,payload=?,fingerprint=?,revision=revision+1 WHERE id=?',
                                   (clean_name(body.get('name')), json.dumps(payload), fp, row['id']))
                    except sqlite3.IntegrityError:
                        raise Error(409, 'credential_unavailable')
                else:
                    require(type(body.get('enabled')) is bool)
                    require(body.get('revision') == row['revision'], 'stale_revision', 409)
                    db.execute('UPDATE resources SET enabled=?,revision=revision+1 WHERE id=?', (body['enabled'], row['id']))
                    if me['role'] == 'admin' and row['kind'] == 'account':
                        db.execute('UPDATE resources SET admin_disabled=? WHERE id=?', (not body['enabled'], row['id']))
                self.audit(db, actor, action, row['id'])
                return {'ok': True}
            if action == 'resources/create':
                require(body.get('kind') != 'account' or me['role'] == 'admin', 'account_admin_only', 403)
                owner = self.target_owner(db, actor, body)
                payload, fp = self.resource_payload(body)
                self.resource_room(db, owner, body['kind'])
                rid = uuid.uuid4().hex
                try:
                    db.execute('INSERT INTO resources(id,owner,kind,name,provider,payload,creator,fingerprint,enabled,revision) VALUES(?,?,?,?,?,?,?,?,?,1)',
                               (rid, owner, body['kind'], clean_name(body.get('name')), body['provider'], json.dumps(payload), actor, fp, 1))
                except sqlite3.IntegrityError:
                    raise Error(409, 'credential_unavailable')
                self.audit(db, actor, 'resource.create', rid)
                return {'id': rid, 'state': 'staged'}
            raise Error(404, 'not_found')

    def resource_room(self, db, owner, kind):
        field = 'max_accounts' if kind == 'account' else 'max_upstreams'
        limit = json.loads(self.user(db, owner)['limits'])[field]
        count = db.execute('SELECT count(*) FROM resources WHERE owner=? AND kind=?', (owner, kind)).fetchone()[0]
        require(count < limit, 'resource_limit', 409)

    def plan(self, actor):
        """Secret-free migration inventory. Not a production config or apply operation."""
        with self.transaction() as db:
            require(self.user(db, actor)['role'] == 'admin', 'forbidden', 403)
            users = []
            for u in db.execute('SELECT * FROM users ORDER BY id'):
                keys = [digest('cli-proxy-api:caller-scope:v1\0' + r['value']) for r in db.execute(
                    'SELECT value FROM client_keys WHERE owner=? AND enabled=1', (u['id'],))] if u['enabled'] else []
                resources = [dict(r) for r in db.execute('SELECT id,kind,provider FROM resources WHERE owner=? AND enabled=1', (u['id'],))] if u['enabled'] else []
                users.append({'user_id': u['id'], 'enabled': bool(u['enabled']), 'key_scopes': keys,
                              'resources': resources, 'limits': json.loads(u['limits'])})
            return {'schema': 1, 'mode': 'preview_only', 'users': users, 'can_apply': False,
                    'blockers': ['native_resource_identity_and_config_reconciliation',
                                 'tenant_aggregate_concurrency_and_dollar_budget_enforcement',
                                 'explicit_existing_key_and_account_ownership_migration']}

    def audit_view(self, actor):
        with self.transaction() as db:
            require(self.user(db, actor)['role'] == 'admin', 'forbidden', 403)
            return {'events': [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY seq DESC LIMIT 100')]}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store, public_origin=None):
        require(address[0] == '127.0.0.1', 'loopback_only')
        super().__init__(address, Handler)
        self.store, self.failures, self.guard = store, {}, threading.Lock()
        self.slots = threading.BoundedSemaphore(32)
        if public_origin:
            parsed = urlsplit(public_origin)
            require(parsed.scheme == 'http' and parsed.hostname == '127.0.0.1' and parsed.port
                    and not parsed.username and not parsed.path and not parsed.query and not parsed.fragment,
                    'loopback_origin_required')
        self.origin = public_origin or 'http://127.0.0.1:' + str(self.server_port)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self, *_):
        pass

    def reply(self, status, data, cookie=None, html=False):
        raw = (data if html else json.dumps(data, ensure_ascii=False)).encode()
        self.send_response(status)
        for k, v in {'Content-Type': 'text/html; charset=utf-8' if html else 'application/json; charset=utf-8',
                     'Content-Length': str(len(raw)), 'Cache-Control': 'no-store', 'Referrer-Policy': 'same-origin',
                     'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'"}.items():
            self.send_header(k, v)
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def identity(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except Exception:
            raise Error(401, 'unauthorized')
        token = cookies.get('snow_console')
        token = token.value if token else ''
        user, csrf = self.server.store.session(token)
        return user, csrf, token

    def check_host(self):
        require(self.headers.get('Host') == self.server.origin[7:], 'invalid_host', 403)

    def do_GET(self):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            if path in ('/', '/admin', '/user'):
                return self.reply(200, pathlib.Path(__file__).with_name('console.html').read_text(encoding='utf-8'), html=True)
            if path == '/health':
                return self.reply(200, {'service': 'snow-multiuser-candidate', 'runtime_connected': False})
            user, csrf, _ = self.identity()
            if path == '/api/state':
                return self.reply(200, self.server.store.view(user['id']) | {'csrf': csrf})
            if path == '/api/admin/plan':
                return self.reply(200, self.server.store.plan(user['id']))
            if path == '/api/admin/audit':
                return self.reply(200, self.server.store.audit_view(user['id']))
            raise Error(404, 'not_found')
        except Error as e:
            self.reply(e.status, {'error': e.code})
        except Exception:
            self.reply(500, {'error': 'internal_error'})

    def do_POST(self):
        try:
            self.check_host()
            require(self.headers.get('Origin') == self.server.origin, 'invalid_origin', 403)
            require(self.headers.get('Content-Type', '').split(';')[0] == 'application/json', 'json_required', 415)
            require(not self.headers.get('Transfer-Encoding'), 'unsupported_encoding')
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise Error(400, 'invalid_length')
            require(0 < size <= 262144, 'body_too_large', 413)
            self.connection.settimeout(10)
            try:
                body = json.loads(self.rfile.read(size))
            except (ValueError, UnicodeError):
                raise Error(400, 'invalid_json')
            require(isinstance(body, dict))
            action = urlsplit(self.path).path.removeprefix('/api/')
            if action == 'login':
                username = body.get('username', '')
                require(isinstance(username, str) and len(username) <= 40, 'invalid_credentials', 401)
                bucket = digest(username.lower())
                with self.server.guard:
                    now = time.time()
                    self.server.failures = {k: [t for t in v if now-t < 300] for k, v in self.server.failures.items() if any(now-t < 300 for t in v)}
                    require(len(self.server.failures.get(bucket, [])) < 10 and len(self.server.failures.get('*', [])) < 200, 'try_later', 429)
                    # Reserve attempts before KDF to bound simultaneous login storms.
                    self.server.failures.setdefault(bucket, []).append(now)
                    self.server.failures.setdefault('*', []).append(now)
                token, _ = self.server.store.login(username, body.get('password'))
                return self.reply(200, {'ok': True}, 'snow_console=' + token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
            user, csrf, token = self.identity()
            supplied = self.headers.get('X-CSRF-Token', '')
            require(supplied.isascii() and hmac.compare_digest(supplied, csrf), 'invalid_csrf', 403)
            if action == 'users/create':
                result = {'id': self.server.store.create_user(user['id'], body.get('username'), body.get('password'))}
            else:
                body['_token'] = token
                result = self.server.store.mutate(user['id'], action, body)
            clear = 'snow_console=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' if action in ('logout', 'password') else None
            return self.reply(200, result, clear)
        except Error as e:
            self.reply(e.status, {'error': e.code})
        except Exception:
            self.reply(500, {'error': 'internal_error'})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', default=str(pathlib.Path(__file__).with_name('private-data')))
    p.add_argument('--port', type=int, default=18741)
    p.add_argument('--bootstrap-admin')
    p.add_argument('--public-origin', help='Exact browser loopback origin when accessed through SSH forwarding')
    a = p.parse_args()
    store = Store(a.data)
    if a.bootstrap_admin:
        import getpass
        store.create_user(None, a.bootstrap_admin, getpass.getpass('New administrator password (8+ chars): '))
        print('Administrator created. No production service was changed.')
    else:
        print('Snow Console independent trial: ' + (a.public_origin or 'http://127.0.0.1:' + str(a.port)))
        Server(('127.0.0.1', a.port), store, a.public_origin).serve_forever()
