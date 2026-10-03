import os, time
from openai import OpenAI

PROMPT = """You are a meeting notetaker for someone who missed (part of) this meeting.
From the transcript below write:
1. TL;DR (2-3 sentences)
2. Key discussion points (by topic, with who said what where it matters)
3. Decisions made
4. Action items (owner, task, deadline if mentioned)
5. Open questions / follow-ups
6. Anything said that mentions or concerns "{me}" directly
Captions are auto-generated and may mangle names or jargon; use context to correct obvious errors.
Be concise and factual; do not invent details.

Transcript:
{transcript}"""

# Sent while the meeting is still running, so the reader can decide whether to jump in.
CATCHUP_PROMPT = """You are a notetaker sending a mid-meeting catch-up to "{me}", who is NOT in this meeting
and may join later. The meeting is still in progress; the transcript so far is below. Write, very briefly:
- What is being discussed right now (1-2 sentences)
- Decisions so far
- Anything that needs "{me}"'s attention or input (questions to them, tasks for them, topics they own)
- Should {me} join now? (one line: yes/no + why)
Captions are auto-generated and may mangle names; use context. Be concise; do not invent details.

Transcript so far:
{transcript}"""

ASK_PROMPT = """Answer the question using only this meeting transcript. If the transcript doesn't say, say so.
Quote who said it where useful. Captions are auto-generated and may mangle names.

Question: {question}

Transcript:
{transcript}"""

RETRIES = 3


def _chat(prompt: str) -> str:
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        timeout=180,
    )
    model = os.environ.get("SUMMARY_MODEL", "apodex/apodex-1.1-mini:free")
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=8000,  # reasoning models spend part of this thinking
                messages=[{"role": "user", "content": prompt}],
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
            last = RuntimeError("model returned an empty reply")
        except Exception as e:  # rate limits / transient errors on the free tier
            last = e
        if attempt < RETRIES - 1:
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError(f"AI request failed after {RETRIES} attempts: {last}")


def summarize(transcript: str, me: str = "Mahi", kind: str = "final") -> str:
    prompt = CATCHUP_PROMPT if kind == "catchup" else PROMPT
    return _chat(prompt.format(me=me, transcript=transcript))


def ask(transcript: str, question: str) -> str:
    return _chat(ASK_PROMPT.format(question=question, transcript=transcript))
