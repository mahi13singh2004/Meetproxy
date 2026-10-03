"""Live monitoring while the bot is in the meeting: mention alerts and periodic catch-up digests."""
import os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

from .bot import clean_transcript
from .mailer import send_mail
from .summarize import summarize

ALERT_COOLDOWN = 60  # seconds; mentions inside the window are batched into the next alert


def push(title: str, body: str):
    """Optional free phone push via ntfy.sh: set NTFY_TOPIC to a hard-to-guess topic and subscribe in the ntfy app."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                                 headers={"Title": title, "Priority": "high"})
    urllib.request.urlopen(req, timeout=15).close()


class Watcher:
    def __init__(self, label: str, me: str, names: list[str], digest_minutes: int = 0, alerts: bool = True):
        self.label, self.me = label, me
        names = [n.strip() for n in names if n.strip()]
        self.pat = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.I) if names else None
        self.alerts = alerts and self.pat is not None
        self.digest_every = digest_minutes * 60
        self.seen = 0            # index into the raw line list already scanned for mentions
        self.digest_seen = 0     # number of lines covered by the last digest
        self.last_alert = 0.0
        self.last_digest = time.time()
        self.pending: list[str] = []
        self.ctx_end = -1        # last line already shown as context in an alert
        self.digest_busy = False
        self.pool = ThreadPoolExecutor(max_workers=2)

    def update(self, lines: list[str]):
        """Called by the recorder every few seconds with all raw caption lines so far."""
        now = time.time()
        if self.alerts:
            for i in range(self.seen, len(lines)):
                speaker, _, text = lines[i].partition(": ")
                if self.pat.search(text) and not self.pat.search(speaker):  # ignore your own speech
                    ctx = clean_transcript(lines[max(0, i - 4): i + 1])
                    self.pending.append("\n".join(ctx))
            self.seen = len(lines)
            if self.pending and now - self.last_alert >= ALERT_COOLDOWN:
                batch, self.pending, self.last_alert = self.pending, [], now
                self.pool.submit(self._alert, batch)
        if (self.digest_every and not self.digest_busy and now - self.last_digest >= self.digest_every
                and len(lines) > self.digest_seen):
            self.digest_busy = True
            snapshot = list(lines)
            self.pool.submit(self._digest, snapshot)

    def _alert(self, batch: list[str]):
        try:
            body = f"You were mentioned in {self.label}:\n\n" + "\n\n---\n\n".join(batch)
            send_mail(f"Mentioned in meeting ({self.label})", body)
            push(f"Mentioned in {self.label}", batch[-1])
            print("Mention alert sent.")
        except Exception as e:
            print(f"Mention alert failed: {e}")

    def _digest(self, snapshot: list[str]):
        try:
            notes = summarize("\n".join(clean_transcript(snapshot)), self.me, kind="catchup")
            send_mail(f"Meeting catch-up ({self.label}) at {time.strftime('%H:%M')}", notes)
            self.digest_seen = len(snapshot)
            print("Catch-up digest sent.")
        except Exception as e:
            print(f"Catch-up digest failed: {e}")
        finally:
            self.last_digest = time.time()
            self.digest_busy = False

    def close(self):
        """Send any mentions still waiting out the cooldown, then wait for in-flight work."""
        if self.pending:
            batch, self.pending = self.pending, []
            self.pool.submit(self._alert, batch)
        self.pool.shutdown(wait=True)
