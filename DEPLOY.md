# Deploying the tracker (for mods — no coding required)

Total time: about 10 minutes, all in a browser. You need one thing from
Telegram (a bot token) and one hosting account. Cost is roughly **$5–7/month**
— that's the floor for something that has to be online 24/7 and keep your
data through restarts.

## 1. Create the bot (2 minutes)

1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Give it a display name (e.g. *AppName Tracker*) and a username ending in
   `bot` (e.g. `AppNameTrackerBot`).
3. BotFather replies with a **token** that looks like
   `1234567890:AAF...xyz`. Copy it — this is the only secret you need.
   Treat it like a password.

## 2. Deploy (5 minutes)

**Render** (this repo includes its config):

1. Create an account at [render.com](https://render.com).
2. Go to `https://render.com/deploy?repo=<THIS-REPO-URL>`
   (or: New → Blueprint → paste the repo URL).
3. When prompted, paste the **BOT_TOKEN** from step 1.
4. Click deploy and wait for it to go green.

That's the whole configuration — one token. The app figures out its own
public URL, and there is no separate database to set up (everything lives on
the service's 1 GB disk).

**Railway** works too: New Project → Deploy from GitHub repo → add a
`BOT_TOKEN` variable → add a **volume** mounted at `/data` (Settings →
Volumes — without it, data is lost on redeploys).

## 3. Connect it to the group (2 minutes)

1. Add the bot to your community group.
2. When you're ready to go live, type **`/setgroup`** in the group. This
   **binds** the tracker to it: only that group's members can open the
   tracker, its admins get the triage controls, and completion
   announcements go there. Adding the bot to other groups does nothing.
3. Type `/feedback` in the group. The bot replies with an "Open the tracker"
   button — **pin that message** so it's always one tap away.

Until `/setgroup` is run, the tracker is in **test mode**: anyone with the
link can open it and file test items (handy for trying it out in a test
group first — the delete button cleans up afterwards). Don't leave it in
test mode longer than needed; bind it as part of going live.

Once bound: **group admins are automatically tracker admins** — anyone
who's an admin of the group can set priorities and statuses and delete
submissions; other group members can file ideas/bugs and vote; people
outside the group can't use the app at all. Promoting someone to group
admin makes them a tracker admin within ~5 minutes, no config anywhere.
Moving to a new group later: a current admin types `/setgroup` in the new
group.

## Optional polish: one-tap opening from the group

Out of the box, the group button takes two taps (it routes through the bot's
private chat, because Telegram doesn't allow instant-open app buttons inside
groups). To make it one tap:

1. In @BotFather: `/newapp` → choose your bot → set the **Web App URL** to
   your service's URL (shown in the Render/Railway dashboard, e.g.
   `https://feature-tracker.onrender.com`) → pick a short name like
   `tracker`.
2. BotFather gives you a link like `https://t.me/AppNameTrackerBot/tracker`.
   Add it as an environment variable on your service:
   `MINIAPP_LINK=https://t.me/AppNameTrackerBot/tracker`
3. Redeploy/restart, then run `/feedback` in the group again and re-pin.

## If something looks wrong

- **Button says "No public URL detected"** — the platform didn't inject its
  URL. Set `PUBLIC_URL=https://your-service-url` as an environment variable
  and restart.
- **Completions aren't announced in the group** — make sure the bot is still
  in the group, then type `/feedback` in the group once (that re-registers it).
- **Moving to a new group** — add the bot to the new group, then have a
  current admin type `/setgroup` there. (Anyone else adding the bot
  somewhere, or running `/setgroup` once it's bound, gets nothing — it
  stays bound to your community.)
- **Locked out — e.g. the bound group was deleted** — add an environment
  variable `RESET_KEY` (any long random string) on the service and restart,
  then send the bot a **private message**: `/unbind <that key>`. The
  tracker returns to unbound test mode; run `/setgroup` in the right group
  to bind it again. Setting `ADMIN_IDS=<your user id>` also always restores
  your own access, since env-listed admins bypass the membership gate.
- **Bot doesn't respond to commands at all** — check the service logs for a
  BOT_TOKEN error; re-paste the token from BotFather.
