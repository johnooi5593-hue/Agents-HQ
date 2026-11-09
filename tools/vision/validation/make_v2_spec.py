"""Writes 1107-v2-placements.json: a small stickers.json with the two 1107 Children review v2 placements the
brand-checker failed, at their ORIGINAL positions, and the typed face boxes the v2 plan had (FACES9 of
work/creative/1107-children/scripts/build_stickers.before16.py, read with ast, never run; v2 had no 16:9 face table).

    hook sparkle  9:16 [0.91, 0.47], t 0.70 + 1.55 s, size 0.12   (on the girl at the right edge, 0.9-2.2 s)
    rainbow       16:9 [0.88, 0.15], t 38.62 + 1.15 s, size 0.24  (on the woman in green leaning in, 39.3-39.7 s)

usage: python make_v2_spec.py     then
       python ".claude/skills/kids-review/scripts/stickers.py" plan tools/vision/validation/1107-v2-placements.json
       (no warnings: the typed v2 boxes missed both faces) and the same with
       --faces tools/vision/validation/1107-faces916.json --faces tools/vision/validation/1107-faces16.json
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from faces_check import read_table  # noqa: E402

V2 = r'D:/Agents HQ/work/creative/1107-children/scripts/build_stickers.before16.py'
faces9 = read_table(V2, 'FACES9')
spec = {
    'note': 'Test spec (t202): the two v2 placements the brand-checker failed, at their original positions, with the v2 '
            'typed face boxes. Not a real plan.',
    'max_on_screen': 4,
    'avoid': [{'start': f['start'], 'end': f['end'], 'what': f"face (typed v2): {f['what']}", 'box': {'9x16': f['box']}}
              for f in faces9],
    'stickers': [
        {'t': 0.7, 'dur': 1.55, 'kind': 'sparkle', 'pos': {'9x16': [0.91, 0.47], '16x9': [0.80, 0.55]}, 'size': 0.12,
         'group': 'burst:hook', 'sfx': 'chime', 'sfx_db': -6, 'what': 'hook: sparkles (v2 position)', 'color': 'pink'},
        {'t': 38.62, 'dur': 1.15, 'kind': 'rainbow', 'pos': {'9x16': [0.83, 0.09], '16x9': [0.88, 0.15]}, 'size': 0.24,
         'group': 'burst:done', 'sfx': 'pop', 'sfx_db': 0, 'what': 'done: rainbow (v2 position)'},
    ],
}
dest = os.path.join(HERE, '1107-v2-placements.json')
with open(dest, 'w', encoding='utf-8') as f:
    json.dump(spec, f, ensure_ascii=False, indent=1)
print(json.dumps({'ok': True, 'out': dest, 'avoid': len(spec['avoid']), 'stickers': 2}))
