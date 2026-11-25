#!/usr/bin/env python3
"""Check the portable proxy rules using temporary, credential-free fixtures."""

import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parent.parent


class FakeMultiDict(dict):
    """Minimal stand-in for mitmproxy MultiDict / Headers supporting set_all."""

    def set_all(self, key, values):
        self[key] = list(values)


class FakeRequest:
    """Minimal stand-in for mitmproxy.http.Request for offline self-tests."""

    def __init__(
        self,
        url='https://example.invalid/api/demo',
        method='GET',
        headers=None,
        query=None,
        cookies=None,
        trailers=None,
        text='',
        content=b'',
        urlencoded_form=None,
        multipart_form=None,
    ):
        self.method = method
        self.http_version = 'HTTP/1.1'
        self._url = url
        scheme, rest = url.split('://', 1)
        host_port, _, path = rest.partition('/')
        self.scheme = scheme
        if ':' in host_port:
            host, port_s = host_port.split(':', 1)
            self.host = host
            self.port = int(port_s)
        else:
            self.host = host_port
            self.port = 443 if scheme == 'https' else 80
        self.authority = host_port
        self.host_header = host_port
        self.path = '/' + path
        self.path_components = [p for p in self.path.partition('?')[0].split('/') if p]
        self.headers = FakeMultiDict(headers or {})
        self.query = FakeMultiDict(query or {})
        self.cookies = FakeMultiDict(cookies or {})
        self.trailers = FakeMultiDict(trailers) if trailers is not None else None
        self.text = text
        self.content = content
        self.urlencoded_form = FakeMultiDict(urlencoded_form or {})
        self.multipart_form = FakeMultiDict(multipart_form or {})
        self.anticache_called = False
        self.anticomp_called = False

    @property
    def url(self):
        return self._url

    @url.setter
    def url(self, value):
        self._url = value
        scheme, rest = value.split('://', 1)
        host_port, _, path = rest.partition('/')
        self.scheme = scheme
        if ':' in host_port:
            host, port_s = host_port.split(':', 1)
            self.host = host
            self.port = int(port_s)
        else:
            self.host = host_port
            self.port = 443 if scheme == 'https' else 80
        self.host_header = host_port
        self.path = '/' + path

    @property
    def pretty_url(self):
        return f'{self.scheme}://{self.host_header}{self.path}'

    def anticache(self):
        self.anticache_called = True
        self.headers.pop('If-None-Match', None)

    def anticomp(self):
        self.anticomp_called = True
        self.headers['Accept-Encoding'] = 'identity'


with tempfile.TemporaryDirectory(prefix='http-proxy-check-') as temp:
    bundle = Path(temp) / 'bundle with spaces'
    for relative in (
        'scripts/http_proxy.py',
        'scripts/start_proxy.sh',
        'scripts/proxy_env.sh',
        'scripts/install_ca.sh',
        'assets/http_proxy/add_header.py',
        'assets/http_proxy/proxy_config.json',
        'examples/proxy_config.example.json',
    ):
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    config = bundle / 'assets/http_proxy/proxy_config.json'

    example_cfg = json.loads((bundle / 'examples/proxy_config.example.json').read_text(encoding='utf-8'))
    assert set(example_cfg) >= {'custom_headers', 'request_modifiers', 'response_modifiers'}
    assert len(example_cfg['request_modifiers']) >= 1

    def command(*args, ok=True):
        run = subprocess.run([sys.executable, str(bundle / 'scripts/http_proxy.py'), *args], capture_output=True, text=True)
        assert (run.returncode == 0) == ok, run.stderr
        return run.stdout

    command('clear')
    stub = types.ModuleType('mitmproxy')
    stub.http = types.SimpleNamespace(HTTPFlow=object, Headers=FakeMultiDict)
    sys.modules['mitmproxy'] = stub
    spec = importlib.util.spec_from_file_location('addon', bundle / 'assets/http_proxy/add_header.py')
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)

    def flow(url='https://example.invalid/api/demo', **req_kwargs):
        return types.SimpleNamespace(
            request=FakeRequest(url=url, **req_kwargs),
            response=types.SimpleNamespace(status_code=200, headers={}, text='{"keep":1,"nested":{"a":1}}'),
        )

    untouched = flow()
    addon.request(untouched)
    addon.response(untouched)
    assert untouched.request.headers == {} and json.loads(untouched.response.text)['keep'] == 1

    command('headers', 'X-Debug-Label=value=with=equals')
    addon._config_mtime = 0
    injected = flow()
    addon.request(injected)
    assert injected.request.headers == {'X-Debug-Label': 'value=with=equals'}

    before = config.read_bytes()
    command('headers', 'invalid-pair', ok=False)
    assert config.read_bytes() == before

    # Request rewrite: routing, path_replace, query, headers (including removing global), cookies, trailers, anticache/anticomp, body_patch
    command(
        'request',
        '--match-url', '/api/v1/demo',
        '--match-method', 'post',
        '--scheme', 'https',
        '--host', 'staging.example.invalid',
        '--port', '8443',
        '--host-header', 'api.staging.example.invalid',
        '--authority', 'api.staging.example.invalid:8443',
        '--http-version', 'HTTP/2.0',
        '--path-replace', '/api/v1/=/api/v2/',
        '--query', 'debug=1',
        '--query', 'tag=a',
        '--query', 'tag=b',
        '--remove-query', 'legacy',
        '--header', 'X-Rewrite=yes',
        '--remove-header', 'X-Debug-Label',
        '--cookie', 'env=staging',
        '--remove-cookie', 'old_sid',
        '--trailer', 'X-Trailer=ok',
        '--anticache',
        '--anticomp',
        '--body-patch', '{"dry_run":true,"nested":{"b":2}}',
    )
    addon._config_mtime = 0

    wrong_method = flow('https://example.invalid/api/v1/demo?legacy=1', method='GET', text='{"nested":{"a":1}}')
    addon.request(wrong_method)
    assert wrong_method.request.host == 'example.invalid' and wrong_method.request.headers['X-Debug-Label'] == 'value=with=equals'

    rewritten = flow(
        'https://example.invalid/api/v1/demo?legacy=1&keep=yes',
        method='POST',
        headers={'If-None-Match': '"v1"'},
        query={'legacy': '1', 'keep': 'yes'},
        cookies={'old_sid': 'x', 'stay': '1'},
        text='{"keep":1,"nested":{"a":1}}',
    )
    addon.request(rewritten)
    assert rewritten.request.http_version == 'HTTP/2.0'
    assert rewritten.request.host == 'staging.example.invalid' and rewritten.request.port == 8443
    assert rewritten.request.host_header == 'api.staging.example.invalid'
    assert rewritten.request.authority == 'api.staging.example.invalid:8443'
    assert rewritten.request.path == '/api/v2/demo?legacy=1&keep=yes'
    assert rewritten.request.query == {'keep': 'yes', 'debug': '1', 'tag': ['a', 'b']}
    assert 'X-Debug-Label' not in rewritten.request.headers
    assert rewritten.request.headers['X-Rewrite'] == 'yes'
    assert rewritten.request.headers['Accept-Encoding'] == 'identity'
    assert rewritten.request.anticache_called and rewritten.request.anticomp_called
    assert rewritten.request.cookies == {'stay': '1', 'env': 'staging'}
    assert rewritten.request.trailers == {'X-Trailer': 'ok'}
    assert json.loads(rewritten.request.text) == {'keep': 1, 'nested': {'a': 1, 'b': 2}, 'dry_run': True}

    # Request rewrite: nested body_patch deep-merge across CLI calls
    command('request', '--match-url', '/api/v1/demo', '--match-method', 'post', '--body-patch', '{"nested":{"c":3}}')
    addon._config_mtime = 0
    rewritten2 = flow(
        'https://example.invalid/api/v1/demo?legacy=1&keep=yes',
        method='POST',
        text='{"keep":1,"nested":{"a":1}}',
    )
    addon.request(rewritten2)
    assert json.loads(rewritten2.request.text) == {'keep': 1, 'nested': {'a': 1, 'b': 2, 'c': 3}, 'dry_run': True}

    # Request rewrite: full url, method, urlencoded_form
    command(
        'request',
        '--match-url', '/api/form',
        '--method', 'put',
        '--url', 'http://local.example.invalid:8080/api/form-v2',
        '--form', 'mode=preview',
        '--form', 'scope=r',
        '--form', 'scope=w',
        '--remove-form', 'obsolete',
    )
    addon._config_mtime = 0
    form_flow = flow('https://example.invalid/api/form', method='POST', urlencoded_form={'obsolete': '1', 'keep': 'ok'})
    addon.request(form_flow)
    assert form_flow.request.method == 'PUT'
    assert form_flow.request.url == 'http://local.example.invalid:8080/api/form-v2'
    assert form_flow.request.urlencoded_form == {'keep': 'ok', 'mode': 'preview', 'scope': ['r', 'w']}

    # Request rewrite: path_components, multipart_form (bytes keys/values), remove_trailers
    command(
        'request',
        '--match-url', '/api/upload',
        '--path-component', 'api',
        '--path-component', 'v2',
        '--path-component', 'upload',
        '--multipart', 'category=test',
        '--remove-multipart', 'unused',
        '--remove-trailer', 'X-Old',
    )
    addon._config_mtime = 0
    mp_flow = flow(
        'https://example.invalid/api/upload',
        method='POST',
        multipart_form={b'unused': b'1', b'keep': b'yes'},
        trailers={'X-Old': 'drop', 'X-Keep': '1'},
    )
    addon.request(mp_flow)
    assert mp_flow.request.path_components == ['api', 'v2', 'upload']
    assert mp_flow.request.multipart_form == {b'keep': b'yes', b'category': b'test'}
    assert mp_flow.request.trailers == {'X-Keep': '1'}

    # Request rewrite: raw body and body_base64
    command('request', '--match-url', '/api/raw', '--path', '/api/raw-v2', '--body', 'plain-body')
    raw_b64 = base64.b64encode(b'\x01\x02\x03\x04').decode('ascii')
    command('request', '--match-url', '/api/bin', '--body-base64', raw_b64)
    addon._config_mtime = 0
    raw_flow = flow('https://example.invalid/api/raw', method='POST')
    bin_flow = flow('https://example.invalid/api/bin', method='POST')
    addon.request(raw_flow)
    addon.request(bin_flow)
    assert raw_flow.request.path == '/api/raw-v2' and raw_flow.request.text == 'plain-body'
    assert bin_flow.request.content == b'\x01\x02\x03\x04'

    # CLI validation checks for request command
    before_req = config.read_bytes()
    command('request', '--match-url', '/api/x', ok=False)
    command('request', '--match-url', '/api/x', '--body', 'a', '--body-patch', '{}', ok=False)
    command('request', '--match-url', '/api/x', '--body-patch', 'not-json', ok=False)
    command('request', '--match-url', '/api/x', '--body-base64', '!!!', ok=False)
    command('request', '--match-url', '/api/x', '--port', '70000', ok=False)
    assert config.read_bytes() == before_req

    # Response rewrite checks
    command(
        'response',
        '--match-url', '/api/demo',
        '--msg', 'test response',
        '--body-patch', '{"extra":{"k":"v"}}',
        '--header', 'X-Mock=1',
        '--header', 'X-Multi=a',
        '--header', 'X-Multi=b',
    )
    command('response', '--match-url', '/api/demo', '--body-patch', '{"extra":{"k2":"v2"}}')
    addon._config_mtime = 0
    patched = flow()
    patched.response.headers = FakeMultiDict()
    addon.response(patched)
    assert json.loads(patched.response.text) == {
        'keep': 1,
        'nested': {'a': 1},
        'msg': 'test response',
        'extra': {'k': 'v', 'k2': 'v2'},
    }
    assert patched.response.headers['X-Mock'] == '1'
    assert patched.response.headers['X-Multi'] == ['a', 'b']

    # Status/header-only response rule does not inject an empty body_patch
    command('response', '--match-url', '/api/status-only', '--status-code', '503', '--header', 'Retry-After=60')
    cfg_now = json.loads(command('show'))
    status_rule = [r for r in cfg_now['response_modifiers'] if '/api/status-only' in r['match_url']][0]
    assert 'body_patch' not in status_rule and status_rule['status_code'] == 503

    command('response', '--msg', 'missing-match-url', ok=False)
    command('response', '--match-url', '/api/demo', '--status-code', '999', ok=False)
    command('response', '--match-url', '/api/demo', '--body', 'x', '--body-patch', '{}', ok=False)

    unmatched = flow('https://example.invalid/other')
    addon.response(unmatched)
    assert 'msg' not in json.loads(unmatched.response.text)

    command('response', '--match-url', '/api/demo', '--body', '{"example":true}', '--status-code', '202')
    addon._config_mtime = 0
    replaced = flow()
    addon.response(replaced)
    assert replaced.response.status_code == 202 and json.loads(replaced.response.text) == {'example': True}

    base = {'nested': {'a': 1}, 'keep': 2}
    addon._deep_merge(base, {'nested': {'b': 3}})
    assert base == {'nested': {'a': 1, 'b': 3}, 'keep': 2}

    command('clear')
    assert json.loads(command('show')) == {'custom_headers': {}, 'request_modifiers': [], 'response_modifiers': []}

    checks = 15
    bash = shutil.which('bash')
    if bash and os.name != 'nt':
        fake_bin = Path(temp) / 'bin'
        fake_bin.mkdir()
        fake_home = Path(temp) / 'home'
        fake_home.mkdir()
        record_file = Path(temp) / 'recorded.json'
        py_recorder = (
            'import json, sys; '
            'open(sys.argv[1], "w", encoding="utf-8").write('
            'json.dumps({"bin": sys.argv[2], "argv": sys.argv[3:]}))'
        )
        for tool in ('mitmdump', 'mitmweb'):
            wrapper = fake_bin / tool
            wrapper.write_text(
                '#!/bin/sh\n'
                f'exec "{sys.executable}" -c \'{py_recorder}\' "{record_file}" "{tool}" "$@"\n',
                encoding='utf-8',
            )
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

        start_env = os.environ.copy()
        start_env['PATH'] = f'{fake_bin}{os.pathsep}{start_env.get("PATH", "")}'
        start_env['HOME'] = str(fake_home)
        addon_path = str(bundle / 'assets/http_proxy/add_header.py')
        confdir_opt = f'confdir={fake_home}/.http-proxy-toolkit/mitmproxy'

        def run_start(*args, ok=True):
            if record_file.exists():
                record_file.unlink()
            run = subprocess.run(
                [bash, str(bundle / 'scripts/start_proxy.sh'), *args],
                env=start_env,
                capture_output=True,
                text=True,
            )
            assert (run.returncode == 0) == ok, (args, run.returncode, run.stdout, run.stderr)
            recorded = json.loads(record_file.read_text(encoding='utf-8')) if record_file.exists() else None
            return run, recorded

        _, rec = run_start()
        assert rec == {
            'bin': 'mitmdump',
            'argv': ['--listen-host', '127.0.0.1', '--listen-port', '8080', '--set', confdir_opt, '--flow-detail', '0', '-s', addon_path],
        }, rec

        _, rec = run_start('18080', '--flow-detail', '4')
        assert rec == {
            'bin': 'mitmdump',
            'argv': ['--listen-host', '127.0.0.1', '--listen-port', '18080', '--set', confdir_opt, '--flow-detail', '4', '-s', addon_path],
        }, rec

        _, rec = run_start('--web')
        assert rec == {
            'bin': 'mitmweb',
            'argv': ['--listen-host', '127.0.0.1', '--listen-port', '8080', '--web-host', '127.0.0.1', '--web-port', '8081', '--set', confdir_opt, '-s', addon_path],
        }, rec

        _, rec = run_start('--port=18080', '--web-port=18081')
        assert rec == {
            'bin': 'mitmweb',
            'argv': ['--listen-host', '127.0.0.1', '--listen-port', '18080', '--web-host', '127.0.0.1', '--web-port', '18081', '--set', confdir_opt, '-s', addon_path],
        }, rec

        help_run, rec = run_start('--help')
        assert rec is None and '--web' in help_run.stdout and '--flow-detail' in help_run.stdout

        run_start('--web', '--flow-detail', '3', ok=False)
        run_start('--port', '8081', '--web-port', '8081', ok=False)
        run_start('--flow-detail', '5', ok=False)
        run_start('--unknown', ok=False)

        # Generic proxy_env.sh checks
        env_script = str(bundle / 'scripts/proxy_env.sh')
        fake_ca_dir = fake_home / '.http-proxy-toolkit/mitmproxy'
        fake_ca = fake_ca_dir / 'mitmproxy-ca-cert.pem'

        # Missing CA fails
        missing_ca_run = subprocess.run(
            [bash, '-c', 'source "$1" 18080', '_', env_script],
            env=start_env,
            capture_output=True,
            text=True,
        )
        assert missing_ca_run.returncode != 0, missing_ca_run.stdout

        # Invalid port fails
        fake_ca_dir.mkdir(parents=True, exist_ok=True)
        fake_ca.write_text('dummy-ca', encoding='utf-8')
        bad_port_run = subprocess.run(
            [bash, '-c', 'source "$1" 70000', '_', env_script],
            env=start_env,
            capture_output=True,
            text=True,
        )
        assert bad_port_run.returncode != 0, bad_port_run.stdout

        # Enable sets all generic proxy & CA env vars, off clears them
        env_keys = (
            'http_proxy',
            'https_proxy',
            'HTTP_PROXY',
            'HTTPS_PROXY',
            'SSL_CERT_FILE',
            'REQUESTS_CA_BUNDLE',
            'CURL_CA_BUNDLE',
            'NODE_EXTRA_CA_CERTS',
        )
        py_dump = (
            'import json, os, sys; '
            'print(json.dumps({k: os.environ.get(k) for k in sys.argv[1:]}))'
        )
        on_off_cmd = (
            'source "$1" 18080 >/dev/null && '
            f'"{sys.executable}" -c \'{py_dump}\' ' + ' '.join(env_keys) + ' && '
            'source "$1" off >/dev/null && '
            f'"{sys.executable}" -c \'{py_dump}\' ' + ' '.join(env_keys)
        )
        env_run = subprocess.run(
            [bash, '-c', on_off_cmd, '_', env_script],
            env=start_env,
            capture_output=True,
            text=True,
        )
        assert env_run.returncode == 0, env_run.stderr
        on_state, off_state = [json.loads(line) for line in env_run.stdout.strip().splitlines()]
        for key in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
            assert on_state[key] == 'http://127.0.0.1:18080', (key, on_state)
        for key in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS'):
            assert on_state[key] == str(fake_ca), (key, on_state)
        assert all(off_state[k] is None for k in env_keys), off_state

        # install_ca.sh checks (isolated with fake security/sudo/openssl/uname)
        ca_script = str(bundle / 'scripts/install_ca.sh')
        ca_bin = Path(temp) / 'ca-bin'
        ca_bin.mkdir()
        ca_calls_file = Path(temp) / 'ca_calls.jsonl'
        py_append = (
            'import json, sys; '
            'open(sys.argv[1], "a", encoding="utf-8").write('
            'json.dumps({"bin": sys.argv[2], "argv": sys.argv[3:]}) + "\\n")'
        )
        for tool in ('security', 'sudo'):
            wrapper = ca_bin / tool
            wrapper.write_text(
                '#!/bin/sh\n'
                f'exec "{sys.executable}" -c \'{py_append}\' "{ca_calls_file}" "{tool}" "$@"\n',
                encoding='utf-8',
            )
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        fake_openssl = ca_bin / 'openssl'
        fake_openssl.write_text(
            '#!/bin/sh\n'
            'echo "SHA1 Fingerprint=AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD"\n',
            encoding='utf-8',
        )
        fake_openssl.chmod(fake_openssl.stat().st_mode | stat.S_IXUSR)
        fake_uname = ca_bin / 'uname'
        fake_uname.write_text('#!/bin/sh\necho Darwin\n', encoding='utf-8')
        fake_uname.chmod(fake_uname.stat().st_mode | stat.S_IXUSR)

        ca_env = os.environ.copy()
        ca_env['PATH'] = f'{ca_bin}{os.pathsep}{ca_env.get("PATH", "")}'
        ca_env['HOME'] = str(fake_home)

        def run_ca(*args, ok=True):
            if ca_calls_file.exists():
                ca_calls_file.unlink()
            run = subprocess.run(
                [bash, ca_script, *args],
                env=ca_env,
                capture_output=True,
                text=True,
            )
            assert (run.returncode == 0) == ok, (args, run.returncode, run.stdout, run.stderr)
            calls = (
                [json.loads(line) for line in ca_calls_file.read_text(encoding='utf-8').splitlines() if line]
                if ca_calls_file.exists()
                else []
            )
            return run, calls

        help_ca, calls = run_ca('--help')
        assert calls == [] and '--system' in help_ca.stdout and '--uninstall' in help_ca.stdout
        run_ca('--unknown', ok=False)
        run_ca('--cert', str(fake_home / 'nonexistent.pem'), ok=False)

        login_kc = f'{fake_home}/Library/Keychains/login.keychain-db'
        _, calls = run_ca()
        assert calls == [
            {'bin': 'security', 'argv': ['add-trusted-cert', '-r', 'trustRoot', '-k', login_kc, str(fake_ca)]}
        ], calls

        _, calls = run_ca('--system')
        assert calls == [
            {
                'bin': 'sudo',
                'argv': ['security', 'add-trusted-cert', '-d', '-r', 'trustRoot', '-k', '/Library/Keychains/System.keychain', str(fake_ca)],
            }
        ], calls

        expected_sha1 = 'AABBCCDDEEFF00112233445566778899AABBCCDD'
        _, calls = run_ca('--uninstall')
        assert calls == [
            {'bin': 'security', 'argv': ['remove-trusted-cert', str(fake_ca)]},
            {'bin': 'security', 'argv': ['delete-certificate', '-Z', expected_sha1, login_kc]},
        ], calls

        custom_cert = fake_home / 'custom-ca.pem'
        custom_cert.write_text('custom-ca', encoding='utf-8')
        _, calls = run_ca('--system', '--uninstall', '--cert', str(custom_cert))
        assert calls == [
            {'bin': 'sudo', 'argv': ['security', 'remove-trusted-cert', '-d', str(custom_cert)]},
            {'bin': 'sudo', 'argv': ['security', 'delete-certificate', '-Z', expected_sha1, '/Library/Keychains/System.keychain']},
        ], calls

        # Failing uninstall (e.g. authorization denied / not installed) must exit non-zero
        fail_bin = Path(temp) / 'ca-fail-bin'
        fail_bin.mkdir()
        (fail_bin / 'uname').write_text('#!/bin/sh\necho Darwin\n', encoding='utf-8')
        (fail_bin / 'uname').chmod(0o755)
        (fail_bin / 'security').write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        (fail_bin / 'security').chmod(0o755)
        fail_env = os.environ.copy()
        fail_env['PATH'] = f'{fail_bin}{os.pathsep}{fail_env.get("PATH", "")}'
        fail_env['HOME'] = str(fake_home)
        fail_run = subprocess.run([bash, ca_script, '--uninstall'], env=fail_env, capture_output=True, text=True)
        assert fail_run.returncode != 0

        checks += 23

    print(f'PASS: {checks} proxy configuration, addon, and launcher checks; no network requests.')
