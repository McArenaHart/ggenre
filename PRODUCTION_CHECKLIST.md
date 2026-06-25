# Production Checklist

## 1) Configure environment
1. Copy `.env.example` to `.env`.
2. Fill all `replace-with-...` values.
3. Keep `DJANGO_DEBUG=False` and `DJANGO_PRODUCTION=True`.

## 2) Install dependencies
```bash
pip install -r requirements.txt
```

## 3) Run database and static setup
```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

## 4) Validate hardened settings
```bash
python manage.py check --deploy
```

Expected output:
```text
System check identified no issues (0 silenced).
```

## 5) Run app server
GGenre chat, contact-admin, and livestream signaling require websockets. Run the
app with ASGI, not the WSGI-only Gunicorn command.

ASGI (Daphne):
```bash
daphne -b 0.0.0.0 -p 8000 ggenre.asgi:application
```

If you use systemd, the service `ExecStart` should point at Daphne:
```ini
ExecStart=/path/to/venv/bin/daphne -b 127.0.0.1 -p 8000 ggenre.asgi:application
```

## 6) Reverse proxy and TLS
1. Put Nginx in front of Daphne.
2. Terminate TLS at Nginx (LetsEncrypt recommended).
3. Forward `X-Forwarded-Proto` and `Host` headers.
4. Forward websocket upgrade headers for `/ws/`.

Minimum Nginx websocket proxy block:
```nginx
location /ws/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
}
```

The regular HTTP proxy block should also point to the same Daphne process:
```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 7) Post-deploy checks
1. Login/logout flow works.
2. Registration completes without OTP and redirects to login.
3. Static assets and uploaded media are accessible.
4. Admin dashboard opens at `/support/`.
5. Browser devtools Network shows `wss://<domain>/ws/chat/user/<id>/`
   returning status `101 Switching Protocols`.
6. Contact-admin and peer inbox chat status changes to `Online`.

## OTP Removal
- User registration is now password-based only; OTP verification/resend routes redirect to login with an informational message.
- No email delivery is required for account activation.
- Keep auth throttling enabled via `AUTH_THROTTLE_WINDOW_SECONDS`, `AUTH_REGISTER_MAX_ATTEMPTS`, and `AUTH_LOGIN_MAX_ATTEMPTS`.
