# tools/voice

`eleven.py` speaks voice-over lines with the owner's ElevenLabs voices (2026-11-10).

- **Key:** the owner pastes it in the app: user menu → Accounts → ElevenLabs. It is saved in `.hq-elevenlabs.json`
  (git-ignored, denied to agents in `.claude/settings.json`) or comes from `ELEVENLABS_API_KEY`. Never read or print it.
- `python tools/voice/eleven.py status`: connected or not, voices, credits (never the key).
- `python tools/voice/eleven.py voices`: the voice ids, the owner's own clones first.
- `python tools/voice/eleven.py say <voice id> out.mp3 "text" --times times.json`: one line plus its real character times.
- The kids-review voice-over step uses it with `vo.py --eleven <voice id>`.
- Every line costs ElevenLabs credits. Speak once and keep the files; exit 1 means ElevenLabs refused (the reason is
  printed, e.g. credits used up), exit 2 means no key is connected.
- Code: `hq/elevenlabs.py` (shared with the app's Accounts screen), tests `hq/tests/test_elevenlabs.py`.
