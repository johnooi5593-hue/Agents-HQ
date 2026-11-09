"""Sticker plan of ONE kids review: copy this file into the video's work folder, rewrite every table for that video, run it.

usage: python "<work>/build_stickers.py" [<out stickers.json>]        (default: stickers.json next to this file)
then:  python "D:/Agents HQ/.claude/skills/kids-review/scripts/stickers.py" plan "<work>/stickers.json"
       python ".../stickers.py" sheet "<work>/render916/edit.mp4" "<work>/check/stk-plan-916.jpg" --every 0.5 --boxes "<work>/stickers.json"
       (and the same on the 16:9 render): fix every error, look at every "touches" warning on the frames.

Edit the TABLES, never stickers.json. The worked example in every table is the owner-approved 1107 Children review v3
(52.2 s, 25 shots of 2 s, cuts at 2.2, 4.2 ... 49.0 s); replace its rows with the new video's. Positions are [x, y]
FRACTIONS of the frame, one pair for 9:16 (p9) and one for 16:9 (p16); sizes are fractions of the frame's short side.
Sticker kinds, motions and fields: the docstring at the top of stickers.py. The look in numbers: ../GUIDE.md.

Sections:
  0  setup              paths, the cut times (read from shots.json), corner spots
  1  cuts               one small sticker at each plain cut (0.15 of the short side, 1.6 s at most, a new kind each time)
  2  bursts             3-6 bigger stickers at each key moment (hook, the craft's name, the V sign, the wow, the payoff,
                        the group photo, the goodbye); their group starts with "burst" so they don't count to the limit
  3  motion graphics    bubbles, twinkles, trails, wipes, underlines, arrows, frames, balloons (the v3 "more motion graphic")
  4  avoid boxes        caption cards and big type (both sizes), faces per shot (9:16 and 16:9 separately): the
                        faces*.json from tools/vision/faces.py beside shots.json, plus the typed FACES9 / FACES16 extras
  5  fit + write        each bubble shrinks (down to 0.85x) until it touches no avoid box, then stickers.json is written
"""
import json, os, sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")       # Chinese in the JSON lines on a cp1252 console

# ==== 0. SETUP ======================================================================================================
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.environ.get("KIDS_REVIEW", "D:/Agents HQ/.claude/skills/kids-review/scripts")
DEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "stickers.json")
SHOTS = os.path.join(HERE, "shots.json")
NOTE = "1107 Children review v3 stickers (built by the kids-review skill's build_stickers template)."   # <- this video

_cfg = json.load(open(SHOTS, encoding="utf-8"))
CUT_TIMES, _t = [], 0.0
for _s in _cfg["shots"]:
    CUT_TIMES.append(round(_t, 3)); _t += round(_s.get("d", _cfg.get("dur", 2.0)) * 30) / 30
END = round(_t, 3)


def next_cut(c):
    return next((x for x in CUT_TIMES if x > c + 1e-6), END)


SPOT = {  # corner / edge spots: name -> (9:16 [x, y], 16:9 [x, y]); the outer ~15 % band keeps stickers off faces
    'TL': ([0.15, 0.10], [0.08, 0.14]), 'TR': ([0.85, 0.10], [0.92, 0.14]),
    'BL': ([0.15, 0.88], [0.08, 0.86]), 'BR': ([0.85, 0.88], [0.92, 0.86]),
}


def st(t, dur, kind, p9, p16, size, group, what, sfx='pop', db=-2, **kw):
    d = {'t': round(t, 3), 'dur': round(dur, 3), 'kind': kind, 'pos': {'9x16': p9, '16x9': p16}, 'size': size,
         'group': group, 'sfx': sfx, 'what': what}
    if sfx:
        d['sfx_db'] = db
    d.update(kw)
    return d


S = []

# ==== 3a. WIPES first (the cut stickers wait for them) ================================================================
# Candy-bubble wipes on about every 4th cut (6 in 52 s), never on a burst cut. cut time -> direction right|left|down|up|diag.
WIPES = {6.2: 'right', 12.2: 'left', 20.2: 'down', 24.2: 'diag', 30.2: 'right', 41.8: 'left'}
WIPE_STARS = {30.2: 18, 41.8: 12}            # stars in the wipe (default 9)
WIPE_DB = {24.2: 3}                          # 1107: earshot heard no hit on the 24.2 swish at 0 dB

# ==== 1. CUTS: one small sticker at each plain cut ====================================================================
# cut time, kind, spot name or (p9, p16), extra fields. Pops in at cut + 0.05 s (cut + 0.2 s after a wipe), gone before the
# next cut. Leave out the cuts that open a burst. Rotate the kinds; never the same kind twice in a row.
CUTS = [
    (2.2, 'sun', 'TL', {}),
    (4.2, 'note', ([0.86, 0.90], [0.92, 0.84]), {'color': 'rose', 'rise': 0.1}),
    (6.2, 'star', 'BL', {'color': 'pink'}),
    (10.2, 'thumbs', ([0.86, 0.88], [0.92, 0.84]), {}),
    (12.2, 'face_smile', ([0.14, 0.89], [0.08, 0.84]), {}),
    (14.2, 'star', ([0.12, 0.12], [0.08, 0.14]), {'color': 'yellow'}),
    (16.2, 'sparkle', 'TR', {'color': 'yellow'}),
    (18.4, 'face_wink', 'TL', {}),                      # 1107: 0.2 s late on purpose (the camera punch-in at 18.3)
    (20.2, 'note', ([0.15, 0.2], [0.08, 0.22]), {'color': 'sky', 'rise': 0.1}),
    (22.2, 'cloud', ([0.8, 0.1], [0.9, 0.14]), {}),
    (24.2, 'heart', ([0.85, 0.9], [0.92, 0.86]), {'color': 'pink', 'rise': 0.08}),
    (28.2, 'sun', ([0.13, 0.1], [0.08, 0.14]), {}),
    (30.2, 'note', ([0.14, 0.9], [0.08, 0.86]), {'color': 'purple', 'rise': 0.08}),
    (34.2, 'star', ([0.14, 0.89], [0.08, 0.86]), {'color': 'mint'}),
    (36.2, 'face_wow', ([0.86, 0.89], [0.92, 0.86]), {}),
    (39.8, 'star', ([0.12, 0.88], [0.08, 0.86]), {'color': 'sky'}),
    (41.8, 'note', ([0.86, 0.16], [0.06, 0.88]), {'color': 'pink', 'rise': 0.08}),
]
EXACT = {18.4}                                           # cut stickers that start exactly at their time (no + 0.05)
for c, kind, spot, extra in CUTS:
    p9, p16 = SPOT[spot] if isinstance(spot, str) else spot
    t = c if c in EXACT else c + 0.05
    if c in WIPES:                                       # pop in after the bubble wipe has cleared (it ends cut + 0.17 s)
        t = c + 0.2
    S.append(st(t, min(1.6, next_cut(c) - t - 0.05), kind, p9, p16, 0.15, 'cut', f'cut {c:.1f}s', db=-3, **extra))

# ==== 2. BURSTS: 3-6 stickers per key moment (owner brief: cute, not cluttered) =======================================
# st(t, dur, kind, p9, p16, size, group, what, sfx, db, ...). The leader gets the sound at db +1, the rest -2..-4 or none.
B = []
# hook (0.15 s, 哇！头上戴的是什么啊？): big star-eyes face + sparkles + a "?" doodle
B += [st(0.45, 1.85, 'face_star', [0.80, 0.885], [0.88, 0.80], 0.25, 'burst:hook', 'hook: star-eyes face', db=1),
      st(0.70, 1.55, 'sparkle', [0.12, 0.12], [0.80, 0.55], 0.12, 'burst:hook', 'hook: sparkles', sfx='chime', db=-6, color='pink'),
      st(1.00, 1.25, 'question', [0.17, 0.86], [0.08, 0.14], 0.17, 'burst:hook', 'hook: ? doodle', rot=12, color='sky')]
# the craft's name (8.35 s, write-on 蒙古包): sparkles + stars around the word
B += [st(8.50, 1.65, 'sparkle', [0.20, 0.30], [0.25, 0.25], 0.16, 'burst:yurt', 'yurt: sparkle top-left', sfx=None),
      st(8.70, 1.45, 'star', [0.82, 0.33], [0.75, 0.25], 0.14, 'burst:yurt', 'yurt: star top-right', sfx=None, color='yellow'),
      st(9.85, 0.85, 'sparkle', [0.86, 0.66], [0.78, 0.72], 0.12, 'burst:yurt', 'yurt: sparkle as the word writes', sfx='chime', db=-6, color='pink'),
      st(10.0, 0.7, 'star', [0.14, 0.67], [0.22, 0.72], 0.12, 'burst:yurt', 'yurt: pink star as the word lands', db=-3, color='pink')]
# the V sign (26.45 s, punch 比个V): laughing face + a V-hand sticker + stars
B += [st(26.45, 1.7, 'face_laugh', [0.82, 0.87], [0.90, 0.80], 0.22, 'burst:V', 'V: laughing face', db=1),
      st(26.60, 1.55, 'vhand', [0.17, 0.86], [0.10, 0.80], 0.17, 'burst:V', 'V: V-hand sticker', sfx=None, rot=10),
      st(27.10, 1.05, 'star', [0.87, 0.12], [0.92, 0.14], 0.11, 'burst:V', 'V: star', db=-2, color='yellow'),
      st(27.30, 0.85, 'sparkle', [0.12, 0.12], [0.08, 0.14], 0.10, 'burst:V', 'V: sparkle', sfx=None)]
# the wow (32.3 s, write-on 好漂亮): heart-eyes face + floating hearts + a crayon squiggle under the word
B += [st(32.30, 1.85, 'face_heart', [0.80, 0.88], [0.90, 0.80], 0.22, 'burst:pretty', 'pretty: heart-eyes face', db=1),
      st(32.60, 1.5, 'heart', [0.16, 0.90], [0.10, 0.84], 0.10, 'burst:pretty', 'pretty: floating heart', db=-3, color='pink', rise=0.1),
      st(32.95, 1.2, 'heart', [0.30, 0.93], [0.20, 0.88], 0.08, 'burst:pretty', 'pretty: floating heart', sfx=None, color='rose', rise=0.08),
      st(33.20, 1.0, 'heart', [0.12, 0.14], [0.08, 0.2], 0.08, 'burst:pretty', 'pretty: floating heart', sfx=None, color='pink', rise=0.06),
      st(33.15, 0.85, 'squiggle', [0.50, 0.84], [0.5, 0.865], {'9x16': 0.30, '16x9': 0.20}, 'burst:pretty', 'pretty: squiggle underline', sfx=None)]
# the payoff (38.15 s, punch 完成啦): confetti from both bottom corners + a thumbs-up + a rainbow
B += [st(38.03, 1.75, 'thumbs', [0.13, 0.905], [0.10, 0.78], {'9x16': 0.16, '16x9': 0.18}, 'burst:done', 'done: thumbs-up', db=1),
      st(38.55, 1.2, 'confetti', [0.08, 0.98], [0.05, 0.98], 0.04, 'burst:done', 'done: confetti left', sfx=None,
         spread=[-85, -35], speed=1.5, count=40, clip={'9x16': [0, 0.56, 1, 1], '16x9': [0, 0.6, 1, 1]}),
      st(38.55, 1.2, 'confetti', [0.92, 0.98], [0.95, 0.98], 0.04, 'burst:done', 'done: confetti right', sfx=None,
         spread=[-145, -95], speed=1.5, count=40, clip={'9x16': [0, 0.56, 1, 1], '16x9': [0, 0.6, 1, 1]}),
      st(38.62, 1.15, 'rainbow', [0.83, 0.09], [0.12, 0.15], 0.24, 'burst:done', 'done: rainbow', sfx='pop', db=0)]
# the group photos (43.95-48.5 s, 一二三耶): a bouncing camera doodle, stars, a flash sparkle with a shutter on 耶, confetti
# only in the blurred bands above and below the photo
B += [st(44.05, 4.35, 'camera', [0.80, 0.16], [0.90, 0.16], 0.20, 'burst:group', 'group: camera doodle', db=0, motion='bounce'),
      st(44.60, 1.75, 'star', [0.16, 0.18], [0.08, 0.16], 0.13, 'burst:group', 'group: star', db=-3, color='yellow'),
      st(46.45, 1.9, 'sparkle', [0.17, 0.85], [0.08, 0.86], 0.13, 'burst:group', 'group 2: sparkle', db=-3, color='pink'),
      st(47.85, 0.55, 'sparkle', [0.86, 0.10], [0.95, 0.09], 0.10, 'burst:group', 'group: camera flash on 耶', sfx='shutter', db=-2, color='white'),
      st(47.85, 1.3, 'confetti', [0.5, 0.0], [0.5, 0.0], 0.04, 'burst:group', 'group: confetti top band', sfx=None,
         spread=[30, 150], speed=0.5, count=44, clip={'9x16': [0, 0, 1, 0.29], '16x9': [0, 0, 1, 0.2]}),
      st(47.85, 1.3, 'confetti', [0.5, 1.0], [0.5, 1.0], 0.04, 'burst:group', 'group: confetti bottom band', sfx=None,
         spread=[-160, -20], speed=0.6, count=44, clip={'9x16': [0, 0.76, 1, 1], '16x9': [0, 0.84, 1, 1]})]
# the goodbye (49.15 s, 下次见啦 拜拜): a waving face + floating hearts to the end
B += [st(49.05, 3.15, 'face_wave', [0.50, 0.15], [0.88, 0.16], 0.25, 'burst:bye', 'bye: waving face', db=1),
      st(49.50, 1.6, 'heart', [0.20, 0.92], [0.10, 0.88], 0.10, 'burst:bye', 'bye: floating heart', sfx=None, color='pink', rise=0.1),
      st(50.20, 1.6, 'heart', [0.80, 0.93], [0.90, 0.88], 0.09, 'burst:bye', 'bye: floating heart', db=-4, color='rose', rise=0.1),
      st(50.90, 1.3, 'heart', [0.36, 0.94], [0.25, 0.9], 0.08, 'burst:bye', 'bye: floating heart', sfx=None, color='pink', rise=0.08),
      st(51.10, 1.1, 'heart', [0.66, 0.93], [0.75, 0.9], 0.08, 'burst:bye', 'bye: floating heart', sfx=None, color='purple', rise=0.08)]
S += B

# ==== 3. MOTION GRAPHICS ==============================================================================================
# One sound per group: pops db -2 / -3, swishes 0 / -1, the twinkle chime -8 (raise to -4 where the voice masks it);
# trail pieces and second twinkles are silent.
V3 = []
BUBX = {'9x16': 1.35, '16x9': 1.45}          # bubbles start this much bigger, then the fit (section 5) shrinks them


def bub(t, dur, text, p9, p16, size, color, group='v3', style='round', tail='bl', db=-2, sfx='pop', what=None):
    """A speech (round) or shout bubble with a 1-3 character cute word; tail bl|br|tl|tr (or per aspect)."""
    size = size if isinstance(size, dict) else {'9x16': size, '16x9': size}
    size = {k: round(v * BUBX[k], 3) for k, v in size.items()}
    V3.append(st(t, dur, 'bubble', p9, p16, size, group, what or f'bubble {text}', sfx=sfx, db=db, text=text, style=style,
                 tail=tail, color=color))


LOUDER = {14.80: -4, 42.40: -4}              # twinkles the voice masked at -8 (earshot NO HIT)


def twk(t, dur, p9, p16, color='yellow', group='v3', snd=True, size=0.08):
    V3.append(st(t, dur, 'twinkle', p9, p16, size, group, 'twinkle', sfx='chime' if snd else None, db=LOUDER.get(round(t, 2), -8), color=color,
                 blink=1.5 + (t * 7) % 1.0))


def trl(t, dur, a9, b9, a16, b16, item='heart', group='v3', size=0.065, db=-3):
    """4 small hearts / stars hopping one after another from a to b."""
    V3.append(st(t, dur, 'trail', a9, a16, size, group, f'{item} trail hops', db=db, item=item, count=4,
                 to={'9x16': b9, '16x9': b16}, bend=0.08))


def wipe(cut, dirn, stars=9):
    d = 10 / 30
    V3.append(st(cut - d / 2, d, 'wipe', [0.5, 0.5], [0.5, 0.5], 0.1, 'transition', f'bubble wipe {dirn} on the {cut:.1f}s cut',
                 sfx='swish_soft', db=WIPE_DB.get(cut, 0), dir=dirn, stars=stars, sfx_offset=round(d / 2, 4)))


def uline(t, dur, p9, p16, w9, w16, color, group):
    V3.append(st(t, dur, 'underline', p9, p16, 0.05, group, 'dashed underline', sfx=None, width={'9x16': w9, '16x9': w16},
                 color=color))


# ---- 3a. wipes (the table is in section 3a above)
for c, dirn in WIPES.items():
    wipe(c, dirn, WIPE_STARS.get(c, 9))

# ---- 3b. speech / shout bubbles: about one per plain shot, words the kids would say (好酷 耶 好好吃 哇塞 好可爱 好棒 真棒
#          加油 冲呀 好厉害 哇); text dark ink over a thick white outline (stickers.py). Never on a face or a card.
bub(0.60, 1.55, '好酷!', [0.50, 0.905], [0.90, 0.36], 0.20, 'yellow', 'burst:hook', style='shout')
bub(2.55, 1.55, '耶!', [0.80, 0.15], [0.62, 0.12], 0.18, 'sky', tail='bl')
bub(6.50, 1.60, '好好吃!', [0.78, 0.865], [0.89, 0.62], {'9x16': 0.26, '16x9': 0.22}, 'orange', tail='tl')
bub(11.00, 1.10, '哇塞!', [0.15, 0.46], [0.24, 0.58], 0.20, 'pink', tail='br')
bub(14.50, 1.60, '好可爱!', [0.20, 0.22], [0.73, 0.30], {'9x16': 0.27, '16x9': 0.22}, 'pink', tail={'9x16': 'br', '16x9': 'bl'})
bub(20.50, 1.55, '好棒!', [0.80, 0.18], [0.86, 0.14], 0.18, 'mint', tail='bl')
bub(24.55, 1.55, '真棒!', [0.78, 0.42], [0.10, 0.42], 0.20, 'yellow', tail='bl')
bub(26.75, 1.40, '耶!', [0.80, 0.46], [0.86, 0.30], 0.20, 'yellow', 'burst:V', style='shout')
bub(28.50, 1.60, '加油!', [0.84, 0.09], [0.225, 0.14], 0.20, 'orange', tail='bl')
bub(34.50, 1.60, '好可爱!', [0.76, 0.87], [0.93, 0.35], {'9x16': 0.26, '16x9': 0.18}, 'pink', tail='tl')
bub(36.50, 1.40, '冲呀!', [0.50, 0.88], [0.89, 0.50], {'9x16': 0.20, '16x9': 0.21}, 'sky', style='shout')
bub(40.20, 1.50, '好厉害!', [0.79, 0.91], [0.82, 0.40], {'9x16': 0.27, '16x9': 0.22}, 'sky', tail='tl')
bub(42.10, 1.60, '哇!', [0.84, 0.50], [0.91, 0.13], {'9x16': 0.20, '16x9': 0.22}, 'yellow', style='shout')
bub(47.70, 1.20, '耶!', [0.30, 0.16], [0.90, 0.76], {'9x16': 0.22, '16x9': 0.16}, 'yellow', 'burst:group', style='shout')

# ---- 3c. twinkles: 1-2 per shot in an empty corner, the first with a soft chime
for args in [
    (0.30, 1.85, [0.93, 0.74], [0.95, 0.08], 'yellow', 'burst:hook'), (0.90, 1.25, [0.07, 0.50], [0.60, 0.95], 'pink', 'burst:hook', False),
    (2.80, 1.30, [0.88, 0.86], [0.95, 0.60]), (4.80, 1.30, [0.88, 0.40], [0.95, 0.10], 'pink'), (6.80, 1.30, [0.90, 0.05], [0.97, 0.08]),
    (8.60, 1.50, [0.10, 0.06], [0.06, 0.10], 'yellow', 'burst:yurt'), (8.90, 0.75, [0.92, 0.52], [0.95, 0.45], 'pink', 'burst:yurt', False),
    (10.90, 1.20, [0.88, 0.06], [0.95, 0.10]), (12.80, 1.30, [0.90, 0.06], [0.95, 0.08], 'mint'), (14.80, 1.30, [0.90, 0.90], [0.95, 0.90]),
    (16.80, 1.30, [0.08, 0.52], [0.05, 0.62], 'sky'), (18.60, 1.40, [0.92, 0.90], [0.05, 0.90]), (19.00, 1.00, [0.08, 0.30], [0.55, 0.06], 'pink', 'v3', False),
    (20.80, 1.20, [0.50, 0.06], [0.50, 0.06], 'yellow'), (22.80, 1.30, [0.10, 0.08], [0.05, 0.08], 'mint'), (24.80, 1.30, [0.90, 0.06], [0.96, 0.06], 'pink'),
    (28.80, 1.30, [0.90, 0.92], [0.95, 0.92]), (30.80, 1.30, [0.92, 0.92], [0.05, 0.10], 'purple'),
    (32.50, 1.60, [0.92, 0.06], [0.95, 0.06], 'pink', 'burst:pretty'), (32.90, 1.20, [0.92, 0.45], [0.97, 0.50], 'yellow', 'burst:pretty', False),
    (34.80, 1.30, [0.50, 0.92], [0.06, 0.10]), (36.80, 1.10, [0.08, 0.90], [0.50, 0.955], 'yellow'),
    (38.30, 1.40, [0.92, 0.70], [0.50, 0.06], 'yellow', 'burst:done'), (42.40, 1.30, [0.08, 0.06], [0.92, 0.95], 'pink'),
    (44.40, 1.80, [0.10, 0.06], [0.05, 0.05], 'yellow', 'burst:group'), (44.80, 1.50, [0.62, 0.05], [0.60, 0.05], 'pink', 'burst:group', False)]:
    twk(*args)

# ---- 3d. trails: hearts or stars hopping along an edge (a9 -> b9 for 9:16, a16 -> b16 for 16:9)
trl(4.50, 1.60, [0.10, 0.56], [0.16, 0.36], [0.70, 0.58], [0.90, 0.40], 'heart')
trl(12.55, 1.50, [0.62, 0.93], [0.92, 0.80], [0.82, 0.95], [0.97, 0.80], 'star')
trl(16.45, 1.60, [0.10, 0.30], [0.40, 0.22], [0.20, 0.28], [0.34, 0.12], 'heart')
trl(22.45, 1.60, [0.12, 0.95], [0.42, 0.86], [0.84, 0.95], [0.96, 0.70], 'heart')
trl(26.50, 1.50, [0.12, 0.42], [0.18, 0.22], [0.76, 0.62], [0.97, 0.56], 'star', 'burst:V')
trl(30.55, 1.50, [0.08, 0.52], [0.30, 0.44], [0.84, 0.58], [0.97, 0.30], 'heart')
trl(45.00, 1.40, [0.10, 0.95], [0.45, 0.86], [0.82, 0.97], [0.97, 0.80], 'heart', 'burst:group')

# ---- 3e. dashed underlines under the big words (9:16 just under the word; check the 16:9 height on frames)
uline(9.95, 0.80, [0.50, 0.615], [0.50, 0.835], 0.62, 0.30, 'rose', 'burst:yurt')
uline(26.95, 0.95, [0.50, 0.785], [0.50, 0.915], 0.50, 0.30, 'yellow', 'burst:V')
uline(38.40, 0.90, [0.50, 0.63], [0.50, 0.815], 0.50, 0.26, 'mint', 'burst:done')

# ---- 3f. arrows: a hand-drawn 看! arrow at the thing to look at (the finished craft)
V3.append(st(38.60, 0.62, 'arrow', [0.20, 0.76], [0.86, 0.62], 0.05, 'burst:done', 'arrow 看！ at the finished yurt',
             sfx='swish_soft', db=-1, sfx_offset=0.12, text='看!', color='rose', width=0.019,
             to={'9x16': [0.35, 0.82], '16x9': [0.73, 0.80]},
             bend={'9x16': -0.06, '16x9': 0.06}, label_pos={'9x16': [0.11, 0.74], '16x9': [0.90, 0.55]},
             label_size={'9x16': 0.16, '16x9': 0.13}))

# ---- 3g. frames: crayon corner brackets around a proud child and the craft (box = [x0, y0, x1, y1] per aspect)
V3.append(st(40.00, 1.75, 'frame', [0.5, 0.3], [0.38, 0.35], 0.05, 'proud', 'crayon corners around the boy and his yurt',
             sfx='swish_soft', db=-1, color='yellow', box={'9x16': [0.04, 0.03, 0.97, 0.57], '16x9': [0.04, 0.02, 0.70, 0.68]},
             arm={'9x16': 0.12, '16x9': 0.14}))

# ---- 3h. balloons rising to the end on the goodbye: 9:16 in the blurred band above the group photo; 16:9 from the
#          bottom edge, at the edges while the card is up, the middle after it
BAL = [  # t, dur, colour, 9:16 x, 16:9 x
    (49.30, 2.40, 'pink', 0.10, 0.04), (49.50, 2.50, 'sky', 0.76, 0.96), (49.70, 2.40, 'yellow', 0.25, 0.16),
    (50.00, 2.20, 'mint', 0.90, 0.84), (50.80, 1.40, 'purple', 0.18, 0.36), (51.00, 1.20, 'orange', 0.84, 0.62)]
for i, (t, dur, c, x9, x16) in enumerate(BAL):
    V3.append(st(t, dur, 'balloon', [x9, 0.36], [x16, 1.08], {'9x16': 0.13, '16x9': 0.12}, 'burst:bye', f'balloon rising ({c})',
                 sfx='pop' if i == 0 else None, db=-4, color=c,
                 rise={'9x16': round(0.62 * dur / 2.4, 3), '16x9': round(0.36 * dur / 2.4, 3)}, clip={'9x16': [0, 0, 1, 0.30], '16x9': None}))
S += V3
S.sort(key=lambda d: d['t'])

# ==== 4. AVOID BOXES ==================================================================================================
# Caption cards: one box per CARD line (start, end incl. the hold); 9:16 cards sit at card_y 0.66, 16:9 at 0.82 (cc16).
# Take start / end from the 9:16 render's frames (a card holds about 0.3-0.5 s past its last word), or use
# card_lines_from_plan() below for a first guess.
CARD9, CARD16 = [0.06, 0.60, 0.94, 0.75], [0.2, 0.74, 0.8, 0.90]
CARD_LINES = [(2.35, 4.0), (4.35, 5.4), (6.3, 7.7), (10.75, 12.2), (12.3, 13.8), (14.3, 15.6), (16.3, 17.7), (18.3, 20.0),
              (20.3, 21.6), (22.3, 23.8), (24.3, 26.2), (28.3, 29.5), (30.3, 31.7), (34.3, 35.95), (36.3, 37.2), (39.95, 41.2),
              (41.95, 43.5), (43.95, 46.4), (46.55, 48.4), (49.15, 50.5)]
CARD9_LINE = {(24.3, 26.2): [0.06, 0.68, 0.94, 0.83], (30.3, 31.7): [0.06, 0.50, 0.94, 0.65]}   # lines moved by cute.json card_y


def card_lines_from_plan(plan_path=os.path.join(HERE, "plan.json"), hold=0.45):
    """First guess: every card line's (start, end + hold), never past the next line's start."""
    ls = sorted(json.load(open(plan_path, encoding="utf-8"))["lines"], key=lambda l: l["start"])
    out = []
    for i, l in enumerate(ls):
        if (l.get("kind") or "card") == "card":
            nxt = ls[i + 1]["start"] if i + 1 < len(ls) else END
            out.append((l["start"], round(min(l["end"] + hold, nxt - 0.05), 2)))
    return out


A = []
for a, b in CARD_LINES:
    A.append({'start': a, 'end': b + 0.35, 'what': 'caption card', 'box': {'9x16': CARD9_LINE.get((a, b), CARD9), '16x9': CARD16}})
# Big type (both sizes; 16:9 boxes follow layout16.json)
A += [{'start': 0.1, 'end': 2.2, 'what': 'hook rows', 'box': {'9x16': [0.15, 0.48, 0.85, 0.80], '16x9': [0.04, 0.70, 0.38, 0.94]}},
      {'start': 9.7, 'end': 10.95, 'what': 'write-on 蒙古包', 'box': {'9x16': [0.05, 0.42, 0.95, 0.60], '16x9': [0.3, 0.58, 0.7, 0.82]}},
      {'start': 26.6, 'end': 27.9, 'what': 'punch 比个V', 'box': {'9x16': [0.05, 0.57, 0.95, 0.76], '16x9': [0.3, 0.70, 0.7, 0.90]}},
      {'start': 32.9, 'end': 34.0, 'what': 'write-on 好漂亮', 'box': {'9x16': [0.05, 0.58, 0.95, 0.77], '16x9': [0.3, 0.58, 0.7, 0.82]}},
      {'start': 38.2, 'end': 39.3, 'what': 'punch 完成啦', 'box': {'9x16': [0.08, 0.46, 0.92, 0.62], '16x9': [0.3, 0.60, 0.7, 0.80]}}]
# Faces, 9:16: start, end, box, what. By eye on the 9:16 frames (stickers.py sheet --every 0.5); boxes take the whole head
# and hair, and widen where the camera pans. Group photos: the whole picture band.
FACES9 = [
    (0.0, 2.2, [0.05, 0.08, 0.62, 0.42], 'boy with the yurt hat'), (0.0, 2.2, [0.74, 0.08, 1.0, 0.3], 'boy top right'),
    (0.0, 2.25, [0.86, 0.35, 1.0, 0.65], 'girl at the right edge'),
    (4.2, 6.2, [0.25, 0.0, 0.75, 0.32], 'teacher'), (6.2, 8.2, [0.3, 0.02, 0.65, 0.24], 'girl with a drink'),
    (10.2, 12.2, [0.22, 0.03, 0.62, 0.35], 'leader'), (12.2, 14.2, [0.3, 0.05, 0.72, 0.32], 'girl walking'),
    (14.2, 16.2, [0.28, 0.05, 1.0, 0.47], 'toddler (mouth and the whole head)'), (22.2, 24.2, [0.28, 0.28, 0.9, 0.52], 'boy in blue'),
    (24.2, 26.2, [0.1, 0.36, 0.5, 0.66], 'little girl (to her chin)'), (26.2, 28.2, [0.22, 0.03, 0.78, 0.34], 'boy in orange'),
    (28.2, 30.2, [0.28, 0.15, 0.72, 0.42], 'girl in a mask'), (30.2, 32.2, [0.42, 0.08, 0.88, 0.58], 'grandma and child'),
    (32.2, 34.2, [0.28, 0.02, 0.72, 0.32], 'girl with the roof'), (34.2, 36.2, [0.08, 0.0, 0.98, 0.5], 'mum and baby'),
    (36.2, 38.0, [0.28, 0.0, 0.92, 0.42], 'boy finishing'), (38.0, 39.8, [0.38, 0.18, 0.72, 0.34], 'woman in a cap'),
    (39.8, 41.8, [0.32, 0.03, 0.82, 0.37], 'boy with his yurt'), (41.8, 43.8, [0.0, 0.12, 0.72, 0.36], 'children close up'),
    (43.8, 52.2, [0.0, 0.30, 1.0, 0.66], 'group photo (whole picture band)'),
    (24.2, 26.2, [0.0, 0.0, 0.30, 0.12], 'woman at the top left'), (30.2, 32.2, [0.0, 0.0, 0.38, 0.24], 'woman at the left'),
    (34.2, 36.2, [0.40, 0.30, 1.0, 0.60], 'baby')]
for a, b, box, what in FACES9:
    A.append({'start': a, 'end': b, 'what': f'face: {what}', 'box': {'9x16': box}})
# Faces, 16:9: the same, on the 16:9 frames (the landscape frame shows more people: check the edges too)
FACES16 = [
    (0.0, 2.2, [0.14, 0.12, 0.42, 0.62], 'left boy with the yurt hat'), (0.0, 2.2, [0.44, 0.30, 0.74, 0.86], 'right boy with the yurt hat'),
    (4.2, 6.2, [0.25, 0.0, 0.60, 0.45], 'teacher'), (4.2, 6.2, [0.0, 0.38, 0.20, 0.70], 'girl with a snack'),
    (6.2, 8.2, [0.40, 0.08, 0.65, 0.45], 'girl with a drink'), (6.2, 8.2, [0.66, 0.0, 0.92, 0.40], 'boy drinking'),
    (6.2, 8.2, [0.0, 0.08, 0.16, 0.50], 'toddler'),
    (10.2, 12.2, [0.38, 0.03, 0.64, 0.45], 'leader'), (10.2, 12.2, [0.0, 0.08, 0.16, 0.50], 'man at the left'),
    (12.2, 14.2, [0.12, 0.08, 0.56, 0.58], 'girl walking'),
    (14.2, 16.2, [0.24, 0.08, 0.62, 0.55], 'toddler'), (14.2, 16.2, [0.80, 0.50, 1.0, 0.82], 'girl with glasses'),
    (16.2, 18.2, [0.38, 0.0, 0.90, 0.42], 'girl in pink'), (18.2, 20.2, [0.74, 0.0, 1.0, 0.62], 'boy in red'),
    (22.2, 24.2, [0.12, 0.18, 0.42, 0.58], 'boy in blue'), (22.2, 24.2, [0.48, 0.0, 0.92, 0.36], 'helpers'),
    (24.2, 26.2, [0.18, 0.0, 0.62, 0.28], 'grandma'), (24.2, 26.2, [0.42, 0.36, 0.82, 0.86], 'little girl'),
    (26.2, 28.2, [0.38, 0.0, 0.70, 0.55], 'boy in orange'), (26.2, 28.2, [0.08, 0.15, 0.32, 0.58], 'small boy'),
    (28.2, 30.2, [0.0, 0.32, 0.38, 0.88], 'girl in a mask'), (28.2, 30.2, [0.62, 0.0, 0.96, 0.42], 'helper'),
    (30.2, 32.2, [0.18, 0.0, 0.80, 0.62], 'grandma and child'), (32.2, 34.2, [0.28, 0.0, 0.78, 0.42], 'girl with the roof'),
    (34.2, 36.2, [0.18, 0.0, 0.86, 0.80], 'mum and baby'), (36.2, 38.0, [0.0, 0.0, 0.48, 0.86], 'boy finishing'),
    (36.2, 38.0, [0.55, 0.0, 0.90, 0.30], 'girl in a cap and helper'),
    (38.0, 39.8, [0.42, 0.18, 0.62, 0.48], 'woman in a cap'),
    (39.2, 39.8, [0.875, 0.09, 1.0, 0.28], 'woman in green leaning in'), (39.8, 41.8, [0.12, 0.0, 0.62, 0.48], 'boy with his yurt (widened: the camera pans)'),
    (29.3, 30.2, [0.36, 0.04, 0.58, 0.60], "masked girl's head (the camera brings her in)"),
    (41.8, 43.8, [0.0, 0.08, 0.86, 0.72], 'children close up'), (43.8, 52.2, [0.0, 0.18, 1.0, 0.64], 'group photo (faces band)')]
for a, b, box, what in FACES16:
    A.append({'start': a, 'end': b, 'what': f'face (16:9): {what}', 'box': {'16x9': box}})
# Faces found by tools/vision/faces.py (t202, SKILL.md step 8): every faces*.json beside shots.json (faces916.json,
# faces16.json, or one faces.json) adds its face ranges for the aspect it was detected on. The typed FACES9 / FACES16
# rows above stay as extras (a face the detector misses: masks, backs of heads, faces cut by the edge).
sys.path.insert(0, SKILL)
import stickers as SK  # noqa: E402
FACE_FILES = sorted(f for f in os.listdir(os.path.dirname(SHOTS)) if f.startswith('faces') and f.endswith('.json'))
_used = []
for _fn in FACE_FILES:
    try:                                   # skip anything that is not a faces.py output (e.g. a faces_check report)
        A += SK.faces_avoid(os.path.join(os.path.dirname(SHOTS), _fn)); _used.append(_fn)
    except (ValueError, KeyError, TypeError) as _e:
        print(json.dumps({'warning': f'{_fn} skipped: not a faces.json ({_e})'}, ensure_ascii=False))
FACE_FILES = _used
if not FACE_FILES:
    print(json.dumps({'warning': 'no faces*.json beside shots.json: only the typed FACES9 / FACES16 boxes are avoided '
                                 '(run tools/vision/faces.py first, SKILL.md step 8)'}, ensure_ascii=False))

# The video's own sound events to change (the caption render's sfx-events, by frame): e.g. a write-on swish the voice masks
SFX_ADJUST = [{'frame': 989, 'sound': 'chime', 'db': -1, 'why': 'write-on swish under 好漂亮 masked by the voice; a reveal chime instead'}]

# ==== 5. FIT + WRITE ==================================================================================================
FIT = []
for d in S:
    if d['kind'] != 'bubble':
        continue
    for key, (W, H) in {'9x16': (1080, 1920), '16x9': (1920, 1080)}.items():
        lo = d['size'][key] / BUBX[key] * 0.85
        while True:
            _, warns, _ = SK.check({'avoid': A, 'stickers': [d]}, [SK.Sticker(d, 0)], W, H)
            if not warns or d['size'][key] * 0.94 < lo:
                break
            d['size'][key] = round(d['size'][key] * 0.94, 3)
        if warns:
            FIT.append(f"{key} {d['what']} at {d['t']}: {warns[0]}")
if FIT:
    print(json.dumps({'bubbles_not_fitted': FIT}, ensure_ascii=False))

spec = {'note': NOTE, 'max_on_screen': 4, 'avoid': A, 'sfx_adjust': SFX_ADJUST, 'stickers': S}
with open(DEST, 'w', encoding='utf-8') as f:
    json.dump(spec, f, ensure_ascii=False, indent=1)
print(json.dumps({'ok': True, 'out': os.path.normpath(DEST), 'stickers': len(S), 'avoid': len(A),
                  'next': 'stickers.py plan <stickers.json>, then render, then sheet'}, ensure_ascii=False))
