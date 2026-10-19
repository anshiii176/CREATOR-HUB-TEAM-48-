# Find Your Care — MVP

Flask + SQLite + vanilla JS app connecting families to verified, non-medical
hospital caretakers.

## Run locally

```bash
pip install flask
python app.py
```

Open http://127.0.0.1:5000/ — any username/password logs you in; pick
"Hirer" or "Employee" on the login screen. `findyourcare.db` is created
and seeded automatically on first run.

## Deploy to the web

The dev server (`app.run(debug=True)`) is not production-safe. Use a real
WSGI server behind a host. Two easy free/cheap options:

### Option A — Render.com (simplest)
1. Push this folder to a GitHub repo.
2. Add a `requirements.txt` with:
   ```
   flask
   gunicorn
   ```
3. On Render: New → Web Service → connect the repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
4. Render builds and gives you a public HTTPS URL.
   Note: Render's free disk is ephemeral, so the SQLite file resets on
   redeploy — fine for a hackathon demo, not for real user data.

### Option B — Railway.app
1. Push to GitHub, same `requirements.txt` as above.
2. New Project → Deploy from GitHub repo.
3. Railway auto-detects Python; set the start command to `gunicorn app:app`.
4. Add a persistent volume mounted at the project folder if you want the
   SQLite file to survive restarts.

### Before going live, change:
- `app.secret_key` in `app.py` — replace the placeholder with a real
  random secret (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`)
  and load it from an environment variable, not hardcoded.
- Real authentication — the current login accepts any username/password
  by design (hackathon simplification).
- SQLite → Postgres if you need concurrent writes at scale beyond a demo.
