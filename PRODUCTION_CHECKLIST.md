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
WSGI (Gunicorn):
```bash
gunicorn ggenre.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

ASGI (Daphne, for websocket support):
```bash
daphne -b 0.0.0.0 -p 8000 ggenre.asgi:application
```

## 6) Reverse proxy and TLS
1. Put Nginx in front of Gunicorn/Daphne.
2. Terminate TLS at Nginx (LetsEncrypt recommended).
3. Forward `X-Forwarded-Proto` and `Host` headers.

## 7) Post-deploy checks
1. Login/logout flow works.
2. OTP email delivery works.
3. Static assets and uploaded media are accessible.
4. Admin dashboard opens at `/support/`.
