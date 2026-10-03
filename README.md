# MeetProxy
Joins a Google Meet for you, captures live captions, and emails an AI summary + full transcript when the call ends.

## Setup
    python -m venv .venv && .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    playwright install msedge        # uses Microsoft Edge (preinstalled on Windows 11)
    copy .env.example .env           # then fill in the keys below

`.env`:
- `OPENROUTER_API_KEY` – free key from https://openrouter.ai/keys (`SUMMARY_MODEL` defaults to a free model)
- `SMTP_USER` / `SMTP_PASSWORD` – Gmail + an App Password (https://myaccount.google.com/apppasswords, needs 2FA; paste it without spaces)
- `MAIL_TO`, `BOT_NAME`

### Google sign-in (one time)
Google blocks sign-in inside automated browsers, so sign in with a normal Edge window that uses the bot's profile folder, then close it:

    & "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --user-data-dir="$PWD\profile" https://accounts.google.com

Use a separate Google account for the bot. Without signing in, the bot joins as a guest (works for personal Meets, not for most company ones).

## Use
    python -m meetproxy https://meet.google.com/xxx-xxxx-xxx
    python -m meetproxy https://meet.google.com/xxx-xxxx-xxx --max-minutes 60 --me "Mahi"
    python -m meetproxy transcripts\20261004-0025.txt     # re-summarize + email a saved transcript

The host must admit the bot. The bot stops when the meeting ends, at `--max-minutes`, or on Ctrl+C (it still saves and emails what it captured).

Output: `transcripts/<stamp>.txt` (raw transcript) and `transcripts/<stamp>-summary.md`, plus the email.

## For when you're not attending
- **Mention alerts** (on by default): when someone says your name, you get an email within seconds with the last few lines for context. Mentions close together are batched. `--names "Mahi,Mahi Singh"` sets which names count (default: `--me`); `--no-alerts` turns it off.
- **Phone push** (optional, free): set `NTFY_TOPIC=<a-long-random-string>` in `.env`, install the ntfy app and subscribe to that topic. Alerts then also arrive as a push notification.
- **Catch-up digests**: `--digest-minutes 15` emails a short "what's happening, what needs you, should you join now?" every 15 minutes while the meeting runs.
- **Ask the meeting**: `python -m meetproxy ask <transcript.txt> "question"` answers from the transcript only.

## Notes
- Uses Meet's built-in captions (free, no audio capture): turn-by-turn text with speaker names. Only speech that Meet captions will be recorded; the bot's own mic is off.
- If the AI summary fails (rate limit etc.) the transcript is still emailed and the summary can be retried with the re-summarize command above.
- Caption DOM selectors live in `meetproxy/bot.py` and may need tweaks if Google changes the Meet UI. If nothing is captured the bot prints the captions area's HTML to help debug.
- Tell participants a notetaker is present.
- Next: calendar auto-join, then voice replies.
