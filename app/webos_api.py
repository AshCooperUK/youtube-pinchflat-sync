"""Read-only webOS access using explicit browser approval and scoped media grants.

Packaged webOS apps cannot use the website's cookie jar. No existing endpoint
accepts these device credentials. Browser approval keeps password and 2FA on
the existing website. The app never receives a website session or CSRF token.
"""
import functools
import hashlib
import re
import secrets
import time
from urllib.parse import unquote

from flask import abort, g, jsonify, make_response, render_template, request, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

WEBOS_API_ENDPOINTS = frozenset({
    'webos_info', 'webos_pair_start', 'webos_pair_status', 'webos_session',
    'webos_library', 'webos_channels', 'webos_video', 'webos_media',
    'webos_artwork', 'webos_subtitle', 'webos_signout',
})


def install_webos_routes(app, host):
    signer = URLSafeTimedSerializer(app.secret_key, salt='ytsd-webos-media-v1')

    def digest(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def database():
        conn = host['db']()
        conn.execute('''CREATE TABLE IF NOT EXISTS webos_devices (
            id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
            user_id INTEGER, session_version INTEGER, name TEXT NOT NULL,
            created REAL NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS webos_pairing (
            code TEXT PRIMARY KEY, secret_hash TEXT UNIQUE NOT NULL,
            created REAL NOT NULL, expires REAL NOT NULL, ip_hash TEXT NOT NULL,
            user_id INTEGER, session_version INTEGER, consumed INTEGER NOT NULL DEFAULT 0)''')
        return conn

    def payload(**values):
        return jsonify(ok=True, **values)

    def problem(message, code=401):
        response = jsonify(ok=False, error=message)
        response.status_code = code
        return response

    def device(identifier=None):
        with database() as conn:
            if identifier is not None:
                row = conn.execute('SELECT * FROM webos_devices WHERE id=?', (identifier,)).fetchone()
            else:
                header = request.headers.get('Authorization', '')
                if not header.startswith('Bearer ') or len(header) > 200:
                    return None
                row = conn.execute('SELECT * FROM webos_devices WHERE token_hash=?', (digest(header[7:]),)).fetchone()
        if not row or row['revoked'] or row['expires'] <= time.time():
            return None
        user = host['get_user_by_id'](row['user_id'])
        if not user or not user['active'] or int(user['session_version'] or 1) != row['session_version']:
            return None
        g.webos_user = user
        g.webos_device = row
        return row

    def authenticated(fn):
        @functools.wraps(fn)
        def guarded(*args, **kwargs):
            if device() is None:
                return problem('Sign-in expired. Link this TV again.')
            return fn(*args, **kwargs)
        return guarded

    @app.after_request
    def webos_headers(response):
        if request.endpoint in WEBOS_API_ENDPOINTS:
            # These endpoints ignore cookies. A bearer credential or individual
            # signed media grant is compulsory except for pairing discovery.
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, Range'
            response.headers['Access-Control-Expose-Headers'] = 'Content-Range, Accept-Ranges, Content-Length'
            response.headers['Access-Control-Max-Age'] = '600'
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            # Browsing through this API never modifies a website session.
        if request.endpoint == 'webos_link':
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Frame-Options'] = 'DENY'
        return response

    def json_body():
        if not request.is_json or (request.content_length or 0) > 4096:
            abort(400)
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400)
        return value

    @app.get('/api/webos/info')
    def webos_info():
        return payload(api_version=1, server_version=host['VERSION'], setup_required=not host['users_exist']())

    @app.post('/api/webos/pair/start')
    def webos_pair_start():
        json_body()
        if not host['users_exist']():
            return problem('Complete server setup in your browser first.', 409)
        now = time.time()
        ip = digest(str(request.remote_addr or 'unknown'))
        secret = secrets.token_urlsafe(32)
        alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
        with database() as conn:
            conn.execute('DELETE FROM webos_pairing WHERE created < ?', (now - 600,))
            count = conn.execute('SELECT COUNT(*) FROM webos_pairing WHERE ip_hash=?', (ip,)).fetchone()[0]
            total = conn.execute('SELECT COUNT(*) FROM webos_pairing').fetchone()[0]
            if count >= 12 or total >= 500:
                return problem('Too many pairing requests. Try again in ten minutes.', 429)
            for _ in range(5):
                code = ''.join(secrets.choice(alphabet) for _ in range(8))
                if not conn.execute('SELECT 1 FROM webos_pairing WHERE code=?', (code,)).fetchone():
                    break
            else:
                return problem('Pairing is busy. Try again.', 503)
            conn.execute('INSERT INTO webos_pairing(code,secret_hash,created,expires,ip_hash) VALUES(?,?,?,?,?)',
                         (code, digest(secret), now, now + 600, ip))
        return payload(code=code[:4] + '-' + code[4:], secret=secret, expires_in=600, poll_interval=5,
                       verification_path='/tv-link')

    @app.post('/api/webos/pair/status')
    def webos_pair_status():
        body = json_body()
        secret = str(body.get('secret') or '')
        if not 30 <= len(secret) <= 100:
            return problem('Pairing has expired.', 410)
        now = time.time()
        with database() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM webos_pairing WHERE secret_hash=?', (digest(secret),)).fetchone()
            if not row or row['consumed'] or row['expires'] <= now:
                return problem('Pairing has expired. Request a new code.', 410)
            if not row['user_id']:
                return payload(status='pending')
            user = host['get_user_by_id'](row['user_id'])
            if not user or not user['active'] or int(user['session_version'] or 1) != row['session_version']:
                return problem('Account sign-in has changed. Request a new code.', 401)
            token = secrets.token_urlsafe(48)
            identifier = secrets.token_hex(16)
            expires = now + min(30, host['remember_login_days']()) * 86400
            conn.execute('DELETE FROM webos_devices WHERE expires < ?', (now,))
            conn.execute('INSERT INTO webos_devices VALUES(?,?,?,?,?,?,?,0)',
                         (identifier, digest(token), user['id'], int(user['session_version'] or 1),
                          'LG webOS TV', now, expires))
            conn.execute('UPDATE webos_pairing SET consumed=1 WHERE code=?', (row['code'],))
        return payload(status='approved', token=token, expires=expires,
                       user_id=str(user['id']), username=user['username'])

    @app.route('/tv-link', methods=['GET', 'POST'])
    def webos_link():
        user = host['current_user_record']()
        message = ''
        with database() as conn:
            if request.method == 'POST':
                if request.form.get('revoke'):
                    conn.execute('UPDATE webos_devices SET revoked=1 WHERE id=? AND user_id=?',
                                 (request.form['revoke'], user['id']))
                    message = 'TV access removed.'
                else:
                    code = re.sub(r'[^A-Z0-9]', '', request.form.get('code', '').upper())[:20]
                    changed = conn.execute('''UPDATE webos_pairing SET user_id=?, session_version=?
                        WHERE code=? AND expires>? AND consumed=0 AND user_id IS NULL''',
                        (user['id'], int(user['session_version'] or 1), code, time.time())).rowcount
                    message = 'TV approved. Return to your television.' if changed else 'Code expired or already used. Check the code on your TV.'
            rows = conn.execute('SELECT * FROM webos_devices WHERE user_id=? AND revoked=0 AND expires>? ORDER BY created DESC',
                                (user['id'], time.time())).fetchall()
        return render_template('tv_link.html', message=message, devices=rows, username=user['username'])

    @app.get('/api/webos/session')
    @authenticated
    def webos_session():
        return payload(api_version=1, server_version=host['VERSION'], user_id=str(g.webos_user['id']),
                       username=g.webos_user['username'], expires=g.webos_device['expires'], progress_storage='device')

    def grant(kind, identifier, index=None):
        value = dict(device=g.webos_device['id'], kind=kind, job=identifier)
        if index is not None:
            value['index'] = index
        token = signer.dumps(value)
        endpoint = dict(media='webos_media', artwork='webos_artwork', subtitle='webos_subtitle')[kind]
        args = dict(job_id=identifier, grant=token)
        if index is not None:
            args['index'] = index
        return url_for(endpoint, **args)

    def rewrite(item):
        identifier = item['id']
        item['stream_url'] = grant('media', identifier)
        item['detail_url'] = url_for('webos_video', job_id=identifier)
        if str(item.get('thumbnail_url') or '').startswith('/api/tv/artwork/'):
            item['thumbnail_url'] = grant('artwork', identifier)
        for index, sub in enumerate(item.get('subtitles', [])):
            sub['url'] = grant('subtitle', identifier, index)
            # Native HTML tracks use WebVTT. SRT receives a lossless timing/text conversion.
            sub['supported'] = sub['mime_type'] in ('text/vtt', 'application/x-subrip')
            if sub['supported']:
                sub['mime_type'] = 'text/vtt'
        return item

    @app.get('/api/webos/library')
    @authenticated
    def webos_library():
        data = app.view_functions['tv_library']().get_json()
        data['items'] = [rewrite(item) for item in data['items']]
        return jsonify(data)

    @app.get('/api/webos/channels')
    @authenticated
    def webos_channels():
        data = app.view_functions['tv_channels']().get_json()
        # Channel images may refer to another video. Derive the job from a URL through the URL map.
        adapter = app.url_map.bind('localhost')
        for item in data['items']:
            path = str(item.get('thumbnail_url') or '')
            if path.startswith('/api/tv/artwork/'):
                _, arguments = adapter.match(unquote(path))
                item['thumbnail_url'] = grant('artwork', arguments['job_id'])
        return jsonify(data)

    @app.get('/api/webos/videos/<job_id>')
    @authenticated
    def webos_video(job_id):
        data = app.view_functions['tv_video'](job_id).get_json()
        data['item'] = rewrite(data['item'])
        return jsonify(data)

    def media_access(kind, job_id, index=None):
        try:
            value = signer.loads(request.args.get('grant', ''), max_age=12 * 3600)
        except (BadSignature, SignatureExpired):
            abort(401)
        if not isinstance(value, dict) or value.get('kind') != kind or value.get('job') != job_id or value.get('index') != index:
            abort(401)
        if device(value.get('device')) is None:
            abort(401)
        # Apply the same completed/playable checks even to previously issued URLs.
        app.view_functions['tv_video'](job_id)

    @app.get('/api/webos/media/<job_id>')
    def webos_media(job_id):
        media_access('media', job_id)
        return host['completed_download_media'](job_id)

    @app.get('/api/webos/artwork/<job_id>')
    def webos_artwork(job_id):
        media_access('artwork', job_id)
        return app.view_functions['tv_artwork'](job_id)

    @app.get('/api/webos/subtitles/<job_id>/<int:index>')
    def webos_subtitle(job_id, index):
        media_access('subtitle', job_id, index)
        details = app.view_functions['tv_video'](job_id).get_json()['item']['subtitles']
        if index >= len(details):
            abort(404)
        mime = details[index]['mime_type']
        response = app.view_functions['tv_subtitle'](job_id, index)
        if mime == 'application/x-subrip':
            response.direct_passthrough = False
            text = response.get_data().decode('utf-8-sig', errors='replace').replace('\r\n', '\n')
            text = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})', r'\1.\2', text)
            response = make_response('WEBVTT\n\n' + text)
            response.mimetype = 'text/vtt'
        elif mime == 'text/vtt':
            response.mimetype = 'text/vtt'
        else:
            abort(415, description='This TV subtitle track needs WebVTT or SRT.')
        return response

    @app.post('/api/webos/signout')
    @authenticated
    def webos_signout():
        json_body()
        with database() as conn:
            conn.execute('UPDATE webos_devices SET revoked=1 WHERE id=?', (g.webos_device['id'],))
        return payload()

