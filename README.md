# Community Feature Tracker (Telegram Mini App)

A tracker that lives inside a Telegram group chat: members file feature ideas
and bug reports (title, details, screenshots) and vote on them; the group's
admins sort them by priority and status; the bot announces in the group when
something ships. No accounts, no logins — Telegram's signed `initData`
identifies everyone automatically.

```
Group chat ──pinned /app button──▶ Mini App (this server's web page)
                                     │  submit ideas & bugs, vote
                                     │  group admins: status & priority
                                     ▼
                                 FastAPI + SQLite
                                     │  status → completed
                                     ▼
Group chat ◀── "✅ Shipped: Dark mode (#14)" ── aiogram bot
```

One Python process runs everything: the web app, its API, and the bot.

## Deploying

**See [DEPLOY.md](DEPLOY.md)** — written so a non-developer mod can do it in
a browser in ~10 minutes. The short version: create a bot with @BotFather,
deploy this repo to Render/Railway with `BOT_TOKEN` as the only variable,
add the bot to the group, type `/setgroup` then `/feedback`, pin the message.

Everything else is automatic:

- **Public URL** — detected from the platform (Render/Railway/Fly), or set
  `PUBLIC_URL` manually.
- **Transport** — webhook when a public URL is known, long polling otherwise.
- **Community binding** — `/setgroup` in a group locks the tracker to it:
  only that group's members can open the app (verified live via
  `getChatMember`), announcements go there, and other groups get nothing.
  Until `/setgroup` is run the app is open (test mode). Rebinding once
  bound requires a current admin.
- **Admins** — the bound group's own admin list, fetched live and cached
  5 min. `ADMIN_IDS` adds extras.

The Docker image keeps all state (SQLite DB + screenshots) under `/data` —
mount a persistent volume there and that's the entire backup surface.

## Layout

```
app/
  main.py        entrypoint — FastAPI app, webhook/polling selection
  api.py         REST API used by the Mini App
  bot.py         bot commands, group capture, admin resolution, announcements
  auth.py        Telegram initData signature verification
  db.py          SQLite schema and queries
  config.py      settings (only BOT_TOKEN required)
  static/        the Mini App (vanilla HTML/CSS/JS)
scripts/
  smoke_test.py  end-to-end test, no Telegram needed
Dockerfile       runs anywhere containers run
render.yaml      Render blueprint (one-click deploy config)
DEPLOY.md        the guide to hand to whoever deploys it
```

## How it's used

- **Members** open the tracker from the pinned button, file ideas or bugs
  (title, details, up to 4 screenshots), and upvote what they care about.
- **Group admins** see extra controls on each item: status (Open / Planned /
  In progress / Completed / Declined), priority (Low → Critical), and
  delete. Unsorted items are flagged so the triage backlog is visible.
- **Non-members** of the bound group can't use the app at all.
- Marking something **Completed** posts an announcement to the group with a
  button back into the tracker — "🐞 Fixed" for bugs, "✅ Shipped" for ideas.
- The board groups active items as In progress / Planned / Open, sorted by
  votes — so it doubles as a public roadmap.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # paste your BOT_TOKEN
uvicorn app.main:app --port 8080
```

- **UI work in a normal browser:** set `DEV_USER_ID=<your telegram id>` in
  `.env` and open http://localhost:8080 — bypasses Telegram signatures
  (never set it in production).
- **Full in-Telegram testing:** tunnel the port
  (`cloudflared tunnel --url http://localhost:8080` or `ngrok http 8080`),
  set the HTTPS URL as `PUBLIC_URL` in `.env`, restart (the bot switches to
  webhook through the tunnel), and point a test bot's `/newapp` URL at it.
- **Sanity check:** `python scripts/smoke_test.py` exercises the full API —
  signed auth, tampered-signature rejection, uploads, voting, admin gating,
  webhook secret enforcement — without needing Telegram at all.

## Notes & easy extensions

- Screenshot URLs are unguessable (random UUIDs) but publicly served; fine
  for community screenshots, not for secrets.
- The bot has privacy mode on by default and never reads group messages —
  everything flows through the Mini App.
- Natural next steps, all small: announce new submissions to the group
  (visibility vs. noise trade-off), comments on submissions, or creating a
  GitHub Issue per submission and syncing status back so devs never leave
  their existing workflow.
