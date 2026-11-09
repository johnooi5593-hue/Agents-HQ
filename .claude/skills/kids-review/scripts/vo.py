"""Step 3 (host voice 3B): speak the voice script and lay it on the framed montage.

usage: python vo.py <framed.mp4> <script lines.json> <vo folder> <vo-video.mp4> [--reuse]

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
"""
import json, os, subprocess, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console

VOICE = {"name": "zh-CN-XiaoyiNeural", "rate": "+22%", "pitch": "+25Hz", "volume": "+10%"}


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout)


def main():
    args = sys.argv[1:]
    reuse = "--reuse" in args
    pos = [a for a in args if not a.startswith("--")]
    if len(pos) != 4:
        raise SystemExit(__doc__)
    video, script, vo, out = pos
    sc = json.load(open(script, encoding="utf-8"))
    voice = dict(VOICE, **(sc.get("voice") or {}))
    os.makedirs(vo, exist_ok=True)
    clips, spoken = [], 0
    for i, ln in enumerate(sc["lines"]):
        t, text = float(ln["t"]), ln["text"]
        raw, cut, key = (os.path.join(vo, f"{i:02d}.{e}") for e in ("mp3", "wav", "txt"))
        sig = json.dumps([text, voice], ensure_ascii=False)
        same = os.path.isfile(cut) and (reuse or (os.path.isfile(key) and open(key, encoding="utf-8").read() == sig))
        if not same:
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice["name"], f"--rate={voice['rate']}",
                            f"--pitch={voice['pitch']}", f"--volume={voice['volume']}", "--text", text, "--write-media", raw],
                           check=True, capture_output=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                            "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse", "-ar", "48000", "-ac", "2", cut],
                           check=True)
            open(key, "w", encoding="utf-8").write(sig); spoken += 1
        clips.append((t, cut, dur(cut), text))
    warn = [f"line {i + 1}: ends {t + d:.2f}s, next starts {clips[i + 1][0]:.2f}s" for i, (t, _, d, _) in enumerate(clips[:-1])
            if t + d > clips[i + 1][0] - 0.1]
    total = dur(video)
    if clips[-1][0] + clips[-1][2] > total - 0.4:
        warn.append(f"last line ends {clips[-1][0] + clips[-1][2]:.2f}s, video ends {total:.2f}s (clean ending needs 0.4 s of tail)")
    live = [c for c in clips if c[0] < total]
    args2, parts = ["ffmpeg", "-y", "-v", "error"], []
    for i, (t, cut, _, _) in enumerate(live):
        args2 += ["-i", cut]; ms = int(round(t * 1000))
        parts.append(f"[{i}:a]adelay={ms}|{ms}[v{i}]")
    n = len(live)
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + \
        f"amix=inputs={n}:duration=longest:normalize=0,apad,atrim=0:{total:.3f}[a]"
    wav = os.path.join(vo, "vo.wav")
    subprocess.run(args2 + ["-filter_complex", graph, "-map", "[a]", "-ar", "48000", "-ac", "2", wav], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", out], check=True)
    lines = [{"t": t, "d": round(d, 3), "text": x} for t, _, d, x in clips]
    json.dump(lines, open(os.path.join(vo, "lines.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"out": out, "wav": wav, "spoken": spoken, "reused": len(clips) - spoken, "placed": n,
                      "lines": [(t, round(d, 2), x) for t, _, d, x in clips], "warnings": warn}, ensure_ascii=False))


if __name__ == "__main__":
    main()
