"""Joins a Google Meet, scrapes live captions into a transcript, returns it when the call ends."""
import asyncio, re, time
from pathlib import Path
from playwright.async_api import async_playwright, Page

PROFILE = Path(__file__).parent.parent / "profile"

# Polls the captions region and records finished utterances. Meet's DOM is undocumented
# and changes; if captions stop being captured, this is the place to fix.
CAPTION_JS = r"""
() => {
  if (window.__mp) return;
  const log = window.__mp = { lines: [], last: {} };
  setInterval(() => {
    const region = document.querySelector('[role="region"][aria-label*="aption" i]');
    if (!region) return;
    region.querySelectorAll(':scope > div').forEach((blk, i) => {
      const parts = blk.innerText.split('\n').map(s => s.trim()).filter(Boolean);
      if (parts.length < 2) return;
      const speaker = parts[0], text = parts.slice(1).join(' ');
      const key = speaker + '#' + i;
      const prev = log.last[key];
      if (prev && prev.text && !text.startsWith(prev.text.slice(0, 15)))
        log.lines.push(prev.speaker + ': ' + prev.text);
      log.last[key] = { speaker, text, t: Date.now() };
    });
    // flush utterances that stopped growing
    for (const [k, v] of Object.entries(log.last))
      if (Date.now() - v.t > 4000) { log.lines.push(v.speaker + ': ' + v.text); delete log.last[k]; }
  }, 700);
}
"""

FLUSH_JS = """() => { const l = window.__mp; if (!l) return [];
  for (const v of Object.values(l.last)) l.lines.push(v.speaker + ': ' + v.text);
  return l.lines; }"""


async def _launch(p, headless=False, extra_args=()):
    """Edge without Playwright's automation flags, so Google lets you sign in."""
    return await p.chromium.launch_persistent_context(
        str(PROFILE), channel="msedge", headless=headless, no_viewport=True,
        ignore_default_args=["--enable-automation", "--no-sandbox"],
        args=[*extra_args],
    )


async def login():
    """One-time: opens a browser so you can sign in to the Google account the bot will use."""
    async with async_playwright() as p:
        ctx = await _launch(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://accounts.google.com")
        input("Sign in in the browser window, then press Enter here...")
        await ctx.close()


async def _click_first(page: Page, labels: list[str], timeout=3000) -> bool:
    for l in labels:
        try:
            await page.get_by_role("button", name=l).first.click(timeout=timeout)
            return True
        except Exception:
            pass
    return False


async def _in_call(page: Page) -> bool:
    # Meet auto-hides the control bar when idle, so also accept other in-call-only elements
    return await page.locator(
        '[aria-label*="Leave call" i], button:has-text("call_end"), '
        '[role="region"][aria-label="Call controls"], [role="region"][aria-label*="aption" i]'
    ).count() > 0


async def _ended(page: Page) -> bool:
    """True only when Meet shows a post-call screen (left, removed, ended, rejoin)."""
    if "meet.google.com" not in page.url or page.url.rstrip("/").endswith("meet.google.com"):
        return True
    return await page.get_by_text(
        re.compile(r"You left the meeting|You.ve been removed|The meeting has ended|"
                   r"Return to home screen|Rejoin", re.I)).count() > 0


async def run_meeting(url: str, bot_name: str, max_minutes: int = 180, headless=False, monitor=None) -> str:
    async with async_playwright() as p:
        ctx = await _launch(
            p, headless, ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=90000)
        await _click_first(page, ["Got it", "Dismiss"], 1500)
        # wait up to 30s for either the in-call UI or a join button (page load speed varies)
        for _ in range(15):
            if await _in_call(page) or await page.get_by_role(
                    "button", name=re.compile(r"Join now|Ask to join|Switch here", re.I)).count():
                break
            await page.wait_for_timeout(2000)

        if await _in_call(page):
            print("Already in the call; skipping join.")
        else:
            await _join(page, bot_name)

        deadline = time.time() + 600
        while not await _in_call(page):
            if time.time() > deadline:
                raise RuntimeError("Never admitted to the meeting")
            await page.wait_for_timeout(2000)
        print("In the call. Enabling captions.")

        await page.wait_for_timeout(2000)
        if not await _click_first(page, ["Turn on captions"], 3000):
            if not await page.get_by_role("button", name="Turn off captions").count():
                await page.keyboard.press("c")  # captions neither clickable nor on: try shortcut
        await page.evaluate(CAPTION_JS)
        return await _record(ctx, page, max_minutes, monitor)


async def _join(page: Page, bot_name: str):
    # guest (not signed in) path asks for a name
    name_box = page.get_by_placeholder("Your name")
    if await name_box.count():
        await name_box.fill(bot_name)

    # mic/cam off
    await _click_first(page, ["Turn off microphone"], 1500)
    await _click_first(page, ["Turn off camera"], 1500)

    if not await _click_first(page, ["Join now", "Ask to join", "Join", "Switch here"], 8000):
        shot = Path(__file__).parent.parent / "debug-join.png"
        await page.screenshot(path=str(shot))
        names = await page.eval_on_selector_all(
            "button,[role=button]", "els => els.map(e => (e.innerText || e.ariaLabel || '').trim()).filter(Boolean)")
        print(f"URL: {page.url}\nTitle: {await page.title()}\nButtons: {names}\nScreenshot: {shot}")
        raise RuntimeError("Could not find Join button (is the link valid / are you signed in?)")
    print("Requested to join; waiting to be admitted (up to 10 min)...")


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", t.lower())


def clean_transcript(lines: list[str]) -> list[str]:
    """Meet revises captions as it hears more, so drop earlier partials of the same utterance."""
    out: list[tuple[str, str]] = []
    for ln in lines:
        speaker, _, text = ln.partition(": ")
        if not text.strip():
            continue
        if out and out[-1][0] == speaker:
            a, b = _words(out[-1][1]), _words(text)
            if b[:len(a)] == a:        # new line extends the previous one
                out[-1] = (speaker, text)
                continue
            if a[:len(b)] == b:        # new line is a shorter repeat
                continue
        out.append((speaker, text))
    return [f"{sp}: {tx}" for sp, tx in out]


REGION_JS = r"""() => {
  const rs = [...document.querySelectorAll('[role="region"][aria-label*="aption" i]')].map(r =>
    ({ label: r.getAttribute('aria-label'), text: r.innerText.slice(0, 500), html: r.outerHTML.slice(0, 3000) }));
  return JSON.stringify(rs, null, 1);
}"""


async def _record(ctx, page: Page, max_minutes: int, monitor=None) -> str:
    end = time.time() + max_minutes * 60
    misses, ticks, reason = 0, 0, "time limit reached"
    lines: list[str] = []  # copied out of the page each tick so closing the window loses nothing
    dumps = 0
    while time.time() < end:
        try:
            await page.wait_for_timeout(5000)
            ticks += 1
            await page.mouse.move(400 + ticks % 50, 400)  # keep Meet's control bar from auto-hiding
            misses = misses + 1 if await _ended(page) else 0
            if misses >= 2:
                reason = "meeting ended or bot was removed"
                break
            await page.evaluate(CAPTION_JS)  # no-op if already installed
            lines = await page.evaluate("() => window.__mp ? window.__mp.lines.slice() : []")
            if monitor:
                try:
                    monitor(lines)
                except Exception as e:  # alerts must never break recording
                    print(f"monitor error: {e}")
            if ticks % 6 == 0:
                print(f"[{ticks * 5}s] lines captured: {len(lines)}")
                if not lines and dumps < 3:
                    dumps += 1
                    print("Nothing parsed yet. Captions area (send me this):\n" + await page.evaluate(REGION_JS))
        except asyncio.CancelledError:  # Ctrl+C: stop recording but still return what we have
            reason = "stopped by Ctrl+C"
            break
        except Exception as e:
            reason = f"browser/page closed or error: {type(e).__name__}"
            break
    print(f"Stopped recording: {reason}")

    try:
        lines = await page.evaluate(FLUSH_JS)
    except BaseException:
        pass  # keep what we copied earlier
    try:
        await ctx.close()
    except BaseException:
        pass
    return "\n".join(lines)
