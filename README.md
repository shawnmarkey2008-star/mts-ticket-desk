# MTS Ticket Desk

A self-hosted, single-user IT service ticket manager built for Markey Tech Solutions with **Python's standard library and SQLite**. No Flask or pip dependencies are required.

## Features

- Dashboard with ticket counts, active repairs, and outstanding balances.
- Customer/device fields, reported issues, diagnosis, work performed, and notes.
- Repair status tracking, estimates, and payments.
- Search, status filtering, and CSV export.
- Persistent SQLite storage and password-protected access.

The public repository contains application code only. First startup creates an empty database; no real customer records, credentials, or saved tickets are distributed.

## Start locally

Use Python 3.7 or newer (a maintained Python 3 release is recommended).

macOS/Linux:

```sh
python3 server.py
```

Windows:

```powershell
python server.py
```

Enter a password at the hidden prompt, then open **http://127.0.0.1:8765**. Sign in with username **`mts`** and the password you entered. Keep the terminal running; use Ctrl+C to stop. The included Mac and Windows launchers also start the app on localhost.

This public version prompts for a session password instead of writing passwords into shell configuration files. If `MTS_PASSWORD` is already set in the environment, it uses that value instead.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MTS_HOST` | `127.0.0.1` | Listening address |
| `MTS_PORT` | `8765` | HTTP port |
| `MTS_DB` | `mts_tickets.sqlite3` beside `server.py` | Database path |
| `MTS_PASSWORD` | Hidden prompt at startup | Authentication password |

## Storage and backups

The SQLite database is created automatically and retained between restarts. Close the application before copying the database for a backup. CSV export supports reporting but is not a complete database backup. Databases, SQLite sidecars, credentials, exports, and backups are excluded by `.gitignore`.

Two computers must visit the same running server to share the same tickets. Running a separate copy on each machine creates separate databases. Moving the original project to an always-on host was planned; this repository does not claim that deployment has been completed.

## Deployment limits

This is a private prototype using Basic authentication over HTTP. It defaults to localhost. It has no TLS, user roles, audit trail, login rate limiting, or CSRF token protection. Do not port-forward it or treat it as an internet-ready application. Network deployment requires a separate security review and an appropriately protected access path. Do not put device passwords or recovery keys into ticket notes.

## Validation

A temporary empty database and synthetic ticket are used to check authentication, ticket creation, persistence, and export. No real customer data is used in these checks.
