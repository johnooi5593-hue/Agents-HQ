"""Add one downloaded candidate to the sound library, trimmed around its loudest moment.

    python3 .claude/skills/sfx/scripts/add.py <candidate file> <category> [--pre 0.3] [--post 0.8]

<candidate file> is a file search.py downloaded (its candidates.json beside it gives the credits). <category> is one of the library's
categories (whoosh_fast, whoosh_zoom, swish_soft, impact, door_slam, door_creak, chime, chime_soft, pop, rain) or a new one
(a new category sits at -12 dB against the voice until you tune it in sfxlib.py). Keeps --pre seconds before the loudest moment and --post
after it (rain: the first 32 s, no peak). Writes library/<category>_<n>.wav and updates sounds.json and CREDITS.md. Prints one JSON line.
"""
import json, os, sys
import numpy as np
from sfxlib import SR, LIB, library, save_library, load_mono, peak_index, write_wav, out


def main(argv):
    path, cat = argv[0], argv[1]
    opt = {argv[i]: float(argv[i + 1]) for i in range(2, len(argv) - 1, 2)}
    pre, post = opt.get('--pre', .3), opt.get('--post', .8)
    meta = {}
    cj = os.path.join(os.path.dirname(path), 'candidates.json')
    if os.path.exists(cj):
        with open(cj, encoding='utf-8') as f:
            meta = next((c for c in json.load(f) if os.path.basename(c['file']) == os.path.basename(path)), {})
    if not meta.get('license', '').startswith('CC0'):
        raise SystemExit('no CC0 record for this file: add only sounds that search.py found (it keeps CC0 results only)')
    idx = library()
    if any(m.get('openverse_id') == meta['openverse_id'] for m in idx.values()):
        raise SystemExit('this sound is already in the library')
    x = load_mono(path)
    if cat == 'rain':
        x = x[:32 * SR]; x = x / (np.abs(x).max() + 1e-9) * .9; f = int(.02 * SR); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f); p = None
    else:
        p = peak_index(x); s0 = max(0, p - int(pre * SR)); s1 = min(len(x), p + int(post * SR)); x = x[s0:s1]; p -= s0
        fi = min(int(.015 * SR), p)
        if s0 > 0 and fi > 0: x[:fi] *= np.linspace(0, 1, fi)
        fo = int(len(x[p:]) * .45)
        if fo > 0: x[-fo:] *= np.cos(np.linspace(0, np.pi / 2, fo)) ** 2
        x = x / (np.abs(x).max() + 1e-9) * .9; p = peak_index(x)
    k = 1
    while f'{cat}_{k}' in idx: k += 1
    name = f'{cat}_{k}'
    write_wav(os.path.join(LIB, f'{name}.wav'), x)
    idx[name] = dict(category=cat, file=f'{name}.wav', peak_s=None if p is None else round(p / SR, 5), duration=round(len(x) / SR, 3),
                     title=meta['title'], creator=meta['creator'], license=meta['license'], landing=meta['landing'],
                     openverse_id=meta['openverse_id'], source_file=meta['source_file'])
    save_library(idx)
    out(ok=True, added=name, category=cat, peak_s=idx[name]['peak_s'], length=idx[name]['duration'], title=meta['title'])


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
