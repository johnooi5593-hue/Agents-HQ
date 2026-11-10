"""Step 3 (host voice 3B): speak the voice script and lay it on the framed montage.

usage: python vo.py <framed.mp4> <script lines.json> <vo folder> <vo-video.mp4> [--reuse] [--eleven <voice id>]

Brand rule (owner 2026-11-03): host voice 3B = edge-tts zh-CN-XiaoyiNeural at +22 % rate, +25 Hz, +10 % volume, super
hype; talk TO the viewer in one connected, chatty Malaysian-style thread with particles (啦 / 咯 / 哦 / 咧 / 耶). Only
what is on screen is said, never a child's name. The script (template: ../templates/lines.json) is
{"voice": {...optional overrides...}, "lines": [{"t": 0.15, "text": "哇！头上戴的是什么啊？", "shot": "..."}, ...]}:
one line per shot, starting about 0.15 s after its cut (0.1-0.25 s), short enough to end before the next line.

Each line is spoken (edge-tts, online text-to-speech, needs the internet), its silence trimmed (-45 dB), and placed at
its time. A line is spoken again only when its text or the voice changed (<vo>/NN.txt keeps what NN.wav says);
--reuse keeps every NN.wav that exists. Writes <vo>/NN.mp3 / NN.wav, <vo>/vo.wav (the voice alone, 48 kHz stereo, the
length of the video), <vo>/lines.json ([{"t", "d", "text"}], read by makeplan.py) and <vo-video.mp4> (the picture
with the voice alone: no room sound, as in 1107). Warns when a line runs into the next one or into the last 0.4 s.

ElevenLabs (owner 2026-11-10): --eleven <voice id>, or "voice": {"engine": "elevenlabs", "id": "<voice id>", "model":
"eleven_multilingual_v2", "stability": 0.4, "style": 0.3, "speed": 1.1} in the script, speaks every line with that
ElevenLabs voice on the owner's key (app -> Accounts -> ElevenLabs; list voices: python tools/voice/eleven.py voices).
Each line is trimmed by ElevenLabs' own character times (not -45 dB) and lines.json gets each line's real "chars"
([[char, start, end]] from the line's start), which makeplan.py uses for the word times. With no key connected the
whole video falls back to host voice 3B and the output says so; when ElevenLabs refuses a line midway (credits used up)
it stops with the reason, so one video never mixes two voices. Lines already spoken are kept (each costs credits).
"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 4, "hq"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console

VOICE = {"name": "zh-CN-XiaoyiNeural", "rate": "+22%", "pitch": "+25Hz", "volume": "+10%"}


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout)


def main():
    args = sys.argv[1:]
    reuse = "--reuse" in args
    eleven_id = None
    if "--eleven" in args:
        i = args.index("--eleven")
        if i + 1 >= len(args):
            raise SystemExit("--eleven needs a voice id (python tools/voice/eleven.py voices)")
        eleven_id = args.pop(i + 1)
        args.pop(i)
    pos = [a for a in args if not a.startswith("--")]
    if len(pos) != 4:
        raise SystemExit(__doc__)
    video, script, vo, out = pos
    sc = json.load(open(script, encoding="utf-8"))
    voice = dict(VOICE, **(sc.get("voice") or {}))
    if eleven_id:
        voice.update(engine="elevenlabs", id=eleven_id)
    warn, el_key = [], False
    if voice.get("engine") == "elevenlabs":
        if not voice.get("id"):
            raise SystemExit('vo.py: "engine": "elevenlabs" needs "id": "<voice id>" (or --eleven <voice id>); '
                             "list them with: python tools/voice/eleven.py voices")
        import elevenlabs
        el_key = elevenlabs.has_key()
        if el_key:                                       # the ElevenLabs take depends on these only (edge-tts fields don't re-spend credits)
            voice = {k: voice[k] for k in ("engine", "id", "model", "stability", "similarity_boost", "style", "speed") if k in voice}
        else:
            warn.append("no ElevenLabs key connected (app -> Accounts -> ElevenLabs): the whole video uses host voice 3B")
            voice = dict(VOICE, **{k: v for k, v in (sc.get("voice") or {}).items() if k in VOICE})
    os.makedirs(vo, exist_ok=True)
    clips, spoken = [], 0
    for i, ln in enumerate(sc["lines"]):
        t, text = float(ln["t"]), ln["text"]
        raw, cut, key, ctimes = (os.path.join(vo, f"{i:02d}.{e}") for e in ("mp3", "wav", "txt", "chars.json"))
        sig = json.dumps([text, voice], ensure_ascii=False)
        same = os.path.isfile(cut) and (reuse or (os.path.isfile(key) and open(key, encoding="utf-8").read() == sig))
        if same and el_key and not os.path.isfile(ctimes):
            same = False                                 # --reuse never keeps a 3B take in an ElevenLabs video
        if not same and el_key:
            settings = {k: voice[k] for k in ("stability", "similarity_boost", "style", "speed") if k in voice}
            try:
                chars = elevenlabs.speak(text, voice["id"], raw, model=voice.get("model") or elevenlabs.MODEL,
                                         settings=settings or None)
            except elevenlabs.ElevenError as e:
                kept = f"Lines 1-{i} are kept; run again to go on." if i else "Nothing was spoken."
                raise SystemExit(f"vo.py: ElevenLabs stopped at line {i + 1} ({text}): {e} {kept}")
            with open(raw + ".chars.json", "w", encoding="utf-8") as f:   # the paid take's own times, before any trim
                json.dump(chars, f, ensure_ascii=False)
            said = [c for c in chars if c[0].strip()]
            a = max(0.0, said[0][1] - 0.03) if said else 0.0
            # start by ElevenLabs' first character, end by the silence (a drawn-out 啦 / 哦 often outlasts its end time)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", f"asetpts=PTS-STARTPTS,atrim=start={a:.3f},asetpts=PTS-STARTPTS,"
                            "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse", "-ar", "48000", "-ac", "2", cut], check=True)
            with open(ctimes, "w", encoding="utf-8") as f:
                json.dump([[c, round(s - a, 3), round(e - a, 3)] for c, s, e in said], f, ensure_ascii=False)
            open(key, "w", encoding="utf-8").write(sig); spoken += 1
        elif not same:
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice["name"], f"--rate={voice['rate']}",
                            f"--pitch={voice['pitch']}", f"--volume={voice['volume']}", "--text", text, "--write-media", raw],
                           check=True, capture_output=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                            "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse", "-ar", "48000", "-ac", "2", cut],
                           check=True)
            if os.path.isfile(ctimes):
                os.replace(ctimes, ctimes + ".old")      # those times belong to an ElevenLabs take, not this one
            open(key, "w", encoding="utf-8").write(sig); spoken += 1
        chars = None
        if el_key and os.path.isfile(ctimes):
            with open(ctimes, encoding="utf-8") as f:
                chars = json.load(f)
        clips.append((t, cut, dur(cut), text, chars))
    warn += [f"line {i + 1}: ends {t + d:.2f}s, next starts {clips[i + 1][0]:.2f}s" for i, (t, _, d, _, _) in enumerate(clips[:-1])
             if t + d > clips[i + 1][0] - 0.1]
    total = dur(video)
    if clips[-1][0] + clips[-1][2] > total - 0.4:
        warn.append(f"last line ends {clips[-1][0] + clips[-1][2]:.2f}s, video ends {total:.2f}s (clean ending needs 0.4 s of tail)")
    live = [c for c in clips if c[0] < total]
    args2, parts = ["ffmpeg", "-y", "-v", "error"], []
    for i, (t, cut, _, _, _) in enumerate(live):
        args2 += ["-i", cut]; ms = int(round(t * 1000))
        parts.append(f"[{i}:a]adelay={ms}|{ms}[v{i}]")
    n = len(live)
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + \
        f"amix=inputs={n}:duration=longest:normalize=0,apad,atrim=0:{total:.3f}[a]"
    wav = os.path.join(vo, "vo.wav")
    subprocess.run(args2 + ["-filter_complex", graph, "-map", "[a]", "-ar", "48000", "-ac", "2", wav], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", out], check=True)
    lines = [dict({"t": t, "d": round(d, 3), "text": x}, **({"chars": ch} if ch else {})) for t, _, d, x, ch in clips]
    json.dump(lines, open(os.path.join(vo, "lines.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    used = "elevenlabs:" + voice["id"] if el_key else voice["name"]
    print(json.dumps({"out": out, "wav": wav, "voice": used, "spoken": spoken, "reused": len(clips) - spoken, "placed": n,
                      "lines": [(t, round(d, 2), x) for t, _, d, x, _ in clips], "warnings": warn}, ensure_ascii=False))


if __name__ == "__main__":
    main()
