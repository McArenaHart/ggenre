# Local Testing Guide

This project includes a local bootstrap command and script for repeatable testing of:

- YouTube embedded content uploads
- OTP vote access lifecycle (grant, extend, cancel, reset)

## 1. One-time setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Quick start (recommended)

Run this from the project root:

```powershell
.\scripts\start_local.ps1 -Reset -RunTests
```

What it does:

- Sets `DJANGO_DEBUG=True` and `LOCAL_CONSOLE_EMAIL=True`
- Runs migrations
- Seeds local users/content/OTP data
- Runs tests (because `-RunTests` is passed)
- Starts the development server

Useful options:

```powershell
.\scripts\start_local.ps1 -Reset -FanVotes 10
.\scripts\start_local.ps1 -NoServer
.\scripts\start_local.ps1 -ListenHost 0.0.0.0 -Port 8080
```

## 3. Manual commands (if preferred)

```powershell
$env:DJANGO_DEBUG="True"
$env:LOCAL_CONSOLE_EMAIL="True"
python manage.py migrate
python manage.py setup_local_testing --reset --fan-votes 10
python manage.py runserver
```

## 4. Seeded local accounts

- Admin: `local_admin` / `Admin123!`
- Artist: `local_artist` / `Artist123!`
- Fan: `local_fan` / `Fan123!`
- OTP for fan: `123456` (default 10 votes)

## 5. Feature verification checklist

1. YouTube embed
- Login as `local_artist`
- Upload content using only a YouTube URL (no file)
- Open content list/detail page and confirm in-app embedded playback

2. OTP single-use flow
- Login as `local_fan`
- Vote for up to 10 content items using OTP `123456`
- Confirm scores cannot be reused in the same genre during the active vote window
- Confirm voting is blocked when votes reach zero

3. Admin OTP controls
- Login as `local_admin`
- Open admin dashboard OTP controls
- Extend votes for `local_fan` and vote again as fan
- Cancel access and confirm voting is blocked
- Reset access and confirm fan can vote again

## 6. Email/OTP testing behavior

With `LOCAL_CONSOLE_EMAIL=True`, OTP and email messages are printed to the terminal running Django. No SMTP credentials are required for local testing.

If PowerShell blocks script execution, run with a temporary bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -Reset
```

## 7. Mission Review Policy And Automation Infrastructure

The mission review system supports policy-level configuration without enabling a live AI chatbot.

Optional Django setting (for example in local environment config):

```python
CHATAPP_MISSION_POLICY = {
	"review_route_mode": "alternate",  # alternate | manual_only | ai_preferred
	"ai_confidence_threshold": 0.75,
	"prefer_online_opponent": True,
	"rematch_cooldown_hours": 12,
	"bulk_review_max_items": 10,
}
```

Notes:

- AI-routed mission reviews now create `ReviewAutomationTicket` rows in queued status.
- This is infrastructure only: no chatbot auto-approvals are executed.

## 8. Ops Metrics Command

Use this command to inspect routing and moderation metrics:

```powershell
python manage.py mission_review_metrics --days 7
```

The output includes:

- Active policy snapshot
- Mission route counts (AI/manual)
- Mission decision counts (approve/reject)
- Automation ticket status counts
