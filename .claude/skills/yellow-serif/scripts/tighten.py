"""Take the filler sounds and dead pauses out of a talk, keeping every real word in order. Shared by every edit skill
(yellow-serif, poster-kinetic, caption-card, neon-glow, sermon highlights): run it on the clip before planning.

usage: python tighten.py <clip> <out.mp4> [--pause 0.30] [--keep 0.12] [--keep-fillers] [--lang zh] [--map cutmap.json]
                         [--drop START-END ...]

What goes:
  fillers   um, uh, erm, er, ah, ahh, oh, ohh, hmm, mm and 嗯, 呃, 额, 唔, 呣; 啊 / 哦 / 噢 / 欸 / 诶 / 哎 only when they stand
            alone (a pause before them, or the clip's first sound), never as a sentence ending (好啊, 是哦 stay)
  pauses    any gap between kept words longer than --pause (s) shrinks to --keep (s), split around the cut, and a
            silence hidden inside a Chinese word Whisper held on to the next one (是…… 没有)
It never removes a real word. A second listen (tested on the 10/30 bilingual livestream, 2026-11-01) checks the first pass:
  - every filler it wrote is heard again with no prompt; real words there are kept (the prompt once turned 会觉得 into 呃)
  - every stretch the voice detector calls speech but no word covers (an interpreter's English under a Chinese sermon, a
    lone 好) is heard again on its own in any language: words are kept, a sound only a filler-leaning listen names is cut,
    an unnamed sound of 0.5 s or more is kept (`kept_unclear`); what it decided is in `second_listen`
  - a voiced sound held inside a word is never cut: it is usually the word drawn out (好快~~)
Possible false starts (the same words said twice within 4 s) are only listed in the report for you to check by ear;
delete the failed try with --drop START-END if it is one.

Speech-to-text: faster-whisper, the local large-v3-turbo model when it is there (env YS_WHISPER_MODEL to change), on the
CPU, temperature 0 with no conditioning on earlier text (the same result every run; with it, Whisper looped or dropped
whole minutes), and a prompt that asks it to write the filler sounds down. Writes <out>.mp4 (frame-exact cuts, 6 ms audio fades at
every join so nothing clicks) and <out>.cutmap.json ({"segments": [[src_start, src_end, cut_start], ...]}, the format
plan.py --map reads). Prints one JSON line.
"""
import argparse, os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from common import FFMPEG, audio, load, probe, report, save  # noqa: E402

FILL_ALWAYS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "ah", "ahh", "oh", "ohh", "hmm", "hm", "mm", "mmm",
               "嗯", "嗯嗯", "呃", "呃呃", "额", "唔", "呣"}
FILL_ALONE = {"啊", "哦", "噢", "欸", "诶", "哎", "喔"}       # a filler only when it stands alone
PROMPT = {"zh": "嗯，呃，以下是普通话的句子，使用简体中文。啊，", "yue": "嗯，呃，以下係廣東話。", None: "Um, uh, so, ah, I mean, hmm."}
HOT = {"zh": "嗯 呃", "yue": "嗯 呃", None: "um uh"}
LOCAL = "D:/AI OFFICE/tools/models/whisper-large-v3-turbo"
GHOSTS = {"thankyou", "thanks", "thankyouforwatching", "peace", "bye", "you", "yeah", "谢谢", "谢谢观看", "谢谢大家", "字幕",
          "ありがとうございました", "ご視聴ありがとうございました"}


def clean(w):
    return re.sub(r"[\s,.!?;:，。！？、；：…\"'“”]", "", w).lower()


def transcribe(path, lang):
    from faster_whisper import WhisperModel
    name = os.environ.get("YS_WHISPER_MODEL") or (LOCAL if os.path.isdir(LOCAL) else "small")
    model = WhisperModel(name, device="cpu", compute_type="int8")
    pcm = audio(path, 16000)
    # temperature 0 and no conditioning on the previous text: the same result every run, and no runaway loops (with
    # conditioning, a 90 s bilingual sermon came back as three words, or as "呃，呃，呃..." for 20 s)
    segs, info = model.transcribe(pcm, language=lang, initial_prompt=PROMPT.get(lang, PROMPT[None]), hotwords=HOT.get(lang, HOT[None]),
                                  temperature=0.0, condition_on_previous_text=False, word_timestamps=True, vad_filter=True,
                                  vad_parameters={"min_silence_duration_ms": 250}, beam_size=5)
    words = [{"t": w.word, "start": w.start, "end": w.end} for s in segs for w in (s.words or []) if w.word.strip()]
    out, i = [], 0                                           # a loop guard all the same: 4+ of the same sound in a row
    while i < len(words):
        j = i
        while j + 1 < len(words) and clean(words[j + 1]["t"]) == clean(words[i]["t"]):
            j += 1
        if j - i < 3 or not clean(words[i]["t"]):
            out += words[i:j + 1]
        i = j + 1
    return out, info.language, model, pcm


def second_listen(model, pcm, words, keep_fillers=False):
    """Speech the first pass did not write down (an interpreter's English under a Chinese sermon, a lone 好) must not be
    cut as a pause. Every stretch between words that the voice detector calls speech is transcribed again on its own, in
    any language: real words come back into `words`, filler-only sounds are cut, unclear sound of 0.5 s or more is kept."""
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    sr = 16000
    pad = np.zeros(sr // 2, np.float32)

    def listen(x, prompt):
        out, _ = model.transcribe(x, language=None, initial_prompt=prompt, vad_filter=False, beam_size=5, temperature=0.0,
                                  condition_on_previous_text=False)
        return "".join(s.text for s in out).strip()

    def is_filler(text):
        toks = [clean(t) for t in re.split(r"[\s,.!?;:，。！？、；：…�]+", text) if clean(t)]
        return bool(toks) and all(t in FILL_ALWAYS | FILL_ALONE or set(t) <= set("嗯呃额唔呣啊哦") for t in toks)

    log = []
    for w in words:                                          # the first pass's prompt can turn mumbled real words into 呃:
        if clean(w["t"]) in FILL_ALWAYS | FILL_ALONE:        # a filler is only one if a plain listen hears no real word
            x = np.concatenate([pad, pcm[int(max(0, w["start"] - 0.05) * sr):int((w["end"] + 0.05) * sr)], pad])
            plain = listen(x, None)
            if plain and not is_filler(plain) and not (w["end"] - w["start"] < 0.8 and clean(plain) in GHOSTS):
                log.append(f"{w['start']:.2f}-{w['end']:.2f}s not a filler: '{w['t'].strip()}' is '{plain[:40]}'")
                w["t"] = plain
    def loud(t0, t1):                                        # 20 ms loudness frames (dB)
        x = pcm[int(t0 * sr):int(t1 * sr)]; k = len(x) // 320
        return 20 * np.log10(np.sqrt((x[:k * 320].reshape(k, 320) ** 2).mean(1)) + 1e-9) if k else np.zeros(1) - 99

    tails = []                                               # "是…… 没有" / "好像…… 很": a pause hidden in a Chinese
    for w in words:                                          # word that Whisper held on to the next word
        c = clean(w["t"]); n = len(re.findall(r"[一-鿿]", c))
        if not n or n != len(c) or c in FILL_ALWAYS | FILL_ALONE:
            continue
        ok = w["start"] + 0.3 * n + 0.15
        if w["end"] - ok < 0.3:
            continue
        e, quiet = loud(ok, w["end"]), np.percentile(loud(w["start"], ok), 90) - 12
        k = len(e) - 1
        while k > 0 and e[k] > quiet:                        # back through the next word's onset: the cut stops before it
            k -= 1
        end = ok + (k + 1) * 0.02 - 0.06
        # only silence is cut: a voiced held sound is often the word itself drawn out (好快~~ sounds like 哦哦哦 on its own)
        if end - ok < 0.25 or np.percentile(e[:k + 1], 90) > quiet:
            continue
        tails.append({"t": "", "start": ok, "end": end, "filler": True}); w["end"] = ok
        log.append(f"{ok:.2f}-{end:.2f}s pause held inside '{c}'")
    words = sorted(words + tails, key=lambda w: w["start"])
    speech = [(d["start"] / sr, d["end"] / sr) for d in get_speech_timestamps(pcm, VadOptions(min_silence_duration_ms=200, speech_pad_ms=60))]
    cover = sorted((w["start"] - 0.05, w["end"] + 0.08) for w in words)
    spans = []                                               # speech outside every word, joined across short breaks
    for s0, s1 in speech:
        pieces = [(s0, s1)]
        for c0, c1 in cover:
            pieces = [q for p0, p1 in pieces for q in ((p0, min(p1, c0)), (max(p0, c1), p1)) if q[1] - q[0] > 0.01]
        for p0, p1 in pieces:                                # joined only when no written word lies between
            if spans and p0 - spans[-1][1] < 0.25 and not any(c1 > spans[-1][1] and c0 < p0 for c0, c1 in cover):
                spans[-1][1] = p1
            else:
                spans.append([p0, p1])
    rescued, unclear = [], []
    for s0, s1 in spans:
        if s1 - s0 < 0.15:
            continue
        x = np.concatenate([pad, pcm[int(s0 * sr):int(s1 * sr)], pad])
        text = listen(x, None)                               # a plain listen first: the filler prompt makes Whisper loop
        if s1 - s0 < 0.8 and clean(text) in GHOSTS:          # what Whisper writes on a breath or a click
            text = ""
        if not text:                                         # nothing named: ask again, leaning towards fillers
            hint = listen(x, "嗯，呃，啊。Um, uh.")
            text = hint if is_filler(hint) else ""
        verdict = "keep"
        if text and is_filler(text) and not keep_fillers:      # a cut of its own, even in a gap too short to count as a pause
            rescued.append({"t": text[:12], "start": s0, "end": s1, "filler": True})
            verdict = "cut filler"
        if verdict == "keep":
            if text or s1 - s0 >= 0.5:                       # the whole stretch is kept: its own word times are unreliable
                rescued.append({"t": text, "start": s0, "end": s1, "rescued": True})
                if not text:
                    unclear.append(f"{s0:.2f}-{s1:.2f}s"); verdict = "keep unclear"
            else:
                verdict = "cut noise"
        log.append(f"{s0:.2f}-{s1:.2f}s {verdict}: {text[:60]}")
    return sorted(words + rescued, key=lambda w: w["start"]), [w for w in rescued if w["t"] and not w.get("filler")], unclear, log


def voice_snap(words, pcm, sr=16000):
    """Whisper often starts a word 0.3-0.5 s before the voice (and ends it late), which hides a real pause: on Pong
    1101 a 0.69 s gap read as 0.2 s and stayed in. Move each word's start later / end earlier to where the voice really is
    (10 ms frames above the speech threshold), at most 0.5 s and never inside the word's own sound. Returns how many moved."""
    import numpy as np
    hop = sr // 100
    n = len(pcm) // hop
    if n < 10:
        return 0
    rms = 20 * np.log10(np.sqrt((np.asarray(pcm[:n * hop], np.float32).reshape(n, hop) ** 2).mean(1)) + 1e-9)
    thr = max(np.percentile(rms, 20) + 12, np.percentile(rms, 95) - 32)
    moved = 0
    for w in words:
        if not clean(w.get("t", "")):
            continue
        i0, i1 = int(w["start"] * 100), int(w["end"] * 100)
        if i1 - i0 < 6 or i0 >= n:
            continue
        if rms[i0:i0 + 3].max() < thr:                       # silent start: begin where the voice does
            hit = np.nonzero(rms[i0:min(i1 - 3, i0 + 50)] >= thr)[0]
            if len(hit):
                w["start"] = (i0 + int(hit[0])) / 100; moved += 1
        i0 = int(w["start"] * 100)
        if i1 <= n and rms[max(i0, i1 - 3):i1].max() < thr:  # silent tail: end where the voice does
            hit = np.nonzero(rms[max(i0 + 3, i1 - 50):i1] >= thr)[0]
            if len(hit):
                w["end"] = (max(i0 + 3, i1 - 50) + int(hit[-1]) + 1) / 100; moved += 1
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("out")
    ap.add_argument("--pause", type=float, default=0.30, help="gaps longer than this (s) are shortened")
    ap.add_argument("--keep", type=float, default=0.12, help="what is left of a shortened gap (s)")
    ap.add_argument("--tail", type=float, default=0.6, help="room tone kept after the last word (s); Pong+Gospel uses 1.5")
    ap.add_argument("--keep-fillers", action="store_true")
    ap.add_argument("--drop", action="append", default=[], metavar="START-END", help="also cut this source range (a false start)")
    ap.add_argument("--protect", action="append", default=[], metavar="START-END",
                    help="never cut a filler here (a drawn-out word end that reads as 'oh', checked by ear)")
    ap.add_argument("--lang", default=os.environ.get("YS_LANG") or None)
    ap.add_argument("--map", default=None, help="the clip's own cutmap.json (from cut_topics.py): the new map then gives source times")
    a = ap.parse_args()
    info = probe(a.clip); dur = info["duration"]; fps = info.get("fps") or 30
    words, lang, model, pcm = transcribe(a.clip, a.lang)
    words, rescued, unclear, listen_log = second_listen(model, pcm, words, a.keep_fillers)
    snapped = voice_snap(words, pcm)
    drops = [tuple(float(x) for x in d.split("-")) for d in a.drop]
    protect = [tuple(float(x) for x in d.split("-")) for d in a.protect]
    kept, fillers, cut = [], [], None
    for i, w in enumerate(words):
        c = clean(w["t"])
        gap_before = w["start"] - words[i - 1]["end"] if i else 9.0
        nxt = words[i + 1] if i + 1 < len(words) else None
        joined = nxt and clean(nxt["t"])[:1] in tuple("呀哟呦唷") and nxt["start"] - w["end"] < 0.15    # 哎呀, 哎哟: a real exclamation
        filler = w.get("filler") or c in FILL_ALWAYS or (c in FILL_ALONE and gap_before >= 0.18 and not joined)
        if filler and any(k0 <= (w["start"] + w["end"]) / 2 <= k1 for k0, k1 in protect):
            filler = False
        if (filler and not a.keep_fillers) or any(d0 <= (w["start"] + w["end"]) / 2 <= d1 for d0, d1 in drops):
            if filler and clean(w["t"]):
                fillers.append(f"{w['start']:.2f}s {w['t'].strip()}")
            cut = (cut[0] if cut else w["start"], w["end"])  # what was taken out since the last kept word
            continue
        if not c and not w.get("filler"):                    # punctuation only (":\"", "?"): not speech, and its time can
            continue                                          # span a silence and hide a real pause (Pong 1101: 0.58 s kept)
        kept.append(dict(w, cut=cut) if cut else w); cut = None
    if not kept:
        sys.exit("no speech found")
    # keep ranges: words padded (timestamps run a little early / late), joined unless the gap is a real pause or a
    # filler was taken out there (joining across it would put the filler back); a range never reaches into what was cut
    snap = lambda t: round(t * fps) / fps
    rng = []                                                 # [start, end, earliest start, latest end]
    for w in kept:
        s, e = max(0.0, w["start"] - 0.05), min(dur, w["end"] + 0.08)
        gone = w.get("cut")
        if rng and s - rng[-1][1] <= a.pause and not gone:
            rng[-1][1] = max(rng[-1][1], e)
        else:
            if rng and gone:                                  # 30 ms of slack: filler times are only roughly right
                rng[-1][3] = gone[0] + 0.03
            rng.append([s, e, gone[1] - 0.03 if gone else 0.0, dur])
    if cut:
        rng[-1][3] = cut[0] + 0.03
    half = a.keep / 2
    rng[0][0] = max(0.0, rng[0][0] - 0.10)
    rng[-1][1] = min(dur, rng[-1][1] + a.tail)              # a tail after the last word
    for r in rng[:-1]:
        r[1] = min(dur, r[1] + half)
    for r in rng[1:]:
        r[0] = max(0.0, r[0] - half)
    # next to a cut, a range reaches right up to it (Whisper's word times can be later than the sound's onset)
    rng = [[snap(lo if lo and s - lo <= a.pause else max(s, lo)), snap(hi if hi < dur and hi - e <= a.pause else min(e, hi))]
           for s, e, lo, hi in rng]
    rng = [r for r in rng if r[1] - r[0] >= 1 / fps]
    # repeated words close together: possible false starts, for the agent to check by ear
    false_starts = []
    txt = [(clean(w["t"]), w["start"]) for w in kept]
    for i in range(len(txt) - 3):
        a2 = "".join(x for x, _ in txt[i:i + 3])
        for j in range(i + 3, min(len(txt) - 2, i + 12)):
            if txt[j][1] - txt[i][1] > 4:
                break
            if len(a2) >= 3 and "".join(x for x, _ in txt[j:j + 3]) == a2:
                false_starts.append(f"{txt[i][1]:.2f}s and {txt[j][1]:.2f}s: '{a2}'")
                break
    # cut: one trim per range, 6 ms fades at every join, concatenated (filter script: no command-line limit)
    lines, cat = [], ""
    for k, (s, e) in enumerate(rng):
        d = e - s
        lines.append(f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS[v{k}];")
        lines.append(f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS,afade=t=in:d=0.006,afade=t=out:st={max(0, d - 0.006):.4f}:d=0.006[a{k}];")
        cat += f"[v{k}][a{k}]"
    lines.append(f"{cat}concat=n={len(rng)}:v=1:a=1[v][a]")
    fd, script = tempfile.mkstemp(suffix=".txt"); os.close(fd)
    with open(script, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", a.clip, "-/filter_complex", script, "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", a.out], capture_output=True, text=True)
    os.unlink(script)
    if p.returncode:
        sys.exit(p.stderr[-1500:])
    segs, c = [], 0.0
    for s, e in rng:
        segs.append([round(s, 3), round(e, 3), round(c, 3)]); c += e - s
    src = os.path.abspath(a.clip)
    if a.map:                                                # the clip was itself a cut: give times in its source
        prev = load(a.map); src = prev.get("source", src); out = []
        for s, e, c0 in segs:
            for p0, p1, q0 in prev["segments"]:
                lo, hi = max(s, q0), min(e, q0 + (p1 - p0))
                if hi - lo > 1e-3:
                    out.append([round(p0 + lo - q0, 3), round(p0 + hi - q0, 3), round(c0 + lo - s, 3)])
        segs = out
    cmap = os.path.splitext(a.out)[0] + ".cutmap.json"
    save(cmap, {"source": src, "segments": segs})
    report(tool="tighten", out=a.out, cutmap=cmap, language=lang, source_seconds=round(dur, 2), cut_seconds=round(c, 2),
           removed_seconds=round(dur - c, 2), joins=len(rng) - 1, fillers_removed=fillers,
           rescued=" ".join(w["t"].strip() for w in rescued)[:300], words_snapped_to_voice=snapped, kept_unclear=unclear, second_listen=listen_log[:40], possible_false_starts=false_starts[:10],
           transcript="".join(w["t"] for w in kept)[:600])


if __name__ == "__main__":
    main()
