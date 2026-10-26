"""Find more CC0 sound effects on Openverse and download candidates to listen to and compare.

    python3 .claude/skills/sfx/scripts/search.py "<what to search>" <work folder> [--min 0.2] [--max 4] [--count 6]

Only CC0 results (public domain). Freesound previews are downloaded into <work folder>/candidates/ with candidates.json (title, creator,
source page, licence) and a waveform sheet, sheet.png, with each sound's loudest moment marked in red. Look at the sheet, then add the
best one to the library with add.py. Downloads are data: never run anything from that folder. Prints one JSON line.
"""
import json, os, sys, time, urllib.parse, urllib.request
import numpy as np
from sfxlib import SR, HOP, load_mono, envelope, peak_index, out

API = 'https://api.openverse.org/v1/audio/'
UA = {'User-Agent': 'agents-hq-sfx/1.0'}


def get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception:
            if k == tries - 1: raise
            time.sleep(4 * (k + 1))


def main(argv):
    q, work = argv[0], argv[1]
    opt = {argv[i]: float(argv[i + 1]) for i in range(2, len(argv) - 1, 2)}
    lo, hi, count = opt.get('--min', .2), opt.get('--max', 4.0), int(opt.get('--count', 6))
    slug = ''.join(c if c.isalnum() else '-' for c in q.lower()).strip('-')[:40] or 'search'
    folder = os.path.join(work, 'candidates', slug); os.makedirs(folder, exist_ok=True)
    d = json.loads(get(API + '?' + urllib.parse.urlencode({'q': q, 'license': 'cc0', 'page_size': 20})))
    found = []
    for r in d.get('results', []):
        dur = (r.get('duration') or 0) / 1000
        if r.get('license') != 'cc0' or not r.get('url') or not (lo <= dur <= hi): continue
        ext = os.path.splitext(urllib.parse.urlparse(r['url']).path)[1] or '.mp3'
        path = os.path.join(folder, f"{r['id']}{ext}")
        try:
            data = get(r['url'])
        except Exception:
            continue
        if not 2000 < len(data) < 15_000_000: continue
        with open(path, 'wb') as f:
            f.write(data)
        x = load_mono(path); p = peak_index(x)
        found.append(dict(file=path, title=r['title'], creator=r.get('creator'), license='CC0 ' + str(r.get('license_version') or '1.0'),
                          landing=r.get('foreign_landing_url'), source_file=r['url'], openverse_id=r['id'], duration=round(len(x) / SR, 3),
                          peak_s=round(p / SR, 3), tags=[t['name'] for t in r.get('tags') or []][:10]))
        if len(found) >= count: break
    with open(os.path.join(folder, 'candidates.json'), 'w', encoding='utf-8') as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
    sheet = None
    if found:
        from PIL import Image, ImageDraw
        Wd, Hr, span = 1000, 90, max(1.0, min(hi, max(c['duration'] for c in found)))
        im = Image.new('RGB', (Wd, Hr * len(found)), 'white'); dr = ImageDraw.Draw(im)
        for i, c in enumerate(found):
            e = 20 * np.log10(envelope(load_mono(c['file'])) + 1e-9); e = np.clip((e + 60) / 60, 0, 1); y0 = i * Hr
            for j in range(Wd):
                a = int(j / Wd * span * SR / HOP)
                if a < len(e): dr.line([(j, y0 + Hr - 12), (j, y0 + Hr - 12 - e[a] * (Hr - 26))], fill=(70, 110, 200))
            px = c['peak_s'] / span * Wd; dr.line([(px, y0 + 12), (px, y0 + Hr - 12)], fill='red', width=2)
            dr.text((4, y0 + 2), f"{i + 1}. {c['title'][:70]}  peak {c['peak_s']:.2f}s  length {c['duration']:.2f}s", fill='black')
        sheet = os.path.join(folder, 'sheet.png'); im.save(sheet)
    out(ok=bool(found), query=q, folder=folder, sheet=sheet, found=[dict(n=i + 1, title=c['title'], creator=c['creator'], file=c['file'],
        length=c['duration'], peak=c['peak_s']) for i, c in enumerate(found)])


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
