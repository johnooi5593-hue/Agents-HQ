"""Step 6b (whole words): merge a plan's per-character word timings into whole words, so a caption card never breaks
inside a word (brand check 1107: 蒙古|包, 帮|忙). Rewrites the plan in place and keeps <plan>.before-regroup.json.

usage: python regroup_words.py <plan.json> [--script lines.json]

Where each line's words come from, first match wins:
  1. "seg" of the same line in the voice script (--script): the words separated by spaces, e.g. "先来 听故事咯".
     Particles stay with their phrase (听故事咯, 好热闹哦), 的 with its word (今天的). Write it for every line you can.
  2. jieba (if installed), then cleaned up: a particle (啦 咯 哦 咧 耶 啊 呀 吧 呢 嘛 噢 喔 哈) or 的 / 们 joins the word
     before it, and a single character joins the word after it when both are short (at most 4 characters together).
  3. otherwise the run stops and lists the lines that need a "seg".
The characters of the words must spell the line's text without punctuation, or the run stops for that line.
Prints one JSON line with the words of every line (check them).
"""
import json, shutil, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console

PARTICLES = set("啦咯哦咧耶啊呀吧呢嘛噢喔哈")
STICKY = set("的们") | PARTICLES


def jieba_words(flat):
    try:
        import jieba
    except ImportError:
        return None
    jieba.setLogLevel(60)
    ws = [w for w in jieba.lcut(flat) if w.strip()]
    out = []
    for w in ws:
        if out and (all(c in STICKY for c in w)):
            out[-1] += w
        else:
            out.append(w)
    merged = []
    for w in out:                                               # a lone character leans on the next short word
        if merged and len(merged[-1]) == 1 and len(merged[-1]) + len(w) <= 4:
            merged[-1] += w
        else:
            merged.append(w)
    return merged


def main():
    args = sys.argv[1:]
    script = args[args.index("--script") + 1] if "--script" in args else None
    pos = [a for i, a in enumerate(args) if a != "--script" and (i == 0 or args[i - 1] != "--script")]
    if len(pos) != 1:
        raise SystemExit(__doc__)
    path = pos[0]
    plan = json.load(open(path, encoding="utf-8"))
    segs = {}
    if script:
        for i, ln in enumerate(json.load(open(script, encoding="utf-8"))["lines"]):
            if ln.get("seg"):
                segs[i + 1] = ln["seg"].split()
    missing, report, how = [], {}, {"seg": 0, "jieba": 0}
    new = []
    for ln in plan["lines"]:
        chars = ln["words"]
        if any(len(w["t"]) != 1 for w in chars):
            raise SystemExit(f"regroup: line {ln['id']} is already grouped; run makeplan.py again first")
        flat = "".join(w["t"] for w in chars)
        seg = segs.get(ln["id"])
        if seg:
            how["seg"] += 1
        else:
            seg = jieba_words(flat)
            if seg is None:
                missing.append(ln["id"]); continue
            how["jieba"] += 1
        if "".join(seg) != flat:
            raise SystemExit(f"regroup: line {ln['id']}: the words {seg} do not spell {flat!r}")
        out, i = [], 0
        for word in seg:
            n, j = 0, i
            while n < len(word):
                n += len(chars[j]["t"]); j += 1
            out.append({"t": word, "start": chars[i]["start"], "end": chars[j - 1]["end"]})
            i = j
        new.append((ln, out))
        report[ln["id"]] = " ".join(seg)
    if missing:
        raise SystemExit(f"regroup: no jieba on this PC; add a \"seg\" to the script for lines {missing}")
    shutil.copyfile(path, path[:-5] + ".before-regroup.json" if path.endswith(".json") else path + ".before-regroup")
    for ln, out in new:
        ln["words"] = out
    json.dump(plan, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"regrouped": len(new), "from": how, "words": report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
