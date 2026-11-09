"""The <out>.sfx-events.json a FULL render would write, without rendering a frame (the sound events depend only on the
plan, the clip length and the cute settings, never on the picture or its cuts).

usage: python <work>/cc916/sfx_dryrun.py <render folder: <work>/cc916 or <work>/cc16> <video> <plan.json> <out.sfx-events.json> [--no-cute]
(make_renderers.py copies it next to each renderer; cute.json is read from the plan's folder.)
It builds the same big moments, card timeline, transitions, leaks, camera events and cute pops as render.py main() and
writes them in the same order and format.
"""
import importlib.util, json, os, sys


def main():
    args = [a for a in sys.argv[1:] if a != "--no-cute"]
    folder, video, plan_p, out_p = args
    sys.path.insert(0, os.path.abspath(folder))
    spec = importlib.util.spec_from_file_location("ccrender", os.path.join(folder, "render.py"))
    R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
    cc, cute = R.cc, R.cute
    plan = cc.load(plan_p)
    err, warn = cc.check(plan)
    pdir = os.path.dirname(os.path.abspath(plan_p))
    if hasattr(R, "LAYOUT16") and os.path.isfile(os.path.join(pdir, "layout16.json")):
        R.LAYOUT16.update(cc.load(os.path.join(pdir, "layout16.json")))
    classic = plan.get("motion") == "classic"
    cute.setup(R.W, R.H, R.SAFE, cute.wants(plan) and "--no-cute" not in sys.argv and not classic, pdir, None, warn)
    full = cc.probe(video)["duration"]
    lines = sorted(plan.get("lines", []), key=lambda l: l["start"])
    bigs = []
    for i, ln in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else full
        if (ln.get("kind") or "card") != "card":
            b = R.Big(ln, warn)
            b.t_out = min(max(ln["end"] + 0.25, b.settle + 0.6), nxt + 0.6, full)
            bigs.append(b)
    timeline = R.card_timeline(lines, bigs, full, classic, warn)
    trans = [(ln["start"], ln["transition"]) for ln in lines if ln.get("transition")]
    leaks = [{"t": tc, "dur": 0.9, "amp": 0.55, "what": "after the flash"} for tc, k in trans if k == "flash"] \
        + [{"t": ln["start"], "dur": 1.5, "amp": 0.38, "what": f"line {ln.get('id')}"} for ln in lines if ln.get("leak")] \
        + [dict({"dur": 1.0, "amp": 0.5, "what": "plan"}, **lk) for lk in plan.get("leaks") or []]
    cam = R.Camera(plan.get("camera") or {}, lines, bigs, trans, full, [], False)
    FPS = R.FPS
    sfx = []
    for b in bigs:
        for e in b.events:
            if e.get("sfx"):
                sfx.append({"frame": int(round(e["t"] * FPS)), "sound": e["sfx"], "what": f"line {b.id} {b.kind}: {e['kind']}"})
    for tc, kind in trans:
        if kind == "flash":
            sfx.append({"frame": int(round(tc * FPS)), "sound": "whoosh_zoom", "what": "white flash transition"})
    for lk in leaks:
        sfx.append({"frame": int(round((lk["t"] + lk["dur"] / 2) * FPS)), "sound": "chime_soft", "what": f"light leak brightest ({lk['what']})"})
    if cute.ON:
        sfx += cute.sfx_events(timeline)
    for e in cam.events():
        sfx.append({"frame": int(round(e["t"] * FPS)), "sound": e["sfx"], "what": e["kind"]})
    n = int(round(full * FPS))
    sfx = [e for e in sfx if 0 <= e["frame"] < n]
    cc.save(out_p, {"events": sorted(sfx, key=lambda e: e["frame"]),
                    "note": "draft from the caption-card plan: keep the true punchlines, delete the rest (a sermon stays reverent)"})
    print(json.dumps({"tool": "sfx_dryrun", "ok": True, "out": out_p, "edition": "cute" if cute.ON else "standard",
                      "events": len(sfx), "cute_pops": sum(1 for e in sfx if "cute card" in e["what"]), "warnings": warn}))


if __name__ == "__main__":
    main()
