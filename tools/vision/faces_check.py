"""Compares faces.py boxes with hand-typed face boxes (the FACES9 / FACES16 tables of a build_stickers.py).

usage: python faces_check.py <faces.json> <build_stickers.py> --table FACES9|FACES16 [--pad P] [--min M] [--grow G]
                             [--conf C] [--sweep] [--json out.json]

The build_stickers.py is only READ (parsed with ast; nothing in it runs). Each table row is (start, end, [x0, y0, x1, y1],
what). --pad / --min / --grow / --conf rebuild the face ranges from the faces.json per_frame detections (no new
detection; --min and --conf can only go up from what the detection used). --sweep tries a grid and prints one row each.

Measures (sampled every 0.1 s inside each hand box's time range, 0.05 s in from both ends):
  hit at t      a detected (padded) face box live at t overlaps the hand box by at least --overlap (default 0.25) of the
                SMALLER of the two boxes (a face inside a wide hand box, or a hand box inside a big face box, both
                count; 0.25 because the hand boxes were typed by eye and often sit beside the face). The strict 0.5
                recall is printed too.
  covered       hit on at least 50% of the samples. recall = covered hand boxes / all hand boxes
  time recall   hit samples / all samples, over every hand box
  misses        hand boxes that are not covered, with their hit fraction
  bloat         padded box area / the mean unpadded face area of its range. pad 0.25 alone gives 1.5 x 1.6 = 2.4;
                "wildly oversized" = more than 2x what the padding alone gives (bloat > 2 x (1+2p)(1+p(1+1.4))):
                the range merged a face that moved far, AND over 5% of the frame (small boxes are harmless). big_on_frame lists boxes over
                0.6 wide, 0.5 tall or 25% of the frame for information (close-ups are big by nature).
  extras        detected ranges (>= 3 hits) that touch no hand box: faces the hand tables lack, or false alarms
Prints a table and one JSON line.
"""
import argparse, ast, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import faces as F  # noqa: E402

BIG_W, BIG_H, BIG_A = 0.6, 0.5, 0.25
WILD = 2.0                      # x the padded face box
WILD_MIN_AREA = 0.05            # ... and over 5% of the frame (a small face that moved is not 'wild')


def read_table(path, name):
    """The literal list assigned to `name` in a Python file (parsed, never executed)."""
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            rows = ast.literal_eval(node.value)
            return [{'start': float(r[0]), 'end': float(r[1]), 'box': [float(v) for v in r[2]], 'what': r[3] if len(r) > 3 else ''}
                    for r in rows]
    raise SystemExit(f'no {name} = [...] table in {path}')


def hit(face_box, hand_box, overlap=0.25):
    i = F.inter(face_box, hand_box)
    m = min(F.area(face_box), F.area(hand_box))
    return m > 0 and i >= overlap * m


def bloat(f):
    fa = F.area(f.get('face') or f['box'])
    return F.area(f['box']) / fa if fa > 0 else 1.0


def oversized(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return w > BIG_W or h > BIG_H or w * h > BIG_A


def num(v, w=6):
    """A recall for the sweep table: "-" when there is nothing to measure (an empty hand table)."""
    return f'{v:{w}.3f}' if v is not None else f'{"-":>{w}}'


def evaluate(fj, hand, step=0.1, need=0.5, overlap=0.25):
    faces = fj['faces']
    rows, tot, tot_hit = [], 0, 0
    for h in hand:
        n = k = k5 = 0
        t = h['start'] + 0.05
        while t <= h['end'] - 0.05 + 1e-9:
            n += 1
            live = F.live_at(faces, t)
            if any(hit(f['box'], h['box'], overlap) for f in live):
                k += 1
            if any(hit(f['box'], h['box'], 0.5) for f in live):
                k5 += 1
            t += step
        frac = k / n if n else 0.0
        rows.append(dict(h, samples=n, hit=round(frac, 3), covered=frac >= need, covered_strict=(k5 / n if n else 0) >= need))
        tot += n; tot_hit += k
    covered = sum(r['covered'] for r in rows)
    big = [f for f in faces if oversized(f['box'])]
    p = (fj.get('params') or {}).get('pad', 0.25)
    base = (1 + 2 * p) * (1 + p * (1 + F.TOP_PAD))
    wild = [f for f in faces if bloat(f) > WILD * base and F.area(f['box']) > WILD_MIN_AREA]
    extras = [f for f in faces if f.get('hits', 0) >= 3 and not any(
        h['start'] < f['end'] and f['start'] < h['end'] and F.inter(f['box'], h['box']) > 0 for h in hand)]
    widest = max(faces, key=lambda f: F.area(f['box']), default=None)
    return dict(recall=round(covered / len(rows), 3) if rows else None, covered=covered, hand_boxes=len(rows),
                recall_strict=round(sum(r['covered_strict'] for r in rows) / len(rows), 3) if rows else None,
                time_recall=round(tot_hit / tot, 3) if tot else None,
                max_bloat=round(max((bloat(f) for f in faces), default=0), 2),
                wild=[dict({k: f[k] for k in ('start', 'end', 'box')}, bloat=round(bloat(f), 2)) for f in wild],
                misses=[{k: r[k] for k in ('start', 'end', 'what', 'hit')} for r in rows if not r['covered']],
                big_on_frame=len(big),
                largest_box_area=round(F.area(widest['box']), 3) if widest else 0,
                faces=len(faces), extras=len(extras),
                extras_list=[{k: f[k] for k in ('start', 'end', 'box', 'conf', 'hits')} for f in extras], rows=rows)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('faces'); ap.add_argument('build')
    ap.add_argument('--table', required=True)
    ap.add_argument('--pad', type=float); ap.add_argument('--min', type=float, dest='min_frac')
    ap.add_argument('--grow', type=float); ap.add_argument('--conf', type=float)
    ap.add_argument('--sweep', action='store_true')
    ap.add_argument('--overlap', type=float, default=0.25)
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    with open(a.faces, encoding='utf-8') as f:
        fj = json.load(f)
    hand = read_table(a.build, a.table)
    if a.sweep:
        print(f"{'pad':>5} {'min':>5} {'grow':>5} {'conf':>5}  recall strict  time   faces wild maxbloat largest extras")
        base = fj.get('params') or {}
        for pad in (0.15, 0.25, 0.35, 0.5):
            for mn in sorted({base.get('min', 0.04), 0.05, 0.06}):
                for grow in (1.5, 1.8, 2.5):
                    for conf in sorted({base.get('conf', 0.6), 0.7, 0.8}):
                        r = evaluate(F.rebuild(fj, pad, mn, grow, conf), hand, overlap=a.overlap)
                        print(f'{pad:5.2f} {mn:5.2f} {grow:5.1f} {conf:5.2f}  {num(r["recall"])} {num(r["recall_strict"])} '
                              f'{num(r["time_recall"])} {r["faces"]:6d} {len(r["wild"]):4d} {r["max_bloat"]:8.2f} '
                              f'{r["largest_box_area"]:7.3f} {r["extras"]:6d}')
        return
    if any(v is not None for v in (a.pad, a.min_frac, a.grow, a.conf)):
        fj = F.rebuild(fj, a.pad, a.min_frac, a.grow, a.conf)
    r = evaluate(fj, hand, overlap=a.overlap)
    for row in r['rows']:
        print(f"{'ok  ' if row['covered'] else 'MISS'} {row['start']:5.1f}-{row['end']:5.1f}  hit {row['hit']:4.0%}  {row['what']}")
    p = fj.get('params') or {}
    summary = {k: v for k, v in r.items() if k not in ('rows', 'extras_list')}
    summary.update(overlap=a.overlap, table=a.table, video_size=fj['size'], pad=p.get('pad'), min=p.get('min'), grow=p.get('grow'), conf=p.get('conf'))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(dict(summary, rows=r['rows'], extras_list=r['extras_list']), f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
