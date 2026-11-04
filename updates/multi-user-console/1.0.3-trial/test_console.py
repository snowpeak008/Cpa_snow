import concurrent.futures
import http.client
import json
import pathlib
import tempfile
import threading
import unittest
from app import Error, Server, Store, digest, resolved_targets


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).parent)
        self.s = Store(self.tmp.name)
        self.s.forbidden_hosts |= {'8.8.4.4'}  # Synthetic own-address fixture, no network.
        self.admin = self.s.create_user(None, 'administrator', 'admin-test-pass-123')
        self.a = self.s.create_user(self.admin, 'alice', 'alice-test-pass-123')
        self.b = self.s.create_user(self.admin, 'bob', 'bob-test-pass-12345')

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def fails(self, status, fn):
        with self.assertRaises(Error) as e:
            fn()
        self.assertEqual(e.exception.status, status)

    def key(self, owner=None):
        return self.s.mutate(owner or self.a, 'keys/create', {'name': 'my client key'})

    def resource(self, actor=None, key='fake-upstream-A', **extra):
        return self.s.mutate(actor or self.a, 'resources/create', {
            'kind': 'upstream', 'provider': 'claude', 'name': '<script>fake</script>',
            'key': key, 'base_url': 'https://example.invalid/v1', 'models': ['test-model'], **extra})

    def test_bootstrap_cannot_overwrite_admin(self):
        self.fails(403, lambda: self.s.create_user(None, 'another-admin', 'another-password-123'))
        self.fails(403, lambda: self.s.create_user(self.a, 'another-user', 'another-password-123'))

    def test_password_hash_and_wrong_login(self):
        saved = self.s.db.execute('SELECT password FROM users WHERE id=?', (self.a,)).fetchone()[0]
        self.assertNotIn('alice-test-pass', saved)
        self.fails(401, lambda: self.s.login('alice', 'wrong-password-123'))
        self.fails(401, lambda: self.s.login('nonexistent', 'wrong-password-123'))

    def test_own_view_hides_credentials_other_users_and_keys(self):
        k = self.key()
        r = self.resource()
        self.resource(self.b, key='fake-upstream-B')
        view = json.dumps(self.s.view(self.a))
        self.assertIn(r['id'], view)
        self.assertNotIn('fake-upstream-A', view)
        self.assertNotIn('fake-upstream-B', view)
        self.assertNotIn(k['key'], view)
        self.assertEqual(self.s.view(self.a)['users'], [])
        self.assertEqual(len(self.s.view(self.admin)['resources']), 2)

    def test_user_cannot_select_other_owner(self):
        self.fails(403, lambda: self.resource(self.a, owner=self.b))

    def test_key_owner_override_denied(self):
        self.fails(403, lambda: self.s.mutate(self.a, 'keys/create', {'name': 'x', 'owner': self.b}))

    def test_cross_user_delete_toggle_update_assign_and_revoke(self):
        r = self.resource()
        k = self.key()
        for action in ('resources/delete', 'resources/toggle', 'resources/update', 'resources/assign'):
            self.fails(404, lambda action=action: self.s.mutate(self.b, action, {'id': r['id'], 'revision': 1, 'enabled': False}))
        self.fails(404, lambda: self.s.mutate(self.b, 'keys/revoke', {'id': k['id']}))
        self.assertEqual(len(self.s.view(self.a)['resources']), 1)

    def test_admin_assign_removes_old_visibility_and_new_owner_readonly(self):
        r = self.resource()
        self.s.mutate(self.admin, 'resources/assign', {'id': r['id'], 'owner': self.b})
        self.assertEqual(self.s.view(self.a)['resources'], [])
        b = self.s.view(self.b)['resources'][0]
        self.assertFalse(b['writable'])
        self.fails(403, lambda: self.s.mutate(self.b, 'resources/delete', {'id': r['id'], 'revision': 2}))
        self.fails(403, lambda: self.s.mutate(self.b, 'resources/assign', {'id': r['id'], 'owner': self.a}))

    def test_users_cannot_update_limits_or_admin_status(self):
        body = {'id': self.a, 'enabled': True, 'limits': {'max_keys': 99, 'max_accounts': 99, 'max_upstreams': 99, 'max_concurrency': 99}}
        self.fails(403, lambda: self.s.mutate(self.a, 'users/update', body))
        self.fails(403, lambda: self.s.mutate(self.admin, 'users/update', body | {'id': self.admin}))

    def test_disable_user_invalidates_sessions_and_migration_inventory(self):
        token, _ = self.s.login('alice', 'alice-test-pass-123')
        self.key()
        self.resource()
        self.s.mutate(self.admin, 'users/update', {'id': self.a, 'enabled': False, 'limits': self.s.view(self.a)['limits']})
        self.fails(401, lambda: self.s.session(token))
        u = next(u for u in self.s.plan(self.admin)['users'] if u['user_id'] == self.a)
        self.assertEqual(u['key_scopes'], [])
        self.assertEqual(u['resources'], [])

    def test_password_change_revokes_all_sessions(self):
        first, _ = self.s.login('alice', 'alice-test-pass-123')
        second, _ = self.s.login('alice', 'alice-test-pass-123')
        self.s.mutate(self.a, 'password', {'current': 'alice-test-pass-123', 'password': 'new-alice-pass-1234'})
        for t in (first, second):
            self.fails(401, lambda t=t: self.s.session(t))
        self.s.login('alice', 'new-alice-pass-1234')

    def test_eight_character_password_and_self_service_change(self):
        uid = self.s.create_user(self.admin, 'eight-char-user', 'eightpw1')
        token, _ = self.s.login('eight-char-user', 'eightpw1')
        self.fails(400, lambda: self.s.create_user(self.admin, 'short-password', 'seven77'))
        self.fails(403, lambda: self.s.mutate(uid, 'password', {'current': 'wrongpw1', 'password': 'newpass1'}))
        self.s.session(token)
        self.s.mutate(uid, 'password', {'current': 'eightpw1', 'password': 'newpass1'})
        self.fails(401, lambda: self.s.session(token))
        self.fails(401, lambda: self.s.login('eight-char-user', 'eightpw1'))
        self.s.login('eight-char-user', 'newpass1')

    def test_no_duplicate_credentials_across_users(self):
        self.resource()
        self.fails(409, lambda: self.resource(self.b))

    def test_model_and_url_validation(self):
        for url in ('http://example.invalid', 'https://user:password@example.invalid', 'https://example.invalid?key=secret', 'https://example.invalid/v1/messages'):
            self.fails(400, lambda url=url: self.resource(base_url=url))
        for models in ([], ['same', 'same'], ['bad/model'], ['model\nname']):
            self.fails(400, lambda models=models: self.resource(models=models))

    def test_import_rejects_path_and_extra_file_fields(self):
        data = {'type': 'claude', 'access_token': 'access-A', 'refresh_token': 'refresh-A'}
        body = {'kind': 'account', 'provider': 'claude', 'name': '../../other.json', 'credential': data}
        r = self.s.mutate(self.admin, 'resources/create', body | {'owner': self.a})
        self.assertRegex(r['id'], r'^[a-f0-9]{32}$')
        self.fails(400, lambda: self.s.mutate(self.admin, 'resources/create', body | {'owner': self.b, 'credential': data | {'path': '/etc/passwd'}}))
        self.assertEqual(sorted(p.name for p in pathlib.Path(self.tmp.name).iterdir()), ['console.sqlite3', 'console.sqlite3-shm', 'console.sqlite3-wal'])

    def account(self):
        return self.s.mutate(self.admin, 'resources/create', {'owner': self.a, 'kind': 'account', 'provider': 'claude',
            'name': 'Assigned account', 'credential': {'type': 'claude', 'access_token': 'fake-a', 'refresh_token': 'fake-r'}})

    def test_user_cannot_create_accounts_even_with_forged_owner(self):
        body = {'kind': 'account', 'provider': 'claude', 'name': 'forbidden',
                'credential': {'type': 'claude', 'access_token': 'fake-a', 'refresh_token': 'fake-r'}}
        for extra in ({}, {'owner': self.admin}, {'owner': self.a, 'role': 'admin'}):
            self.fails(403, lambda extra=extra: self.s.mutate(self.a, 'resources/create', body | extra))

    def test_user_controls_assigned_account_but_cannot_change_credentials_delete_or_reassign(self):
        r = self.account()
        v = self.s.view(self.a)['resources'][0]
        self.assertTrue(v['controllable'])
        self.assertFalse(v['writable'])
        self.s.mutate(self.a, 'resources/toggle', {'id': r['id'], 'revision': 1, 'enabled': False})
        self.s.mutate(self.a, 'resources/weight', {'id': r['id'], 'revision': 2, 'weight': 7})
        self.s.mutate(self.a, 'resources/toggle', {'id': r['id'], 'revision': 3, 'enabled': True})
        self.assertEqual(self.s.view(self.a)['resources'][0]['weight'], 7)
        for action in ('resources/delete', 'resources/update', 'resources/assign'):
            self.fails(403, lambda action=action: self.s.mutate(self.a, action, {'id': r['id'], 'revision': 4}))
        self.fails(404, lambda: self.s.mutate(self.b, 'resources/weight', {'id': r['id'], 'revision': 4, 'weight': 10}))

    def test_admin_disabled_account_cannot_be_reenabled_by_user(self):
        r = self.account()
        self.s.mutate(self.admin, 'resources/toggle', {'id': r['id'], 'revision': 1, 'enabled': False})
        for action, extra in (('resources/toggle', {'enabled': True}), ('resources/weight', {'weight': 10})):
            self.fails(403, lambda action=action, extra=extra: self.s.mutate(self.a, action, {'id': r['id'], 'revision': 2} | extra))
        v = self.s.view(self.a)['resources'][0]
        self.assertFalse(v['controllable'])
        self.assertTrue(v['admin_disabled'])
        self.s.mutate(self.admin, 'resources/toggle', {'id': r['id'], 'revision': 2, 'enabled': True})
        self.assertTrue(self.s.view(self.a)['resources'][0]['controllable'])

    def test_weight_bounds_and_conflicts(self):
        r = self.account()
        for weight in (True, 0, -1, 11, 1.5, '5'):
            self.fails(400, lambda weight=weight: self.s.mutate(self.a, 'resources/weight', {'id': r['id'], 'revision': 1, 'weight': weight}))
        self.fails(409, lambda: self.s.mutate(self.a, 'resources/weight', {'id': r['id'], 'revision': 9, 'weight': 5}))

    def test_self_and_nonpublic_api_addresses_denied_on_create_and_update(self):
        r = self.resource()
        urls = ['https://8.8.4.4:9443/v1', 'https://127.0.0.1', 'https://[::1]',
                'https://[::ffff:127.0.0.1]', 'https://localhost.', 'https://sub.localhost',
                'https://10.1.2.3/v1', 'https://169.254.169.254', 'https://2130706433', 'https://server.local']
        self.s.forbidden_hosts |= {'console.example.invalid'}
        urls.append('https://CONSOLE.EXAMPLE.INVALID.:8443/v1')
        for url in urls:
            self.fails(400, lambda url=url: self.resource(base_url=url))
            self.fails(400, lambda url=url: self.s.mutate(self.a, 'resources/update', {'id': r['id'], 'revision': 1,
                'kind': 'upstream', 'provider': 'claude', 'name': 'changed', 'key': '', 'base_url': url, 'models': ['test-model']}))

    def test_connection_time_dns_validator_rejects_self_private_and_mixed_addresses(self):
        for ips in (['8.8.4.4'], ['127.0.0.1'], ['8.8.8.8', '10.0.0.1'], ['::ffff:127.0.0.1'], []):
            self.fails(400, lambda ips=ips: resolved_targets('https://alias.example.invalid', self.s.forbidden_hosts, lambda *_: ips))
        self.assertEqual(resolved_targets('https://example.invalid', self.s.forbidden_hosts, lambda *_: ['8.8.8.8']), ['8.8.8.8'])

    def test_quota_and_budget_are_not_fabricated(self):
        self.resource()
        v = self.s.view(self.a)
        self.assertFalse(v['runtime_connected'])
        self.assertNotIn('balance', v)
        self.assertFalse(self.key()['usable_in_cpa'])

    def test_stale_resource_update_is_rejected(self):
        r = self.resource()
        self.s.mutate(self.a, 'resources/toggle', {'id': r['id'], 'enabled': False, 'revision': 1})
        self.fails(409, lambda: self.s.mutate(self.a, 'resources/delete', {'id': r['id'], 'revision': 1}))

    def test_upstream_edit_preserves_blank_key_and_never_returns_it(self):
        r = self.resource()
        self.s.mutate(self.a, 'resources/update', {'id': r['id'], 'revision': 1, 'kind': 'upstream',
                      'provider': 'claude', 'name': 'renamed', 'key': '',
                      'base_url': 'https://example.invalid/v2', 'models': ['new-model']})
        self.assertEqual(self.s.view(self.a)['resources'][0]['name'], 'renamed')
        saved = self.s.db.execute('SELECT payload FROM resources WHERE id=?', (r['id'],)).fetchone()[0]
        self.assertEqual(json.loads(saved)['key'], 'fake-upstream-A')
        self.assertNotIn('fake-upstream-A', json.dumps(self.s.view(self.a)))

    def test_administrator_reset_password_requires_admin_and_revokes_sessions(self):
        token, _ = self.s.login('alice', 'alice-test-pass-123')
        self.fails(403, lambda: self.s.mutate(self.b, 'users/reset-password', {'id': self.a, 'password': 'changed-password-123'}))
        self.s.mutate(self.admin, 'users/reset-password', {'id': self.a, 'password': 'changed-password-123'})
        self.fails(401, lambda: self.s.session(token))
        self.fails(401, lambda: self.s.login('alice', 'alice-test-pass-123'))
        self.s.login('alice', 'changed-password-123')

    def test_expired_session_is_rejected(self):
        token, _ = self.s.login('alice', 'alice-test-pass-123')
        with self.s.transaction() as db:
            db.execute('UPDATE sessions SET expires=0 WHERE token=?', (digest(token),))
        self.fails(401, lambda: self.s.session(token))

    def test_audit_only_administrator(self):
        self.key()
        self.fails(403, lambda: self.s.audit_view(self.a))
        self.assertTrue(any(e['action'] == 'key.create' for e in self.s.audit_view(self.admin)['events']))

    def test_limits_reject_bool_negative_and_unrecognized_fields(self):
        limits = self.s.view(self.a)['limits']
        for invalid in (limits | {'max_keys': True}, limits | {'max_keys': -1}, limits | {'max_concurrency': 101}, limits | {'admin': 1}):
            self.fails(400, lambda invalid=invalid: self.s.mutate(self.admin, 'users/update', {'id': self.a, 'enabled': True, 'limits': invalid}))

    def test_resource_limit_admin_assignment_and_own_delete(self):
        r = self.resource()
        limits = self.s.view(self.b)['limits'] | {'max_upstreams': 0}
        self.s.mutate(self.admin, 'users/update', {'id': self.b, 'enabled': True, 'limits': limits})
        self.fails(409, lambda: self.s.mutate(self.admin, 'resources/assign', {'id': r['id'], 'owner': self.b}))
        self.assertEqual(self.s.view(self.a)['resources'][0]['id'], r['id'])
        self.s.mutate(self.a, 'resources/delete', {'id': r['id'], 'revision': 1})
        self.assertEqual(self.s.view(self.a)['resources'], [])

    def test_concurrent_creation_cannot_bypass_key_limit(self):
        def create(_):
            try:
                return self.key()['id']
            except Error as e:
                return e.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            out = list(pool.map(create, range(12)))
        self.assertEqual(out.count('key_limit'), 9)
        self.assertEqual(len(self.s.view(self.a)['keys']), 3)

    def test_audit_and_plan_do_not_include_secrets(self):
        k = self.key()
        self.resource()
        self.fails(403, lambda: self.s.plan(self.a))
        text = json.dumps(self.s.plan(self.admin))
        audit = str([tuple(r) for r in self.s.db.execute('SELECT * FROM audit')])
        for secret in (k['key'], 'fake-upstream-A', 'alice-test-pass-123'):
            self.assertNotIn(secret, text + audit)
        self.assertIn(digest('cli-proxy-api:caller-scope:v1\0' + k['key']), text)

    def test_persistence_and_no_automatic_runtime_activation(self):
        r = self.resource()
        self.s.db.close()
        self.s = Store(self.tmp.name)
        self.assertEqual(self.s.view(self.a)['resources'][0]['id'], r['id'])
        self.assertFalse(self.s.plan(self.admin)['can_apply'])

    def test_http_origin_csrf_session_cookie_and_unknown_actions(self):
        server = Server(('127.0.0.1', 0), self.s)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = server.origin[7:]
        def request(method, path, body=None, cookie='', csrf='', origin=None, hostname=host):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            headers = {'Host': hostname, 'Origin': origin or server.origin, 'Content-Type': 'application/json',
                       'Cookie': cookie, 'X-CSRF-Token': csrf}
            conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            res = conn.getresponse()
            raw, status, session = res.read(), res.status, res.getheader('Set-Cookie')
            conn.close()
            return status, json.loads(raw), session
        try:
            self.assertEqual(request('GET', '/api/state')[0], 401)
            body = {'username': 'alice', 'password': 'alice-test-pass-123'}
            self.assertEqual(request('POST', '/api/login', body, origin='http://evil.invalid')[0], 403)
            self.assertEqual(request('POST', '/api/login', body, hostname='evil.invalid')[0], 403)
            status, _, cookie = request('POST', '/api/login', body)
            self.assertEqual(status, 200)
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Strict', cookie)
            cookie = cookie.split(';')[0]
            _, state, _ = request('GET', '/api/state', cookie=cookie)
            self.assertEqual(request('POST', '/api/keys/create', {'name': 'x'}, cookie=cookie)[0], 403)
            csrf = state['csrf']
            self.assertEqual(request('POST', '/api/keys/create', {'name': 'x'}, cookie=cookie, csrf=csrf)[0], 200)
            self.assertEqual(request('POST', '/api/users/create', {'username': 'mallory', 'password': 'fake-password-123'}, cookie=cookie, csrf=csrf)[0], 403)
            self.assertEqual(request('GET', '/api/admin/plan', cookie=cookie)[0], 403)
            self.assertEqual(request('GET', '/api/admin/audit', cookie=cookie)[0], 403)
            self.assertEqual(request('POST', '/api/config', {}, cookie=cookie, csrf=csrf)[0], 404)
            self.assertEqual(request('POST', '/api/logout', {}, cookie=cookie, csrf=csrf)[0], 200)
            self.assertEqual(request('GET', '/api/state', cookie=cookie)[0], 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_ssh_forwarded_origin_keeps_host_and_csrf_checks(self):
        server = Server(('127.0.0.1', 0), self.s, 'http://127.0.0.1:18320')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            conn.request('GET', '/health', headers={'Host': '127.0.0.1:18320'})
            r = conn.getresponse()
            self.assertEqual(r.status, 200)
            r.read()
            conn.close()
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            conn.request('POST', '/api/login', json.dumps({'username': 'alice', 'password': 'alice-test-pass-123'}),
                         {'Host': '127.0.0.1:18320', 'Origin': 'http://127.0.0.1:18321', 'Content-Type': 'application/json'})
            r = conn.getresponse()
            self.assertEqual(r.status, 403)
            r.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main(verbosity=2)
