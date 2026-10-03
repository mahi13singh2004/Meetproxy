import argparse, asyncio, os, re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
from .bot import login, run_meeting
from .summarize import summarize, ask
from .watch import Watcher
from .mailer import send_mail


def deliver(transcript: str, stamp: str, label: str, me: str, source: str):
    """Summarize + email. A failure here never loses the transcript (already on disk)."""
    out = Path("transcripts")
    if not transcript.strip():
        send_mail("Meeting notes: no transcript captured",
                  f"The bot attended {source} but captured no captions. Were captions available?")
        print("No captions captured; emailed a notice.")
        return
    try:
        notes = summarize(transcript, me)
        (out / f"{stamp}-summary.md").write_text(notes, encoding="utf-8")
    except Exception as e:
        print(f"Summary failed: {e}")
        notes = f"(AI summary failed: {e})\nThe full transcript is attached."
    send_mail(f"Meeting notes {stamp} ({label})", notes, (f"transcript-{stamp}.txt", transcript))
    print("Notes emailed.")


def main():
    ap = argparse.ArgumentParser(prog="meetproxy")
    ap.add_argument("target", help="Meet link | 'login' | saved transcript .txt to re-summarize | "
                                   "'ask' (then: transcript.txt \"question\")")
    ap.add_argument("rest", nargs="*", help=argparse.SUPPRESS)
    ap.add_argument("--names", help="comma-separated names that trigger a mention alert (default: --me)")
    ap.add_argument("--digest-minutes", type=int, default=0,
                    help="email a catch-up summary every N minutes while the meeting runs (0 = off)")
    ap.add_argument("--no-alerts", action="store_true", help="disable instant mention alerts")
    ap.add_argument("--max-minutes", type=int, default=180)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--me", default="Mahi")
    a = ap.parse_args()

    if a.target == "login":
        return asyncio.run(login())

    if a.target == "ask":
        if len(a.rest) < 2:
            ap.error('usage: meetproxy ask transcripts/file.txt "your question"')
        print(ask(Path(a.rest[0]).read_text(encoding="utf-8"), " ".join(a.rest[1:])))
        return

    out = Path("transcripts")
    out.mkdir(exist_ok=True)

    if Path(a.target).is_file():  # re-run summary on a saved transcript
        path = Path(a.target)
        return deliver(path.read_text(encoding="utf-8"), path.stem, path.stem, a.me, str(path))

    code = re.search(r"[a-z]{3}-[a-z]{4}-[a-z]{3}", a.target)
    label = code.group(0) if code else "Meet"
    watcher = Watcher(label, a.me, (a.names or a.me).split(","), a.digest_minutes, not a.no_alerts)
    try:
        transcript = asyncio.run(run_meeting(a.target, os.environ.get("BOT_NAME", "Notetaker"),
                                             a.max_minutes, a.headless, monitor=watcher.update))
    finally:
        watcher.close()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    (out / f"{stamp}.txt").write_text(transcript, encoding="utf-8")  # saved before anything can fail
    deliver(transcript, stamp, label, a.me, a.target)


main()
