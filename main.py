import sys
import math
import random
import array
import json
import os
import datetime
import wave
import hashlib
import tempfile
import subprocess
import time

try:
    import pygame
except ImportError:
    print("لازم تنزّل المكتبات:  pip install pygame arabic-reshaper python-bidi")
    sys.exit(1)
try:
    import arabic_reshaper
    try:
        from bidi import get_display
    except ImportError:
        from bidi.algorithm import get_display
except ImportError:
    print("لازم تنزّل المكتبات:  pip install pygame arabic-reshaper python-bidi")
    sys.exit(1)

import netplay                                  # اللعب الأونلاين على الشبكة المحلية (LAN)

# ================================================================= إعدادات
SW, SH = 960, 640
T = 32
MAX_LEVEL = 10
FOOTSTEP_VOL = 0.10                    # صوت خطوات اللاعب (0 = بدون صوت)
FEAR_DEATH = 100.0                     # (أونلاين) لو شريط الخوف وصل للرقم ده اللاعب بيموت
PCOL = [(120, 18, 30), (40, 110, 190), (40, 150, 70), (200, 140, 30),       # ألوان اللاعبين (8)
        (130, 60, 170), (30, 160, 160), (200, 80, 130), (110, 110, 118)]
BDAY_TEXT = "Happy New Year!"          # الجملة اللي الوحش بيقولها يوم الميلاد
# ---- المنصّة: أندرويد / ويندوز (EXE) / تشغيل عادي
ANDROID = 'ANDROID_ARGUMENT' in os.environ or 'ANDROID_PRIVATE' in os.environ
FROZEN = getattr(sys, 'frozen', False)
TOUCH = ANDROID or ('--touch' in sys.argv)           # وضع اللمس: موبايل، أو تجربة على الكمبيوتر بـ --touch
BASE_DIR = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))   # ملفات اللعبة (assets)
if ANDROID:
    APP_DIR = os.environ.get('ANDROID_PRIVATE') or BASE_DIR        # مكان الحفظ على الموبايل
elif FROZEN:
    APP_DIR = os.path.dirname(sys.executable)                      # الحفظ جنب الـ EXE (مش الفولدر المؤقت)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))


def asset(name):
    return os.path.join(BASE_DIR, "assets", name)


SAVE_FILE = os.path.join(APP_DIR, "savegame.json")


LANG = 'ar'                       # اللغة الحالية: 'ar' أو 'en'  (زرار اللغة في القايمة أو حرف L)
EN = {}                           # القاموس: النص العربي -> الإنجليزي (في آخر الملف)


def tr(s):
    return EN.get(s, s) if LANG == 'en' else s


class S:
    """نص بيتترجم لوحده حسب اللغة الحالية"""

    def __init__(self, key, **kw):
        self.key, self.kw = key, kw

    def __str__(self):
        t = str(tr(self.key))
        if not self.kw:
            return t
        return t.format(**{k: (str(v) if isinstance(v, S) else tr(v) if isinstance(v, str) else v)
                           for k, v in self.kw.items()})


def diff(n):
    """الصعوبة بتزيد مع كل مرحلة"""
    return dict(cd=max(8.0, 24 - 1.7 * n),           # أقل فاصل بين خضّتين
                gmax=1 + (n >= 6) + (n >= 9),         # عدد الأشباح مع بعض
                gcd=max(10.0, 45 - 3.2 * n),          # وقت ظهور الشبح
                gspd=5 * n,                           # سرعة الشبح
                drain=0.6 * (1 + 0.05 * n),           # سرعة سحب بطارية الكشاف
                   amb=max(9.0, 28 - 2.2 * n))          # الأصوات العشوائية


# ================================================================= الأوض والأثاث
class Level:
    pass


class Obj:
    def __init__(self, oid, name, tx, ty, tw, th, color, solid=True, **kw):
        self.id, self.name = oid, name
        self.rect = pygame.Rect(tx * T, ty * T, tw * T, th * T)
        self.color, self.solid, self.can = color, solid, True
        self.kind = 'flavor'
        self.title = name
        self.text = ["مفيش حاجة هنا... بس حاسس إن حد بيبصلك."]
        self.give = self.need = self.scare = None
        self.finale = False
        self.lines = self.locked = []
        self.empty = "فاضي."
        self.toast = ""
        self.sp = None
        self.where = ""
        self.__dict__.update(kw)


GENERIC_FLAVOR = [
    ["مفيش حاجة هنا... بس حاسس إن حد بيبصلك."],
    ["الغبار هنا لسه مهزوز... حد لمس المكان من لحظة."],
    ["سمعت همس خفيف طالع من هنا."],
    ["ريحة رطوبة تقيلة... وحاجة تانية أوحش."],
    ["فيه بصمة إيد صغيرة على السطح."],
    ["فيه خربشة على الخشب: \"اخرج\"."],
    ["مفيش حاجة جوه... بس كان فيه حد هنا."],
    ["حاسس إن المكان ده اتحرّك ورايا... مش متأكد."],
]

# ---------------- المرحلة 1 (بيت مرسوم باليد) ----------------
ROOMS1 = [
    ("الصالة", (16, 16, 8, 8), (74, 52, 38)),
    ("أوضة المعيشة", (2, 16, 12, 8), (68, 50, 60)),
    ("المطبخ", (26, 16, 12, 8), (98, 98, 92)),
    ("أوضة النوم", (2, 2, 10, 7), (64, 44, 50)),
    ("المكتبة", (14, 2, 10, 7), (62, 46, 30)),
    ("المكتب", (26, 2, 12, 7), (40, 58, 54)),
    ("الممر", (2, 11, 36, 3), (54, 46, 42)),
]
DOORS1 = [(14, 19, 2, 2), (24, 19, 2, 2), (7, 14, 2, 2), (19, 14, 2, 2),
          (33, 14, 2, 2), (6, 9, 2, 2), (18, 9, 2, 2), (31, 9, 2, 2), (19, 24, 2, 1)]
RUGS1 = [(18, 18, 4, 3, (84, 28, 28)), (4, 5, 5, 3, (56, 34, 70)),
         (17, 4, 4, 3, (30, 60, 70)), (28, 5, 6, 3, (70, 40, 30)), (5, 18, 3, 2, (40, 60, 50))]
CANDLES1 = [(16, 17), (13, 17), (11, 8), (14, 8), (37, 8), (37, 23), (2, 12), (37, 12)]

TEXTS1 = {
    'hall_table': ("ورقة على الترابيزة", [
        "ورقة مكتوبة بخط مرتعش:",
        "\"الباب الكبير اتقفل لوحده... ومش هيتفتح غير بمفتاحه.",
        "المفتاح في المكتب اللي فوق، والمكتب مقفول.",
        "دوّر كويس... وماتبصّش ورا.\""]),
    'bookshelf_l': ("ورقة بين الكتب", [
        "لقيت ورقة قديمة:",
        "\"المفتاح النحاسي بتاع المكتب كنت دايمًا",
        "أخبّيه في دولاب أوضة النوم.\""]),
    'nightstand': ("مذكرات قديمة", [
        "\"كل ليلة بسمع خطوات قدام باب الأوضة.",
        "النهارده الخطوات وقفت... جوه الأوضة.\"",
        "آخر صفحة متبلّلة بحاجة حمرا..."]),
    'lib_desk': ("ورقة على المكتب", [
        "\"درج المكتب الكبير مفتاحه صغير.",
        "كنت بحطه في حتة باردة... في المطبخ.\""]),
    'bed': ("السرير", ["السرير متبهدل... والملاية لسه دافية!"]),
    'coffee_table': ("ترابيزة القهوة", ["كوباية شاي على الترابيزة... ولسه بتطلّع بخار."]),
    'stove': ("البوتجاز", ["البوتجاز بارد... بس سامع صوت غليان من جوه الحلّة!"]),
    'k_table': ("ترابيزة السفرة", ["حوالين الترابيزة أربع كراسي. الكرسي الرابع لسه بيهتز."]),
    'sink': ("الحوض", ["الحنفية بتنقّط... والميّه لونها مش طبيعي."]),
    'shelf_1': ("الكتب", ["كل الكتب دي عن الأرواح والأحلام المزعجة."]),
    'shelf_2': ("الكتب", ["كتاب مفتوح على صفحة مكتوب فيها: \"هو شايفك\"."]),
    'chair': ("الكرسي الهزّاز", ["الكرسي بيهتز لوحده... بعدت عنه بسرعة."]),
    'safe': ("الخزنة", ["خزنة محتاجة رقم سري، ومفيش حاجة هنا تفتحها."]),
}
BATTERY1 = {'sofa': "تحت وسادة الكنبة", 'drawer': "في الدرج", 'shelf_3': "ورا الكتب",
            'cabinet': "في الدولاب العلوي", 'study_shelf': "بين الكتب"}

SP1 = {
    'wardrobe': dict(kind='container', give='ka', scare='face', title="الدولاب",
                     lines=["جوه الدولاب لقيت مفتاح نحاسي تقيل.", "ده مفتاح المكتب."],
                     empty="الدولاب فاضي دلوقتي."),
    'fridge': dict(kind='container', give='small', scare='flicker', title="التلاجة",
                   lines=["التلاجة ريحتها وحشة...", "لقيت مفتاح صغير متلزّق في الباب من جوه."],
                   empty="التلاجة فاضية... وريحتها وحشة."),
    'desk': dict(kind='container', need='small', give='exit', finale=True, title="مكتب كبير",
                 locked=["الدرج الكبير مقفول بقفل صغير.", "محتاج مفتاح صغير."],
                 lines=["فتحت الدرج بالمفتاح الصغير...",
                        "لقيت مفتاح كبير صدّي: مفتاح الباب الأمامي!",
                        "يلا اجري على الباب!"],
                 empty="الدرج فاضي دلوقتي."),
    'study_door': dict(kind='door', need='ka', title="باب المكتب", toast="فتحت باب المكتب!",
                       locked=["الباب مقفول بمفتاح نحاسي.", "لازم تلاقيه."]),
    'front_door': dict(kind='exit', need='exit', title="الباب الأمامي",
                       locked=["الباب تقيل ومقفول بإحكام.", "محتاج مفتاحه... ومش معاك."]),
    'piano': dict(kind='special', sp='piano'),
    'portrait': dict(kind='special', sp='portrait'),
    'mirror': dict(kind='special', sp='mirror'),
    'doll': dict(kind='special', sp='doll'),
}


def build_objs1():
    O = []

    def add(*a):
        O.append(Obj(*a))
    add('hall_table', "الترابيزة", 21, 17, 2, 1, (104, 66, 34))
    add('front_door', "الباب الأمامي", 19, 24, 2, 1, (110, 30, 30))
    add('bookshelf_l', "المكتبة الصغيرة", 2, 16, 3, 1, (80, 50, 28))
    add('sofa', "الكنبة", 3, 21, 4, 2, (110, 56, 90))
    add('coffee_table', "ترابيزة القهوة", 4, 19, 2, 1, (96, 62, 36))
    add('piano', "البيانو", 9, 21, 3, 2, (24, 24, 28))
    add('bed', "السرير", 3, 3, 3, 2, (130, 70, 70))
    add('nightstand', "الكومودينو", 6, 3, 1, 1, (100, 66, 40))
    add('wardrobe', "الدولاب", 9, 2, 2, 1, (88, 54, 30))
    add('drawer', "الدُرج", 2, 7, 2, 1, (96, 62, 36))
    add('shelf_1', "رف الكتب", 14, 2, 3, 1, (76, 48, 26))
    add('shelf_2', "رف الكتب", 17, 2, 3, 1, (76, 48, 26))
    add('shelf_3', "رف الكتب", 21, 2, 3, 1, (76, 48, 26))
    add('lib_desk', "مكتب المكتبة", 20, 6, 3, 2, (96, 62, 36))
    add('chair', "كرسي هزّاز", 15, 5, 2, 2, (120, 80, 50))
    add('stove', "البوتجاز", 27, 16, 3, 1, (74, 74, 80))
    add('fridge', "التلاجة", 30, 16, 2, 1, (196, 200, 206))
    add('cabinet', "الدولاب العلوي", 36, 16, 2, 1, (120, 84, 50))
    add('sink', "الحوض", 26, 22, 2, 1, (150, 156, 160))
    add('k_table', "ترابيزة السفرة", 30, 20, 3, 2, (110, 74, 44))
    add('study_door', "باب المكتب - مقفول", 31, 10, 2, 1, (112, 72, 30))
    add('desk', "مكتب كبير", 30, 3, 4, 2, (92, 58, 32))
    add('safe', "الخزنة", 26, 3, 1, 2, (60, 60, 66))
    add('portrait', "الصورة الكبيرة", 28, 2, 2, 1, (120, 100, 40))
    add('study_shelf', "رف الكتب", 35, 2, 3, 1, (76, 48, 26))
    add('mirror', "المراية الكبيرة", 22, 16, 2, 1, (170, 190, 200))
    add('doll', "الدُمية الكبيرة", 10, 7, 1, 1, (200, 150, 160))
    for o in O:
        if o.id in TEXTS1:
            o.kind, (o.title, o.text) = 'note', TEXTS1[o.id]
        elif o.id in BATTERY1:
            o.kind, o.where = 'battery', BATTERY1[o.id]
        elif o.id in SP1:
            o.__dict__.update(SP1[o.id])
    return O


def build_level1():
    lv = Level()
    lv.n, lv.W, lv.H = 1, 40, 26
    lv.title = "البيت القديم"
    lv.grid = [[1] * lv.W for _ in range(lv.H)]
    lv.floorc = [[(0, 0, 0)] * lv.W for _ in range(lv.H)]

    def carve(x, y, w, h, c):
        for j in range(y, y + h):
            for i in range(x, x + w):
                lv.grid[j][i] = 0
                lv.floorc[j][i] = c
    for _n, (x, y, w, h), c in ROOMS1:
        carve(x, y, w, h, c)
    for d in DOORS1:
        carve(*d, (58, 48, 40))
    lv.rooms = ROOMS1
    lv.rugs = RUGS1
    lv.candles = CANDLES1
    lv.objs = build_objs1()
    lv.triggers = [dict(rect=pygame.Rect(a * T, b * T, c * T, d * T), kind=k, fired=False)
                   for a, b, c, d, k in [(10, 11, 3, 3, 'flicker'), (16, 4, 5, 2, 'bang'),
                                         (25, 11, 3, 3, 'face'), (27, 19, 5, 3, 'bang'),
                                         (4, 6, 4, 2, 'flicker'), (8, 18, 3, 2, 'face'),
                                         (17, 11, 3, 3, 'dash'), (4, 11, 3, 3, 'eyes'),
                                         (33, 11, 3, 3, 'watch'), (21, 19, 2, 2, 'knock'),
                                         (8, 4, 3, 2, 'name')]]
    lv.floors = [(i, j) for j in range(lv.H) for i in range(lv.W) if lv.grid[j][i] == 0]
    lv.start = (20 * T + 16, 21 * T + 16)
    lv.item_names = {'ka': "مفتاح المكتب النحاسي", 'small': "المفتاح الصغير", 'exit': "مفتاح الباب الأمامي"}

    def goal(g):
        if 'exit' in g.inv:
            return "اهرب من الباب الأمامي!"
        if 'study_door' in g.opened:
            return "افتح درج المكتب" if 'small' in g.inv else "دوّر على مفتاح صغير للدرج"
        if 'ka' in g.inv:
            return "افتح باب المكتب، فوق ناحية اليمين"
        return "دوّر على مفتاح المكتب النحاسي"
    lv.goal = goal
    return lv


# ---------------- المراحل 2..10 (بتتولّد تلقائي) ----------------
DIMS = {2: (3, 2), 3: (3, 3), 4: (4, 3), 5: (5, 3), 6: (4, 4), 7: (5, 4), 8: (6, 4), 9: (5, 5), 10: (6, 5)}
RW, RH = 9, 7
NAMES = ["أوضة النوم", "المكتبة", "المطبخ", "الصالة", "الحمّام", "أوضة الأطفال", "المخزن", "أوضة الضيوف",
         "السفرة", "البدروم", "العلّية", "المكتب", "أوضة الغسيل", "الشرفة", "أوضة الخياطة", "أوضة الموسيقى",
         "المرسم", "الطرقة الكبيرة", "أوضة الأجداد", "أوضة الصلاة", "غرفة الكتب القديمة", "أوضة الألعاب",
         "الأنتريه", "المخبأ", "غرفة المراية", "مخزن الخشب", "أوضة الساعة", "غرفة المرضى", "القبو",
         "أوضة الضوء الأحمر", "غرفة الدُمى", "أوضة السفرجي", "غرفة النجف"]
FURN = [("السرير", 3, 2, (130, 70, 70)), ("الدولاب", 2, 1, (88, 54, 30)), ("الكومودينو", 1, 1, (100, 66, 40)),
        ("المكتب", 3, 2, (96, 62, 36)), ("رف الكتب", 3, 1, (76, 48, 26)), ("الكنبة", 3, 1, (110, 56, 90)),
        ("الترابيزة", 2, 1, (104, 66, 34)), ("الصندوق الخشب", 1, 1, (110, 80, 40)),
        ("التلاجة", 1, 1, (196, 200, 206)), ("الخزانة", 2, 1, (80, 60, 40)), ("البيانو", 2, 2, (24, 24, 28)),
        ("الكرسي الهزّاز", 1, 1, (120, 80, 50)), ("الدُرج", 2, 1, (96, 62, 36)),
        ("المراية الكبيرة", 1, 1, (170, 190, 200)), ("الصورة", 2, 1, (120, 100, 40)),
        ("الدُمية الكبيرة", 1, 1, (200, 150, 160))]
PALETTE = [(74, 52, 38), (68, 50, 60), (98, 98, 92), (64, 44, 50), (62, 46, 30), (40, 58, 54),
           (60, 52, 70), (80, 60, 48), (52, 62, 52), (88, 70, 60)]
RUGCOL = [(84, 28, 28), (56, 34, 70), (30, 60, 70), (70, 40, 30), (40, 60, 50)]


def gen_level(n, seed):
    rng = random.Random(seed * 100 + n)
    srng = random.Random(seed * 31 + n)          # عشوائية منفصلة للخضّات (علشان شكل البيت ما يتغيّرش)
    cols, rows = DIMS[n]
    lv = Level()
    lv.n, lv.title = n, S("الشقة {n}", n=n)
    lv.W, lv.H = 2 + cols * (RW + 2), 2 + rows * (RH + 2)
    lv.grid = [[1] * lv.W for _ in range(lv.H)]
    lv.floorc = [[(0, 0, 0)] * lv.W for _ in range(lv.H)]
    dark_f = 1 - 0.04 * n

    def carve(x, y, w, h, c):
        for j in range(y, y + h):
            for i in range(x, x + w):
                lv.grid[j][i] = 0
                lv.floorc[j][i] = c

    def org(c, r):
        return 2 + c * (RW + 2), 2 + r * (RH + 2)

    names = NAMES[:]
    rng.shuffle(names)
    cells = [(c, r) for r in range(rows) for c in range(cols)]
    cell = {}
    for i, cr in enumerate(cells):
        x0, y0 = org(*cr)
        col = tuple(int(v * dark_f) for v in rng.choice(PALETTE))
        nm = names[i] if i < len(names) else S("أوضة {n}", n=i + 1)
        cell[cr] = dict(name=nm, x0=x0, y0=y0, col=col)
        carve(x0, y0, RW, RH, col)
    lv.rooms = [(v['name'], (v['x0'], v['y0'], RW, RH), v['col']) for v in cell.values()]

    # شجرة الأوض (متاهة)
    start = (cols // 2, rows - 1)
    seen, stack, edges = {start}, [start], []
    while stack:
        cur = stack[-1]
        nb = [(cur[0] + dc, cur[1] + dr) for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))
              if 0 <= cur[0] + dc < cols and 0 <= cur[1] + dr < rows and (cur[0] + dc, cur[1] + dr) not in seen]
        if nb:
            nx = rng.choice(nb)
            seen.add(nx)
            edges.append((cur, nx))
            stack.append(nx)
        else:
            stack.pop()
    deg = {c: 0 for c in cells}
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
    leaves = [c for c in cells if deg[c] == 1 and c != start]
    rng.shuffle(leaves)
    locks = leaves[:2] if (n >= 7 and len(leaves) >= 2) else leaves[:1]
    A = locks[0]
    B = locks[1] if len(locks) > 1 else None

    # أبواب إضافية (لفّات)
    lockset = set(locks)
    pairs = []
    es = set(edges) | set((b, a) for a, b in edges)
    for (c, r) in cells:
        for dc, dr in ((1, 0), (0, 1)):
            o2 = (c + dc, r + dr)
            if o2 in cell and ((c, r), o2) not in es and (c, r) not in lockset and o2 not in lockset:
                pairs.append(((c, r), o2))
    rng.shuffle(pairs)
    all_edges = list(edges) + pairs[:len(cells) // 4]

    def gap(a, b):
        (c1, r1), (c2, r2) = a, b
        if r1 == r2:
            left = a if c1 < c2 else b
            lx, ly = org(*left)
            return (lx + RW, ly + 3, 2, 2)
        top = a if r1 < r2 else b
        tx, ty = org(*top)
        return (tx + 4, ty + RH, 2, 2)

    doorzones = {c: [] for c in cells}
    objs = []
    for a, b in all_edges:
        g = gap(a, b)
        carve(*g, (58, 48, 40))
        doorzones[a].append(pygame.Rect(g))
        doorzones[b].append(pygame.Rect(g))

    def lock_door(room, parent, oid, need, nm):
        g = gap(parent, room)
        gx, gy, gw, gh = g
        if parent[1] == room[1]:   # جنب بعض
            col_ = gx + 1 if room[0] > parent[0] else gx
            rect = (col_, gy, 1, 2)
        else:
            row_ = gy + 1 if room[1] > parent[1] else gy
            rect = (gx, row_, 2, 1)
        o = Obj(oid, S("باب {r} - مقفول", r=nm), *rect, (112, 72, 30), kind='door', need=need,
                title=S("باب {r}", r=nm), toast=S("فتحت باب {r}!", r=nm),
                locked=["الباب مقفول بقفل تقيل.", S("محتاج مفتاح {r}.", r=nm)])
        objs.append(o)
        return o

    def parent_of(c):
        for a, b in edges:
            if b == c:
                return a
            if a == c:
                return b

    dA = lock_door(A, parent_of(A), 'dA', 'ka', cell[A]['name'])
    if B:
        lock_door(B, parent_of(B), 'dB', 'kb', cell[B]['name'])

    # BFS للبعد عن البداية
    adj = {c: [] for c in cells}
    for a, b in all_edges:
        adj[a].append(b)
        adj[b].append(a)
    dist, q = {start: 0}, [start]
    for cur in q:
        for nx in adj[cur]:
            if nx not in dist:
                dist[nx] = dist[cur] + 1
                q.append(nx)
    border = [c for c in cells if c not in lockset and c != start and
              (c[0] in (0, cols - 1) or c[1] in (0, rows - 1))]
    border.sort(key=lambda c: -dist.get(c, 0))
    E = border[0]
    x0, y0 = cell[E]['x0'], cell[E]['y0']
    if E[1] == 0:
        er = (x0 + 4, y0 - 1, 2, 1)
    elif E[1] == rows - 1:
        er = (x0 + 4, y0 + RH, 2, 1)
    elif E[0] == 0:
        er = (x0 - 1, y0 + 3, 1, 2)
    else:
        er = (x0 + RW, y0 + 3, 1, 2)
    carve(*er, (58, 48, 40))
    doorzones[E].append(pygame.Rect(er))
    objs.append(Obj('exit', "باب الشقة", *er, (110, 30, 30), kind='exit', need='exit', title="باب الشقة",
                    locked=["الباب تقيل ومقفول بإحكام.", "محتاج مفتاح الشقة... ومش معاك."]))

    # أثاث
    furn = {c: [] for c in cells}
    cnt = [0]

    def place(cr, tries=60):
        v = cell[cr]
        x0, y0 = v['x0'], v['y0']
        nm, w, h, col = rng.choice(FURN)
        cands = []
        for (ww, hh) in ((w, h), (h, w)):
            if (ww, hh) == (w, h):
                for x in range(x0, x0 + RW - ww + 1):
                    cands += [(x, y0, ww, hh), (x, y0 + RH - hh, ww, hh)]
            else:
                for y in range(y0, y0 + RH - hh + 1):
                    cands += [(x0, y, ww, hh), (x0 + RW - ww, y, ww, hh)]
        rng.shuffle(cands)
        zones = [pygame.Rect(z.x - 2, z.y - 2, z.w + 4, z.h + 4) for z in doorzones[cr]]
        sp = pygame.Rect(x0 + RW // 2 - 1, y0 + RH // 2 - 1, 3, 3)
        for c in cands:
            r = pygame.Rect(c)
            if any(r.colliderect(z) for z in zones) or r.colliderect(sp):
                continue
            if any(r.inflate(2, 2).colliderect(pygame.Rect(o.rect.x // T, o.rect.y // T, o.rect.w // T, o.rect.h // T))
                   for o in furn[cr]):
                continue
            cnt[0] += 1
            o = Obj('g%d' % cnt[0], nm, c[0], c[1], c[2], c[3], col)
            o.text = rng.choice(GENERIC_FLAVOR)
            o.room = v['name']
            furn[cr].append(o)
            return o
        return None

    for cr in cells:
        for _ in range(rng.randint(3, 5)):
            place(cr)
    for lk in locks:
        while len(furn[lk]) < 2:
            if not place(lk):
                break
    if not furn[A]:
        o = place(A, 200)
    free_cells = [c for c in cells if c not in lockset]
    pool = [o for c in free_cells for o in furn[c]]
    rng.shuffle(pool)
    names_i = {'ka': S("مفتاح {r}", r=cell[A]['name']), 'exit': "مفتاح الشقة", 'small': "المفتاح الصغير"}
    if B:
        names_i['kb'] = S("مفتاح {r}", r=cell[B]['name'])

    def hint(o):
        return S("في {f} في {r}", f=o.name, r=o.room) if n < 5 else S("في {r}", r=o.room)

    def mk(o, give, need=None, finale=False):
        o.kind, o.give, o.need, o.finale = 'container', give, need, finale
        o.lines = [S("فتحت {f}...", f=o.name), S("ولقيت {k}!", k=names_i[give])]
        o.locked = [S("فيه قفل صغير على {f}.", f=o.name), "محتاج مفتاح صغير."]
        o.empty = "فاضي دلوقتي."
        if not finale and n >= 2:                     # خضّة وإنت بتاخد المفتاح
            o.scare = srng.choice(['face', 'flicker', 'flicker', 'bang', 'bang', 'dash', 'near'])

    nm_ = lv.item_names = names_i
    cE = rng.choice(furn[A]) if furn[A] else pool.pop()
    mk(cE, 'exit', finale=True)
    cKa = pool.pop()
    mk(cKa, 'ka', need='small' if n >= 4 else None)
    notes = []
    notes.append([S("المفتاح الكبير بتاع الشقة جوّه {r}.", r=cell[A]['name']), "والأوضة مقفولة، وعلى بابها قفل تقيل."])
    notes.append([S("مفتاح {r} مخبّي {h}.", r=cell[A]['name'], h=hint(cKa))])
    if n >= 4:
        if B and furn[B]:
            cS = rng.choice(furn[B])
            cKb = pool.pop()
            mk(cKb, 'kb')
            notes.append([S("مفتاح {r} {h}.", r=cell[B]['name'], h=hint(cKb))])
        else:
            cS = pool.pop()
        mk(cS, 'small')
        notes.append([S("المفتاح الصغير بتاع الدُرج... {h}.", h=hint(cS))])
    for nl in notes:
        if not pool:
            break
        o = pool.pop()
        o.kind, o.title, o.text = 'note', "ورقة مرمية", ["ورقة مكتوبة بخط مرتعش:"] + nl + (
            ["...ومكتوب في آخرها: \"{name}\""] if n >= 4 else [])
    nb = 3 + len(cells) // 3
    for o in pool[:nb]:
        o.kind, o.where = 'battery', S("جوه {f}", f=o.name)
    objs += [o for c in cells for o in furn[c]]
    for o in objs:                                # الأثاث اللي بيعمل رعب لوحده
        if o.kind == 'flavor':
            if o.name == "المراية الكبيرة":
                o.kind, o.sp = 'special', 'mirror'
            elif o.name == "الدُمية الكبيرة":
                o.kind, o.sp = 'special', 'doll'
            elif o.name == "البيانو":
                o.kind, o.sp = 'special', 'piano'
            elif o.name == "الصورة":
                o.kind, o.sp = 'special', 'portrait'
    lv.objs = objs

    # شموع
    cand_prob = max(0.3, 1 - 0.08 * n)
    lv.candles = []
    for cr in cells:
        v = cell[cr]
        if cr != start and rng.random() > cand_prob:
            continue
        corners = [(v['x0'], v['y0']), (v['x0'] + RW - 1, v['y0']),
                   (v['x0'], v['y0'] + RH - 1), (v['x0'] + RW - 1, v['y0'] + RH - 1)]
        rng.shuffle(corners)
        zones = doorzones[cr]
        for (cx_, cy_) in corners:
            r = pygame.Rect(cx_, cy_, 1, 1)
            if any(r.colliderect(pygame.Rect(o.rect.x // T, o.rect.y // T, o.rect.w // T, o.rect.h // T))
                   for o in furn[cr]):
                continue
            lv.candles.append((cx_, cy_))
            break
    # سجاد
    lv.rugs = []
    for cr in cells:
        if rng.random() < 0.6:
            v = cell[cr]
            lv.rugs.append((v['x0'] + 2, v['y0'] + 2, 5, 3, rng.choice(RUGCOL)))
    # خضّات
    others = [c for c in cells if c != start]
    rng.shuffle(others)
    cnt_t = min(len(others), 3 + n)
    kinds = (['face'] * (2 + n // 3) + ['bang'] * 3 + ['flicker'] * 3 +
             (['name'] * 2 if n >= 3 else []) + (['near'] * 2 if n >= 4 else []) +
             ['eyes'] * 2 + ['knock'] * 2 + (['dash'] * 2 if n >= 2 else []) +
             (['watch'] * 2 if n >= 3 else []))
    lv.triggers = []
    for i, cr in enumerate(others[:cnt_t]):
        v = cell[cr]
        k = rng.choice(kinds)
        if n == 5 and i == 0:
            k = 'name'
        lv.triggers.append(dict(rect=pygame.Rect((v['x0'] + 3) * T, (v['y0'] + 2) * T, 3 * T, 3 * T),
                                kind=k, fired=False))
    lv.floors = [(i, j) for j in range(lv.H) for i in range(lv.W) if lv.grid[j][i] == 0]
    sx, sy = cell[start]['x0'] + RW // 2, cell[start]['y0'] + RH // 2
    lv.start = (sx * T + 16, sy * T + 16)
    Aname = cell[A]['name']

    def goal(g):
        if 'exit' in g.inv:
            return "اهرب من باب الشقة!"
        if 'dA' in g.opened:
            return S("دوّر على مفتاح الشقة جوه {r}", r=Aname)
        if 'ka' in g.inv:
            return S("افتح باب {r}", r=Aname)
        return "اقرا الأوراق ودوّر على المفاتيح"
    lv.goal = goal
    return lv


# ================================================================= نص عربي
FONTS = {}
_cache = {}


def font_ok(f):
    try:
        return all(m is not None for m in f.metrics("\ufee3\ufefb\ufe8d\ufedf"))
    except Exception:
        return False


def load_font(size):
    for pth in (asset("font.ttf"), os.path.join(APP_DIR, "font.ttf"), os.path.join(APP_DIR, "font.otf")):
        if os.path.exists(pth):                         # الخط المرفق (IBM Plex Sans Arabic) أو أي خط حطيته جنب اللعبة
            return pygame.font.Font(pth, size)
    first = None
    for name in ("segoeui", "tahoma", "arial", "calibri", "dubai", "simplifiedarabic", "traditionalarabic",
                 "arabictypesetting", "sakkalmajalla", "notosansarabic", "notonaskharabic", "dejavusans",
                 "timesnewroman"):
        pth = pygame.font.match_font(name)
        if pth:
            f = pygame.font.Font(pth, size)
            if font_ok(f):
                return f
            first = first or f
    return first or pygame.font.Font(None, size)


def txt(text, size, color):
    text = str(text)
    key = (LANG, text, size, color)
    s = _cache.get(key)
    if s is None:
        if len(_cache) > 700:
            _cache.clear()
        f = FONTS.get(size) or FONTS.setdefault(size, load_font(size))
        shown = EN.get(text, text) if LANG == 'en' else text
        rs = arabic_reshaper.reshape(shown)
        try:
            vis = get_display(rs, base_dir='R') if (LANG == 'ar' and has_arabic(shown)) else get_display(rs)
        except TypeError:
            vis = get_display(rs)
        s = f.render(vis, True, color)
        _cache[key] = s
    return s


def draw_text(surf, text, size, color, x, y, align='r'):
    s = txt(text, size, color)
    if align == 'r':
        surf.blit(s, (x - s.get_width(), y))
    elif align == 'c':
        surf.blit(s, (x - s.get_width() // 2, y))
    else:
        surf.blit(s, (x, y))
    return s.get_height()


# ================================================================= الصوت
SR = 44100
AUDIO = False
SND = {}


def _snd(samples):
    ch = pygame.mixer.get_init()[2]
    buf = array.array('h')
    for s in samples:
        v = int(max(-1.0, min(1.0, s)) * 30000)
        buf.append(v)
        if ch == 2:
            buf.append(v)
    return pygame.mixer.Sound(buffer=buf.tobytes())


def load_or_build_sounds(msg=None):
    """على الموبايل بيتخزّن الصوت أول مرة (بيتبني بالكود)، والمرات الجاية بيتحمّل في لحظة"""
    cache = os.path.join(APP_DIR, "cache", "snd_v3")
    marker = os.path.join(cache, "ok")
    if ANDROID and os.path.exists(marker):
        try:
            d = {}
            for fn in os.listdir(cache):
                if fn.endswith('.wav'):
                    d[fn[:-4]] = pygame.mixer.Sound(os.path.join(cache, fn))
            if 'drone' in d:
                return d
        except Exception:
            pass
    if msg:
        msg("جاري تجهيز الأصوات... (أول مرة بس)")
    d = build_sounds()
    if ANDROID:
        try:
            os.makedirs(cache, exist_ok=True)
            fmt = pygame.mixer.get_init()
            for k, snd in d.items():
                with wave.open(os.path.join(cache, k + ".wav"), 'wb') as w:
                    w.setnchannels(fmt[2])
                    w.setsampwidth(2)
                    w.setframerate(fmt[0])
                    w.writeframes(snd.get_raw())
            with open(marker, 'w') as f:
                f.write('ok')
        except Exception as ex:
            print("مقدرتش أخزّن الأصوات:", ex)
    return d


def build_sounds():
    rnd = random.random
    tp = 2 * math.pi
    S = {}
    out, ph, ph2 = [], 0.0, 0.0
    for i in range(int(SR * 1.5)):
        t = i / SR
        env = math.exp(-t * 2.0) if t > 0.01 else t / 0.01
        f = 1400 - 900 * t
        ph += tp * f / SR
        ph2 += tp * f * 1.41 / SR
        out.append(env * (0.45 * (rnd() * 2 - 1) + 0.3 * math.sin(ph) +
                          0.25 * math.sin(ph2) * (1 if int(t * 40) % 2 else -0.6)))
    S['scare'] = _snd(out)
    S['bang'] = _snd([math.exp(-i / SR * 8) * (0.8 * (rnd() * 2 - 1) + 0.8 * math.sin(tp * 55 * i / SR))
                      for i in range(int(SR * 0.7))])

    def thump(x):
        return math.sin(tp * 50 * x) * math.exp(-x * 16) if x >= 0 else 0.0
    S['heart'] = _snd([thump(i / SR) + 0.7 * thump(i / SR - 0.22) for i in range(int(SR * 0.8))])
    S['drone'] = _snd([(0.5 * math.sin(tp * 55 * i / SR) + 0.3 * math.sin(tp * 58 * i / SR) +
                        0.2 * math.sin(tp * 82.5 * i / SR)) * (0.7 + 0.3 * math.sin(tp * 0.5 * i / SR)) * 0.35
                       for i in range(SR * 4)])
    out, y = [], 0.0
    for i in range(int(SR * 1.8)):
        t = i / SR
        y = y * 0.85 + (rnd() * 2 - 1) * 0.15
        out.append(y * math.sin(math.pi * t / 1.8) ** 2 * (0.6 + 0.4 * math.sin(tp * 7 * t)) * 3)
    S['whisper'] = _snd(out)
    out, ph = [], 0.0
    for i in range(SR):
        t = i / SR
        ph += tp * (120 + 40 * math.sin(tp * 5 * t) + 60 * t) / SR
        out.append(((ph / tp) % 1 * 2 - 1) * 0.25 * math.sin(math.pi * t) + (rnd() - .5) * 0.04)
    S['creak'] = _snd(out)
    out, y = [], 0.0
    for i in range(int(SR * 0.18)):
        y = y * 0.8 + (rnd() * 2 - 1) * 0.2
        out.append(y * math.exp(-i / SR * 28) * 2.2)
    S['step'] = _snd(out)
    out = []
    for i in range(int(SR * 0.2)):
        t = i / SR
        out.append(0.3 * math.sin(tp * (660 if t < 0.1 else 880) * t) * math.exp(-(t % 0.1) * 20))
    S['pickup'] = _snd(out)
    for nm, f0 in (('foot1', 105), ('foot2', 88)):          # خطوات ناعمة وواطية
        out, y = [], 0.0
        for i in range(int(SR * 0.14)):
            t = i / SR
            y = y * 0.92 + (rnd() * 2 - 1) * 0.08
            out.append((0.8 * math.sin(tp * f0 * t) + 0.35 * y) * math.exp(-t * 34) * (1 if t > 0.004 else t / 0.004))
        S[nm] = _snd(out)
    S['unlock'] = _snd([(0.6 * (rnd() * 2 - 1) if i < SR * 0.04 else 0.4 * math.sin(tp * 300 * i / SR)) *
                        math.exp(-i / SR * 14) for i in range(int(SR * 0.3))])

    # ---------- أصوات رعب إضافية ----------
    out, y = [], 0.0                                        # خبط على الحيطة
    for i in range(int(SR * 1.0)):
        t = i / SR
        y = y * 0.9 + (rnd() * 2 - 1) * 0.1
        v = 0.0
        for h in (0.0, 0.3, 0.62):
            if t >= h:
                v += math.exp(-(t - h) * 36) * (0.9 * math.sin(tp * 95 * (t - h)) + 3.2 * y)
        out.append(v)
    S['knock'] = _snd(out)
    out, y = [], 0.0                                        # باب بيتقفل بقوة
    for i in range(int(SR * 1.0)):
        t = i / SR
        y = y * 0.86 + (rnd() * 2 - 1) * 0.14
        v = math.exp(-t * 6) * (5.0 * y + 0.9 * math.sin(tp * 42 * t))
        if t > 0.17:
            v += 0.45 * math.exp(-(t - 0.17) * 9) * (4.0 * y + 0.8 * math.sin(tp * 60 * t))
        out.append(v)
    S['slam'] = _snd(out)
    out, ph = [], 0.0                                       # عياط طفل بعيد
    for i in range(int(SR * 2.0)):
        t = i / SR
        f = 380 + 150 * math.sin(math.pi * t / 2.0) + 14 * math.sin(tp * 5.5 * t) - 40 * t
        ph += tp * f / SR
        env = math.sin(math.pi * t / 2.0) ** 0.8 * (0.75 + 0.25 * math.sin(tp * 4.5 * t))
        v = math.sin(ph) + 0.55 * math.sin(2 * ph + 0.6) + 0.35 * math.sin(3 * ph + 1.2) + 0.2 * math.sin(4 * ph)
        out.append(env * (0.28 * v + (rnd() - 0.5) * 0.05))
    S['cry'] = _snd(out)
    out = [0.0] * int(SR * 1.3)                             # ضحكة طفل
    for k, t0 in enumerate((0.0, 0.2, 0.4, 0.6, 0.86)):
        f0, dur, ph = 600 - k * 35, 0.13, 0.0
        for j in range(int(SR * dur)):
            t = j / SR
            ph += tp * (f0 - 160 * t / dur) / SR
            env = math.sin(math.pi * t / dur) ** 1.5
            v = env * (0.4 * math.sin(ph) + 0.22 * math.sin(2 * ph + 1) + 0.12 * math.sin(3 * ph))
            idx = int(SR * t0) + j
            out[idx] += v
            out[idx + int(SR * 0.11)] += v * 0.35
    S['laugh'] = _snd(out)
    out, y = [], 0.0                                        # نفس تقيل ورا رقبتك
    for i in range(int(SR * 1.8)):
        t = i / SR
        y = y * 0.78 + (rnd() * 2 - 1) * 0.22
        env = (math.sin(math.pi * t / 0.8) ** 2 if t < 0.8 else 0.0) + \
              (0.8 * math.sin(math.pi * (t - 0.9) / 0.8) ** 2 if 0.9 <= t < 1.7 else 0.0)
        out.append(y * env * 2.6)
    S['breath'] = _snd(out)
    out, ph = [], 0.0                                       # صرخة حادة
    for i in range(int(SR * 1.3)):
        t = i / SR
        f = 800 + 1700 * (t / 1.3) ** 1.5
        ph += tp * (f + 140 * math.sin(tp * 31 * t)) / SR
        env = (t / 0.01 if t < 0.01 else 1.0) * math.exp(-t * 1.6)
        out.append(env * (0.6 * math.tanh(2.6 * math.sin(ph)) + 0.35 * (rnd() * 2 - 1)))
    S['shriek'] = _snd(out)
    S['static'] = _snd([(rnd() * 2 - 1) * 0.8 * (1.0 if int(i / SR * 70) % 3 else 0.25) * math.exp(-i / SR * 4)
                        for i in range(int(SR * 0.5))])
    notes = (659.3, 784.0, 987.8, 784.0, 880.0, 659.3, 587.3)   # علبة موسيقى لحنها مش مظبوط
    out = [0.0] * int(SR * (0.4 * len(notes) + 0.9))
    for k, f in enumerate(notes):
        f *= 1 - 0.012 * k * (k > 3)                            # النغمات بتنزل شوية شوية
        st = int(SR * 0.4 * k)
        for j in range(int(SR * 0.9)):
            t = j / SR
            out[st + j] += math.exp(-t * 5.5) * 0.28 * (math.sin(tp * f * t) + 0.4 * math.sin(tp * f * 2.76 * t) +
                                                        0.2 * math.sin(tp * f * 5.4 * t))
    S['musicbox'] = _snd(out)
    out, y = [], 0.0                                        # شمعة بتطفي
    for i in range(int(SR * 0.45)):
        t = i / SR
        n_ = rnd() * 2 - 1
        y = y * 0.6 + n_ * 0.4
        out.append((n_ - y) * math.exp(-t * 9) * 1.1 * (t / 0.02 if t < 0.02 else 1.0))
    S['snuff'] = _snd(out)
    return S


MASTER = 1.0
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(dict(lang=LANG, volume=MASTER), f)
    except Exception:
        pass


def load_settings():
    global LANG, MASTER
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            d = json.load(f)
        LANG = d.get('lang', 'ar') if d.get('lang') in ('ar', 'en') else 'ar'
        MASTER = max(0.0, min(1.0, float(d.get('volume', 1.0))))
    except Exception:
        pass


def set_lang(l):
    global LANG
    LANG = l
    save_settings()


def apply_volume():
    if AUDIO and 'drone' in SND:
        SND['drone'].set_volume(0.5 * MASTER)


def change_volume(delta=None, mute=False):
    global MASTER
    if mute:
        MASTER = 0.0 if MASTER > 0 else 1.0
    else:
        MASTER = max(0.0, min(1.0, round(MASTER + delta, 2)))
    apply_volume()
    save_settings()


def play(name, vol=1.0):
    if AUDIO and name in SND:
        SND[name].set_volume(max(0.0, min(1.0, vol * MASTER)))
        SND[name].play()


# ---------------- صوت الشبح وهو بينادي اسمك ----------------
_AR2L = dict(zip("ابتثجحخدذرزسشصضطظعغفقكلمنهةىءؤئأإآ",
                 ["a", "b", "t", "th", "j", "h", "kh", "d", "z", "r", "z", "s", "sh", "s", "d", "t", "z", "a",
                  "gh", "f", "k", "k", "l", "m", "n", "h", "a", "a", "", "o", "e", "a", "i", "aa"]))
_VOWELS = set("aeiou")


def has_arabic(t):
    return any('\u0600' <= c <= '\u06ff' for c in t)


def translit(name):
    """تحويل تقريبي للاسم العربي لحروف إنجليزي (لو مفيش صوت عربي في الجهاز)"""
    out = []
    for i, c in enumerate(name):
        if c == 'و':
            piece = 'oo' if (out and out[-1][-1:] not in _VOWELS) else 'w'
        elif c == 'ي':
            piece = 'ee' if (out and out[-1][-1:] not in _VOWELS) else 'y'
        else:
            piece = _AR2L.get(c, c if c.isascii() else "")
        if out and piece and out[-1][-1:] not in _VOWELS and piece[0] not in _VOWELS:
            out.append('a')
        if piece:
            out.append(piece)
    return ''.join(out) or name


def android_tts_to_wav(name, out):
    """نطق الاسم بمحرّك أندرويد (Google TTS) عن طريق pyjnius. لو مفيش صوت: الوحش هيهمس بس"""
    try:
        import time
        from jnius import autoclass, PythonJavaClass, java_method
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
        Locale = autoclass('java.util.Locale')
        File = autoclass('java.io.File')
        Bundle = autoclass('android.os.Bundle')
        state = {'ok': None}

        class InitListener(PythonJavaClass):
            __javainterfaces__ = ['android/speech/tts/TextToSpeech$OnInitListener']
            __javacontext__ = 'app'

            @java_method('(I)V')
            def onInit(self, status):
                state['ok'] = (status == 0)

        lst = InitListener()
        tts = TextToSpeech(PythonActivity.mActivity, lst)
        t0 = time.time()
        while state['ok'] is None and time.time() - t0 < 10:
            time.sleep(0.05)
        if not state['ok']:
            return False
        use_ar = tts.setLanguage(Locale('ar')) >= 0
        if not use_ar:
            tts.setLanguage(Locale.ENGLISH)
        tts.setSpeechRate(0.7)
        nm = name if (use_ar or not has_arabic(name)) else translit(name)
        if os.path.exists(out):
            os.remove(out)
        tts.synthesizeToFile("%s،  %s" % (nm, nm), Bundle(), File(out), "hh")
        last, t0 = -1, time.time()
        while time.time() - t0 < 20:                    # بنستنى الملف يتكتب ويثبت
            time.sleep(0.4)
            sz = os.path.getsize(out) if os.path.exists(out) else 0
            if sz > 1000 and sz == last:
                break
            last = sz
        tts.shutdown()
        return os.path.exists(out) and os.path.getsize(out) > 1000
    except Exception as ex:
        print("نطق أندرويد مش شغال:", ex)
        return False


def tts_to_wav(name, out):
    """بيطلّع ملف wav فيه الاسم منطوق بصوت الجهاز (pyttsx3 أو PowerShell على ويندوز أو محرّك أندرويد)"""
    if ANDROID:
        return android_tts_to_wav(name, out)
    latin = translit(name) if has_arabic(name) else name
    phrase = lambda n: "%s،  %s" % (n, n)
    try:
        import pyttsx3
        eng = pyttsx3.init()
        chosen = None
        for v in eng.getProperty('voices'):
            info = (str(v.id) + ' ' + str(v.name) + ' ' + str(getattr(v, 'languages', ''))).lower()
            if any(k in info for k in ('arabic', 'hoda', 'naayf', 'areg', 'arsa', 'maged', 'majed', 'tarik', 'ar-', 'ar_')):
                chosen = v
                break
        if chosen:
            eng.setProperty('voice', chosen.id)
        eng.setProperty('rate', 105)
        eng.save_to_file(phrase(name if (chosen or not has_arabic(name)) else latin), out)
        eng.runAndWait()
        eng.stop()
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            return True
    except Exception:
        pass
    if sys.platform.startswith('win'):
        ps = ("Add-Type -AssemblyName System.Speech;"
              "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "$v=$s.GetInstalledVoices()|?{$_.VoiceInfo.Culture.Name -like 'ar*'}|select -First 1;"
              "if($v){$s.SelectVoice($v.VoiceInfo.Name);$t=$env:GN_TEXT}else{$t=$env:GN_LATIN};"
              "$s.Rate=-4;$s.SetOutputToWaveFile($env:GN_OUT);$s.Speak($t);$s.Dispose()")
        env = dict(os.environ, GN_TEXT=phrase(name), GN_LATIN=phrase(latin), GN_OUT=out)
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, timeout=40,
                           creationflags=0x08000000, capture_output=True)
        except Exception:
            pass
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            return True
    return False


def scary_voice(path):
    """بيحوّل الصوت لصوت شيطاني: أوطى + تشويه + صدى + همس"""
    tp = 2 * math.pi
    with wave.open(path) as w:
        ch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        return None
    a = array.array('h')
    a.frombytes(raw)
    mono = [sum(a[i:i + ch]) / (ch * 32768.0) for i in range(0, len(a) - ch + 1, ch)]
    pk = max((abs(v) for v in mono), default=0)
    if pk < 0.01:
        return None
    idx = [i for i, v in enumerate(mono) if abs(v) > pk * 0.04]
    mono = mono[idx[0]:idx[-1] + 1]
    step, pos, dry, n = fr / SR * 0.62, 0.0, [], len(mono)       # تبطيئ + تغليظ
    while pos < n - 1:
        i = int(pos)
        f = pos - i
        dry.append(mono[i] * (1 - f) + mono[i + 1] * f)
        pos += step
    y, env, nz, out = 0.0, 0.0, 0.0, []
    for i, v in enumerate(dry):
        v = math.tanh(2.4 * v) * (0.72 + 0.28 * math.sin(tp * 42 * i / SR))   # تشويه + خشونة
        y += (v - y) * 0.45                                                   # فلتر
        env += (abs(y) - env) * 0.002
        nz = nz * 0.8 + (random.random() * 2 - 1) * 0.2
        out.append(y + nz * env * 1.3)                                        # همس فوق الصوت
    tail = int(SR * 1.1)
    res = [0.0] * (len(out) + tail)
    for d, g in ((0, 1.0), (0.13, 0.55), (0.29, 0.4), (0.5, 0.28), (0.8, 0.16)):
        k = int(SR * d)
        for i, v in enumerate(out):
            res[i + k] += v * g
    m = max(abs(v) for v in res) or 1.0
    res = [v / m * 0.95 for v in res]
    fade = int(SR * 0.05)
    for i in range(fade):
        res[i] *= i / fade
        res[-1 - i] *= i / fade
    return _snd(res)


VOICE_KINDS = ('v_whisper', 'v_child', 'v_rev', 'v_choir')


def _load_mono(path):
    with wave.open(path) as w:
        ch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        return None, fr
    a = array.array('h')
    a.frombytes(raw)
    mono = [sum(a[i:i + ch]) / (ch * 32768.0) for i in range(0, len(a) - ch + 1, ch)]
    pk = max((abs(v) for v in mono), default=0)
    if pk < 0.01:
        return None, fr
    idx = [i for i, v in enumerate(mono) if abs(v) > pk * 0.04]
    return mono[idx[0]:idx[-1] + 1], fr


def _resample(mono, fr, ratio):
    step, pos, out, n = fr / SR * ratio, 0.0, [], len(mono)
    while pos < n - 1:
        i = int(pos)
        f = pos - i
        out.append(mono[i] * (1 - f) + mono[i + 1] * f)
        pos += step
    return out


def _mix(layers, tail_s=1.2):
    """بيدمج طبقات (عينات، تأخير بالثواني، قوة) في صوت واحد فيه صدى"""
    n = max(int(SR * d) + len(x) for x, d, g in layers) + int(SR * tail_s)
    res = [0.0] * n
    for x, d, g in layers:
        k = int(SR * d)
        for i, v in enumerate(x):
            res[i + k] += v * g
    m = max(abs(v) for v in res) or 1.0
    res = [v / m * 0.95 for v in res]
    fade = int(SR * 0.05)
    for i in range(fade):
        res[i] *= i / fade
        res[-1 - i] *= i / fade
    return res


def _save_wav(path, res):
    buf = array.array('h', [int(max(-1.0, min(1.0, v)) * 30000) for v in res])
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(buf.tobytes())


def make_voice_variants(path):
    """همس قريب من ودنك / طفل مشوّه / الاسم بالمقلوب / كورال شياطين"""
    mono, fr = _load_mono(path)
    if not mono:
        return {}
    tp = 2 * math.pi
    vs = {}
    dry = _resample(mono, fr, 0.9)                                    # همس في ودنك
    env, nz, out = 0.0, 0.0, []
    for v in dry:
        env += (abs(v) - env) * 0.004
        nz = nz * 0.55 + (random.random() * 2 - 1) * 0.45
        out.append(nz * min(1.0, env * 14) * 1.3 + v * 0.10)
    vs['v_whisper'] = _mix([(out, 0, 1.0), (out, 0.18, 0.5), (out, 0.4, 0.3), (out, 0.7, 0.15)])
    dry = _resample(mono, fr, 1.3)                                    # صوت طفل مشوّه
    out = [math.tanh(1.8 * v) * (0.75 + 0.25 * math.sin(tp * 28 * i / SR)) for i, v in enumerate(dry)]
    vs['v_child'] = _mix([(out, 0, 1.0), (out, 0.22, 0.45), (out, 0.46, 0.25)], 1.0)
    dry = _resample(mono, fr, 0.7)[::-1]                              # الاسم بالمقلوب
    out, y = [], 0.0
    for v in dry:
        y += (math.tanh(2.0 * v) - y) * 0.5
        out.append(y + (random.random() * 2 - 1) * 0.02)
    vs['v_rev'] = _mix([(out, 0, 1.0), (out, 0.3, 0.5), (out, 0.6, 0.35), (out, 1.0, 0.2)], 1.6)
    layers = []                                                       # كورال شياطين
    for ratio, d, g in ((0.5, 0.0, 1.0), (0.58, 0.04, 0.85), (0.72, 0.09, 0.7), (1.2, 0.13, 0.35)):
        x, y = [], 0.0
        for i, v in enumerate(_resample(mono, fr, ratio)):
            v = math.tanh(2.8 * v) * (0.7 + 0.3 * math.sin(tp * 38 * i / SR))
            y += (v - y) * 0.5
            x.append(y)
        layers.append((x, d, g))
    base = layers[0][0]
    layers += [(base, 0.35, 0.5), (base, 0.7, 0.35), (base, 1.2, 0.2)]
    vs['v_choir'] = _mix(layers, 1.8)
    return vs


def prepare_voice(name):
    """بيجهّز صوت الشبح باسمك. لو فشل: الشبح هيهمس وبس"""
    SND.pop('voice', None)
    for k in VOICE_KINDS:
        SND.pop(k, None)
    if not AUDIO or not name:
        return False
    vdir = os.path.join(APP_DIR, "cache") if ANDROID else tempfile.gettempdir()
    os.makedirs(vdir, exist_ok=True)
    path = os.path.join(vdir, "hh_voice_%s.wav" % hashlib.md5(name.encode('utf-8')).hexdigest()[:10])
    try:
        if not (os.path.exists(path) and os.path.getsize(path) > 1000):
            if not tts_to_wav(name, path):
                print("ملقيتش صوت ينطق الاسم. نزّل:  pip install pyttsx3  (الشبح هيهمس بس دلوقتي)")
                return False
        snd = scary_voice(path)
        if snd:
            SND['voice'] = snd
        vs = None
        for k in VOICE_KINDS:                       # النسخ المرعبة بتتحفظ علشان التشغيل الجاي يبقى أسرع
            cp = path[:-4] + "_%s_v2.wav" % k
            if not (os.path.exists(cp) and os.path.getsize(cp) > 1000):
                if vs is None:
                    vs = make_voice_variants(path)
                if k not in vs:
                    continue
                _save_wav(cp, vs[k])
            SND[k] = pygame.mixer.Sound(cp)
        return 'voice' in SND
    except Exception as ex:
        print("مشكلة في صوت الشبح:", ex)
    return False


def prepare_voice_async(name):
    """على الموبايل التجهيز بياخد وقت، فبيتعمل في الخلفية واللعبة شغّالة"""
    if not ANDROID:
        return prepare_voice(name)
    import threading
    threading.Thread(target=prepare_voice, args=(name,), daemon=True).start()
    return False


# ================================================================= رسومات
_rad = {}


def radial(R, amax=240):
    R = max(12, int(R // 6 * 6))
    s = _rad.get((R, amax))
    if s is None:
        s = pygame.Surface((2 * R, 2 * R), pygame.SRCALPHA)
        for r in range(R, 0, -2):
            pygame.draw.circle(s, (255, 255, 255, int(amax * (1 - r / R) ** 1.1)), (R, R), r)
        _rad[(R, amax)] = s
    return s


def light(dark, cx, cy, R, amax=240):
    s = radial(R, amax)
    r = s.get_width() // 2
    dark.blit(s, (cx - r, cy - r), special_flags=pygame.BLEND_RGBA_SUB)


_glow = {}


def glow(s, x, y, R, col, amax=180):
    key = (R, col, amax)
    g = _glow.get(key)
    if g is None:
        g = radial(R, amax).copy()
        g.fill(col + (255,), special_flags=pygame.BLEND_RGBA_MULT)
        _glow[key] = g
    s.blit(g, (x - g.get_width() // 2, y - g.get_height() // 2))


def make_face(seed, style=0):
    """الوحش بتاع الخضّة: 0 شيطان بقرون، 1 ملكة الصراخ، 2 سيد الجماجم"""
    random.seed(seed)
    w, h = 300, 380
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    if style == 0:
        skin, rim, eye, mane = (112, 126, 108), (60, 72, 58), (255, 170, 20), (30, 10, 14)
    elif style == 1:
        skin, rim, eye, mane = (214, 216, 208), (130, 130, 124), (190, 230, 255), (6, 6, 10)
    else:
        skin, rim, eye, mane = (226, 220, 196), (120, 112, 90), (255, 40, 20), (20, 16, 20)
    for _ in range(80):                                   # شعر / عرف
        x0 = random.randint(40, 260)
        pts = [(x0, 60)]
        x, y = x0, 60
        for _k in range(9):
            x += random.randint(-10, 10) + (-6 if x0 < 150 else 6)
            y += random.randint(26, 40)
            pts.append((x, y))
        pygame.draw.lines(s, mane, False, pts, random.randint(3, 7))
    if style == 0:                                        # قرون
        for sg in (-1, 1):
            cx = 150 + sg * 70
            pts = [(cx, 90), (cx + sg * 30, 40), (cx + sg * 62, 12), (cx + sg * 80, 28),
                   (cx + sg * 46, 52), (cx + sg * 22, 100)]
            pygame.draw.polygon(s, (36, 30, 26), pts)
            pygame.draw.lines(s, (90, 80, 66), False, pts[:4], 3)
    elif style == 2:                                      # تاج عضم
        for k in range(7):
            bx = 80 + k * 23
            pygame.draw.polygon(s, (150, 140, 110), [(bx - 8, 74), (bx + 8, 74), (bx + random.randint(-6, 6), 74 - random.randint(30, 60))])
    box = (56, 58, 188, 290) if style != 2 else (62, 62, 176, 230)
    pygame.draw.ellipse(s, skin, box)
    if style == 2:
        pygame.draw.rect(s, skin, (96, 250, 108, 90), border_radius=18)
    pygame.draw.ellipse(s, rim, box, 6)
    for _ in range(14):                                   # شروخ وندوب
        x = random.randint(80, 220)
        y = random.randint(80, 200)
        pygame.draw.lines(s, rim, False, [(x, y), (x + random.randint(-20, 20), y + 20), (x + random.randint(-30, 30), y + random.randint(40, 70))], 2)
    for ex in (112, 188):                                 # العيون المتوهجة
        if style == 2:
            pygame.draw.ellipse(s, (0, 0, 0), (ex - 28, 112, 56, 70))
        elif style == 1:
            pygame.draw.ellipse(s, (0, 0, 0), (ex - 24, 104, 48, 96))
        else:
            pygame.draw.polygon(s, (0, 0, 0), [(ex - 34, 130), (ex + 34, 112), (ex + 28, 160), (ex - 26, 166)])
        glow(s, ex, 144, 40, eye, 230)
        pygame.draw.circle(s, (255, 255, 235), (ex, 144), 5)
    if style == 1:                                        # الفم والأنياب
        pygame.draw.ellipse(s, (0, 0, 0), (118, 214, 64, 130))
        for k in range(6):
            pygame.draw.polygon(s, (230, 230, 215), [(122 + k * 11, 224), (130 + k * 11, 224), (126 + k * 11, 244)])
    else:
        mh = 96 if style == 0 else 70
        pygame.draw.ellipse(s, (14, 0, 0), (86, 222, 128, mh + 34))
        for k in range(9):
            tx = 94 + k * 13
            ln = random.randint(18, 40) if k % 2 else random.randint(10, 22)
            pygame.draw.polygon(s, (236, 232, 210), [(tx, 234), (tx + 12, 234), (tx + 6, 234 + ln)])
            pygame.draw.polygon(s, (236, 232, 210), [(tx, 236 + mh + 10), (tx + 12, 236 + mh + 10), (tx + 6, 236 + mh - ln // 2)])
    random.seed()
    return s


def make_ghost():
    """شبح طويل بفستان ممزق، شعر أسود على وشه، وإيدين طويلة"""
    random.seed(11)
    s = pygame.Surface((96, 160), pygame.SRCALPHA)
    for k in range(16):                                   # أطراف الفستان الممزقة
        x0 = 20 + k * 4
        pygame.draw.polygon(s, (196 + random.randint(-14, 14), 200, 210, 235 - (k % 3) * 25),
                            [(x0, 62), (x0 + 8, 62), (x0 + 4 + random.randint(-4, 4), random.randint(112, 158))])
    pygame.draw.polygon(s, (208, 211, 218, 242), [(32, 54), (64, 54), (74, 122), (22, 122)])
    for sg in (-1, 1):                                    # دراعات طويلة وصوابع
        pts = [(48 + sg * 14, 60), (48 + sg * 26, 90), (48 + sg * 20, 118), (48 + sg * 28, 140)]
        pygame.draw.lines(s, (222, 222, 210), False, pts, 5)
        hx, hy = pts[-1]
        for f in range(5):
            pygame.draw.line(s, (222, 222, 210), (hx, hy), (hx + (f - 2) * 3 + sg * random.randint(0, 6), hy + random.randint(10, 20)), 2)
    pygame.draw.rect(s, (214, 214, 204), (45, 50, 6, 10))
    pygame.draw.ellipse(s, (226, 226, 214), (34, 12, 28, 40))
    for ex in (38, 51):
        pygame.draw.ellipse(s, (0, 0, 0), (ex, 26, 8, 13))
    pygame.draw.ellipse(s, (0, 0, 0), (43, 42, 10, 20))
    for _ in range(95):                                   # شعر طويل
        x0 = random.randint(32, 64)
        sd = -1 if x0 < 48 else 1
        x, y = x0, 12 + random.randint(0, 6)
        pts = [(x, y)]
        for _k in range(9):
            x += sd * random.randint(0, 4) + random.randint(-2, 2)
            y += random.randint(10, 16)
            pts.append((x, y))
        pygame.draw.lines(s, (6, 6, 8, 255), False, pts, random.randint(1, 3))
    for _ in range(6):
        x = random.randint(38, 58)
        pygame.draw.line(s, (6, 6, 8, 255), (x, 14), (x + random.randint(-4, 4), random.randint(36, 56)), 1)
    random.seed()
    return s


def draw_ghost_pos(gx, gy, t):
    w, h = A['ghost'].get_size()
    return (int(gx - w / 2 + math.sin(t * 1.7 + gx * 0.01) * 5),
            int(gy - h + 36 + math.sin(t * 2.2 + gy * 0.01) * 4))


def draw_ghost(s, gx, gy, alpha, t):
    spr = A['ghost']
    w, h = spr.get_size()
    x, y = draw_ghost_pos(gx, gy, t)
    spr.set_alpha(alpha)
    if random.random() < 0.12:                            # تشويش
        for k in range(0, h, 12):
            s.blit(spr, (x + (random.randint(-9, 9) if random.random() < 0.5 else 0), y + k), (0, k, w, 12))
    else:
        s.blit(spr, (x, y))
    return x, y


def ghost_eyes(s, x, y, a=1.0):
    for ex in (x + 42, x + 55):
        glow(s, ex, y + 32, 14, (255, 40, 30), 60 * (1 + int(min(a, 0.99) * 3)))
        pygame.draw.ellipse(s, (255, 235, 225), (ex - 3, y + 30, 6, 4))


def make_vignette():
    s = pygame.Surface((SW, SH), pygame.SRCALPHA)
    for k in range(70):
        pygame.draw.rect(s, (90, 0, 0, int(230 * (1 - k / 70) ** 2.2)), (k * 4, k * 4, SW - k * 8, SH - k * 8), 4)
    return s


def draw_hand(s, x, y, ang):
    """بصمة إيد دم على الأرض"""
    col = (122, 10, 12)
    pygame.draw.ellipse(s, col, (x - 9, y - 5, 18, 20))
    for a in (-52, -26, 0, 26, 52):
        r = math.radians(a + ang)
        ln = 30 if a == 0 else 26
        pygame.draw.line(s, col, (x + math.sin(r) * 6, y - 2 - math.cos(r) * 6),
                         (x + math.sin(r) * ln, y - 2 - math.cos(r) * ln), 4)
    pygame.draw.line(s, col, (x - 4, y + 12), (x - 6, y + 34), 3)       # دم نازل



A = {}


# ================================================================= الحفظ
def load_save():
    try:
        with open(SAVE_FILE, encoding='utf-8') as f:
            d = json.load(f)
        if 'profile' in d:
            return d
    except Exception:
        pass
    return None


def write_save(d):
    try:
        with open(SAVE_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False)
        return True
    except Exception:
        return False


NAME_LINES = ["{n}... استنّى", "مش هتهرب يا {n}", "{n}.. ورااااك", "أنا شايفك يا {n}",
              "تعالى يا {n}... متخافش", "{n}... كنت مستنيك", "{n}... أنا واقف ورا الباب",
              "{n}.. بصّ ورا", "مش لوحدك يا {n}", "{n}... سامعك وإنت بتتنفّس",
              "فاضل خطوة واحدة يا {n}", "ليه سبتني لوحدي يا {n}؟"]

AMB_TEXT = {'creak': "سمعت صرير باب بيتفتح... في مكان ما.",
            'whisper': "مين اللي بيهمس؟!",
            'step': "خطوات... جاية من فوق.",
            'knock': "حد بيخبط... من جوه الحيطة!",
            'cry': "سمعت عياط طفل... بعيد.",
            'laugh': "ضحكة طفل... ورا الباب!",
            'musicbox': "علبة موسيقى بتشتغل لوحدها...",
            'breath': "حاسس بنفس بارد ورا رقبتك...",
            'slam': "باب اتقفل بقوة في مكان ما!"}
HALL_WORDS = ["وراك", "شايفك", "اطلع", "هو هنا"]
DECAL_WORDS = ["اطلع", "هو وراك", "شايفك", "مش هتخرج", "متبصّش"]


# ================================================================= اللعبة
AR_ROWS = ["ضصثقفغعهخحجد", "شسيبلاتنمكطذ", "ئءؤرىةوزظأإآ"]
EN_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm'"]


class Game:
    def __init__(self):
        self.state = 'title'
        self.dark = pygame.Surface((SW, SH), pygame.SRCALPHA)
        self.t = 0.0
        self.sel = 0
        self.btns = []
        self.js_t, self.js_after, self.js_text, self.js_face = 0.0, None, "", None
        self.shake = 0.0
        self.toast_s, self.toast_t = "", 0.0
        self.dlg, self.dlg_title, self.dlg_close = None, "", None
        self.later = []
        self.app = None
        self.say = None
        self.bday_done = False
        self.field = 0
        self.form = {'name': '', 'day': '', 'month': ''}
        self.form_err = ""
        self.trans_t = 0.0
        self.next_n = 1
        self.win_t = 0.0
        self.lv = None
        self.level = 1
        self.objs = []
        self.opened = set()
        self.inv = set()
        self.done = set()
        self.ghosts = []
        self.spare, self.battery, self.fear = 0, 100.0, 0.0
        self.js_dur = 1.5
        self.eyes, self.decals, self.dash, self.hall = [], [], None, None
        self.out_c = set()
        self.glitch_t = 0.0
        self.was_moving = False
        self.eye_cd = self.snuff_cd = self.sc_cd = self.phantom_cd = 10.0
        self.joy, self.joy_run, self.kb_lang = (0.0, 0.0), False, 'ar'      # الجويستيك + لغة كيبورد الشاشة
        # ---- أونلاين
        self.net = self.srv = self.scan = None
        self.on_view, self.join_id, self.join_wait, self.net_msg = 'menu', "", None, ""
        self.pending_online = False
        self.reset_room()
        self.profile = None
        self.saved = None
        d = load_save()
        if d:
            self.profile, self.saved = d['profile'], d.get('game')

    # ------------------------------------------------ أدوات
    def name(self):
        return (self.profile or {}).get('name', "يا غريب")

    def toast(self, s, sec=3.0):
        self.toast_s, self.toast_t = s, sec

    def dialog(self, title, lines, on_close=None):
        self.dlg = list(lines)
        self.dlg_title, self.dlg_close = title, on_close

    def close_dialog(self):
        fn = self.dlg_close
        self.dlg = self.dlg_close = None
        if fn:
            fn()

    def after(self, sec, fn):
        self.later.append([sec, fn])

    def flash_ok(self):
        return self.flash and self.battery > 0 and self.blackout <= 0

    def is_bday(self):
        p = self.profile
        d = datetime.date.today()
        return bool(p) and d.day == p['day'] and d.month == p['month']

    def maybe_birthday(self):
        if self.is_bday() and not self.bday_done:
            self.bday_done = True
            self.scare('face', text=BDAY_TEXT)

    def voice(self, vol=1.0, kind='voice'):
        if not AUDIO:
            return
        s = SND.get(kind) or SND.get('voice')
        if s is None:
            play('whisper', vol * 0.8)
        elif s.get_num_channels() == 0:
            s.set_volume(max(0.0, min(1.0, vol * MASTER)))
            s.play()

    def name_line(self):
        return S(random.choice(NAME_LINES), n=self.name())

    # ------------------------------------------------ جلسة ومراحل
    def new_session(self):
        self.spare, self.battery, self.fear = 0, 100.0, 0.0
        self.start_level(1)

    def start_level(self, n):
        self.level = n
        self.lv = build_level1() if n == 1 else gen_level(n, self.room_seed if self.net else self.profile['seed'])
        self.objs = self.lv.objs
        self.px, self.py = self.lv.start
        self.fx, self.fy = 0, -1
        self.inv, self.done, self.opened = set(), set(), set()
        self.ghosts = []
        D = diff(n)
        self.ghost_cd = D['gcd'] + 12
        self.cd = 10.0
        self.blackout = 0.0
        self.flash = True
        self.dead_warned = False
        self.later = []
        self.app = self.say = None
        self.amb = random.uniform(0.7, 1.2) * D['amb']
        self.step_t = self.heart_t = 0.0
        self.voice_cd = 6.0
        self.visited = set()
        self.show_map = False
        self.moving = False
        self.eyes, self.decals, self.dash, self.hall = [], [], None, None
        self.out_c = set()
        self.glitch_t = 0.0
        self.was_moving = False
        self.eye_cd = random.uniform(10, 20)
        self.snuff_cd = random.uniform(25, 40)
        self.sc_cd = 15.0
        self.phantom_cd = 20.0
        self.joy, self.joy_run = (0.0, 0.0), False
        apply_volume()
        if TOUCH and n == 1:
            self.toast("حرّك الجويستيك للمشي... وزر التفاعل لفتح الحاجات.", 6)
        self.fear = min(self.fear, 25.0)
        self.room = self.lv.rooms[0][0]
        self.dlg = None
        self.toast(S("{t} - عدد الأوض: {n}", t=self.lv.title, n=len(self.lv.rooms)), 4)

    def snapshot(self):
        return dict(profile=self.profile, game=dict(
            level=self.level, px=self.px, py=self.py, fx=self.fx, fy=self.fy, inv=sorted(self.inv),
            spare=self.spare, battery=self.battery, fear=self.fear, done=sorted(self.done),
            opened=sorted(self.opened), visited=sorted(self.visited),
            fired=[i for i, t in enumerate(self.lv.triggers) if t['fired']]))

    def save(self, silent=False):
        if self.net:                                   # الأونلاين مالوش حفظ
            return False
        ok = write_save(self.snapshot())
        if not silent:
            self.toast("تم حفظ اللعبة" if ok else "مقدرتش أحفظ الملف!", 2.5)
        return ok

    def load_game(self):
        g = self.saved
        self.spare, self.battery, self.fear = g['spare'], g['battery'], g['fear']
        self.start_level(g['level'])
        self.px, self.py, self.fx, self.fy = g['px'], g['py'], g['fx'], g['fy']
        self.inv, self.done, self.opened = set(g['inv']), set(g['done']), set(g['opened'])
        for o in self.objs:
            if o.id in self.opened:
                o.solid = o.can = False
        self.visited = set(g.get('visited', []))
        for i in g['fired']:
            if i < len(self.lv.triggers):
                self.lv.triggers[i]['fired'] = True
        self.toast(S("أهلًا بيك تاني يا {n}...", n=self.name()), 3)

    def go_next(self):
        if self.net:                                   # أونلاين: بنبلّغ الغرفة إننا هربنا وبنتفرّج على الباقي
            play('unlock')
            if self.me_status == 'alive':
                self.me_status, self.died_t = 'escaped', 0.0
                self.net.send({'t': 'esc', 'e': self.epoch})
                self.ghosts, self.later, self.dlg = [], [], None
            return
        play('unlock')
        if self.level >= MAX_LEVEL:
            self.state, self.win_t = 'win', 0.0
        else:
            self.state, self.trans_t, self.next_n = 'trans', 0.0, self.level + 1

    def update_trans(self, dt):
        self.trans_t += dt
        if self.trans_t > 3.4:
            self.start_level(self.next_n)
            self.state = 'play'
            self.save(silent=True)


    # ------------------------------------------------ أونلاين (LAN)
    def reset_room(self):
        self.room_id, self.room_ip, self.room_seed = "", "", 0
        self.pid, self.slot, self.is_host = None, 0, False
        self.peers = {}                                # pid -> بيانات اللاعبين التانيين
        self.me_status, self.me_why = 'alive', ""      # alive | dead | escaped
        self.epoch, self.spec_pid = 0, None
        self.pos_t = self.ping_t = self.died_t = self.wipe_t = 0.0
        self.room_phase, self.op_sent = 'lobby', []

    def open_online(self):
        if not self.profile:                           # محتاجين اسم: نعدّي على شاشة التسجيل الأول
            self.do_action('new')
            self.pending_online = True
            return
        self.state, self.on_view, self.net_msg, self.sel = 'online', 'menu', "", 0
        if 'voice' not in SND:
            prepare_voice_async(self.name())

    def stop_scan(self):
        if self.scan:
            self.scan.stop()
            self.scan = None
        if not TOUCH:
            pygame.key.stop_text_input()

    def leave_online(self):
        self.stop_scan()
        if self.net:
            self.net.close()
        if self.srv:
            self.srv.stop()
        self.net = self.srv = None
        self.join_wait = None
        self.reset_room()

    def net_lost(self, msg):
        """اتقطع الاتصال (أو المضيف قفل الغرفة): نرجع لقايمة الأونلاين"""
        self.leave_online()
        self.state, self.on_view, self.net_msg, self.sel = 'online', 'menu', msg, 0
        self.js_t, self.dlg = 0.0, None

    def drop_connection(self, msg):
        """فشل الانضمام: نفضل في شاشة الانضمام ونعرض السبب"""
        if self.net:
            self.net.close()
        self.net, self.net_msg, self.join_wait = None, msg, None

    def create_room(self):
        self.net_msg = ""
        rid = netplay.new_room_id()                    # رقم من 6 أرقام اتأكدنا إنه مش مستخدم على الشبكة
        seed = random.randint(1, 10 ** 6)              # نفس الـ seed = نفس شكل البيت عند كل اللاعبين
        srv = netplay.RoomServer(self.name(), seed, rid)
        if not srv.start():
            self.net_msg = "مقدرتش أفتح الغرفة... تأكد إنك متصل بشبكة."
            return
        self.reset_room()
        self.srv, self.net = srv, netplay.NetClient()
        self.room_id, self.room_ip, self.room_seed = rid, srv.ip, seed
        self.net.connect('127.0.0.1', srv.port, self.name(), srv.host_key)
        self.on_view, self.sel = 'lobby', 0

    def open_join(self):
        self.stop_scan()
        self.on_view, self.join_id, self.net_msg, self.join_wait, self.sel = 'join', "", "", None, 0
        self.scan = netplay.Scanner()
        self.scan.start()
        if not TOUCH:
            pygame.key.start_text_input()

    def join_type(self, text):
        text = text.translate({0x660 + i: ord('0') + i for i in range(10)})
        self.join_id = (self.join_id + ''.join(c for c in text if c.isdigit() or c == '.'))[:15]
        self.net_msg = ""

    def connect_to(self, ip, port):
        if self.net:
            self.net.close()
        self.reset_room()
        self.net = netplay.NetClient()
        self.net.connect(ip, port, self.name())
        self.room_ip = ip
        self.net_msg, self.join_wait = "جاري الاتصال...", None

    def join_go(self):
        key = self.join_id.strip()
        if not key or self.net:
            return
        if '.' in key:                                 # IP المضيف (لو الشبكة بتمنع البحث التلقائي)
            self.connect_to(key, netplay.GAME_PORT)
            return
        r = self.scan.rooms.get(key) if self.scan else None
        if r:
            self.connect_to(r['ip'], r['port'])
        else:
            self.join_wait = (key, time.time() + 3.0)
            self.net_msg = "بدوّر على الغرفة..."

    def net_frame(self, dt):
        """بتتنفّذ كل فريم في كل الشاشات: بتقرا رسايل الشبكة"""
        if self.join_wait:
            key, until = self.join_wait
            r = self.scan.rooms.get(key) if self.scan else None
            if r:
                self.connect_to(r['ip'], r['port'])
            elif time.time() > until:
                self.join_wait, self.net_msg = None, "الغرفة مش موجودة على الشبكة. جرّب تكتب IP المضيف."
        if not self.net:
            return
        for m in self.net.poll():
            if not self.net:
                break
            self.on_net(m)
        if not self.net:
            return
        self.ping_t -= dt
        if self.ping_t <= 0:
            self.ping_t = 2.0
            self.net.send({'t': 'ping'})
        if self.wipe_t > 0:
            self.wipe_t -= dt
        k = min(1.0, dt * 12)                          # تنعيم حركة اللاعبين التانيين
        for p in self.peers.values():
            if p.get('x') is None:
                p['dx'] = None
            elif p.get('dx') is None:
                p['dx'], p['dy'] = p['x'], p['y']
            else:
                p['dx'] += (p['x'] - p['dx']) * k
                p['dy'] += (p['y'] - p['dy']) * k

    def on_net(self, m):
        t = m.get('t')
        if t == 'welcome':
            self.pid, self.slot, self.is_host = m['pid'], m['slot'], bool(m.get('host'))
            self.room_id, self.room_seed = str(m['room']), m['seed']
            self.stop_scan()
            self.join_wait, self.net_msg = None, ""
            self.on_view, self.state, self.sel = 'lobby', 'online', 0
        elif t == 'deny':
            self.drop_connection({'full': "الغرفة مليانة (8 لاعبين).",
                                  'started': "اللعبة بدأت بالفعل... مينفعش تنضم دلوقتي.",
                                  'version': "نسخة اللعبة مختلفة عن نسخة المضيف."}.get(m.get('why'), "الغرفة رفضت انضمامك."))
        elif t == 'error':
            self.drop_connection("مقدرتش أوصل للمضيف... اتأكد من الرقم ومن الشبكة.")
        elif t in ('closed', 'bye'):
            msg = "المضيف قفل الغرفة." if m.get('why') == 'host_left' else "الاتصال بالغرفة اتقطع."
            if self.state == 'online' and self.on_view == 'join':
                self.drop_connection(msg)
            else:
                self.net_lost(msg)
        elif t == 'roster':
            self.on_roster(m)
        elif t == 'level':
            self.on_level(m)
        elif t == 'st':
            if m.get('e') == self.epoch:
                for k, v in m['p'].items():
                    p = self.peers.get(int(k))
                    if p and p.get('st') == 'alive':
                        p['x'], p['y'], p['fx'], p['fy'], p['fl'], p['g'] = v[0], v[1], v[2], v[3], v[4], v[5]
        elif t == 'op':
            p = self.peers.get(m.get('pid'))
            if p and m.get('e') == self.epoch:
                p['op'] = list(m.get('ids', []))
        elif t == 'wipe':
            self.wipe_t = float(m.get('after', 3.0))
        elif t == 'win':
            self.state, self.win_t, self.js_t = 'win', 0.0, 0.0

    def on_roster(self, m):
        old = {pid: p.get('st') for pid, p in self.peers.items()}
        seen = set()
        for d in m.get('players', []):
            pid = d['pid']
            seen.add(pid)
            p = self.peers.setdefault(pid, dict(x=None, y=None, dx=None, dy=None, fx=0.0, fy=-1.0, fl=0, g=[], op=[]))
            p.update(name=d['name'], slot=d['slot'], st=d['st'], host=d['host'], gx=d['dx'], gy=d['dy'],
                     why=d.get('why', ""))
            if d['st'] != 'alive':
                p['x'], p['g'] = None, []
                if (pid != self.pid and old.get(pid) == 'alive' and self.me_status == 'alive'
                        and self.state in ('play', 'pause')):
                    self.toast(S("{n} مات!" if d['st'] == 'dead' else "{n} هرب من الشقة!", n=d['name']), 3)
        for pid in list(self.peers):
            if pid not in seen:
                del self.peers[pid]
        self.room_phase = m.get('phase', 'lobby')

    def on_level(self, m):
        n, e, why = m['n'], m['e'], m.get('why')
        if e <= self.epoch:
            return
        self.epoch = e
        revived = self.me_status != 'alive'
        self.me_status, self.me_why = 'alive', ""
        self.wipe_t, self.spec_pid, self.op_sent = 0.0, None, []
        self.dlg, self.js_t, self.js_after = None, 0.0, None
        for p in self.peers.values():
            p.update(x=None, dx=None, g=[], op=[], fl=0)
        if why in ('start', 'restart'):
            self.spare, self.battery, self.fear = 0, 100.0, 0.0
            self.start_level(n)
            self.state = 'play'
            if why == 'restart':
                self.toast("كلكم متّم... الشقة اتعادت من الأول.", 4)
        else:                                          # الشقة الجاية: اللي ماتوا بيرجعوا للحياة
            if revived:
                self.battery, self.fear = 100.0, 0.0
            self.next_n, self.state, self.trans_t = n, 'trans', 0.0

    # ---- الموت والتفرّج
    def spectating(self):
        return bool(self.net) and self.state in ('play', 'pause') and self.me_status != 'alive'

    def die(self, why):
        if self.me_status != 'alive':
            return
        self.me_status, self.me_why, self.died_t = 'dead', why, 0.0
        self.net.send({'t': 'die', 'e': self.epoch, 'x': int(self.px), 'y': int(self.py), 'why': why})
        self.ghosts, self.eyes, self.later, self.dlg = [], [], [], None
        self.app = self.dash = self.hall = self.say = None
        self.blackout = 0.0
        self.shake = 1.0
        play('shriek')
        self.js_t = self.js_dur = 1.3                  # وش الوحش لحظة الموت
        self.js_after, self.js_text = None, ""
        self.js_face = random.choice(A['faces'])

    def spec_targets(self):
        return [pid for pid, p in sorted(self.peers.items())
                if pid != self.pid and p.get('st') == 'alive' and p.get('dx') is not None]

    def spec_cycle(self, d=1):
        tg = self.spec_targets()
        if tg:
            i = tg.index(self.spec_pid) if self.spec_pid in tg else -1
            self.spec_pid = tg[(i + d) % len(tg)]

    def spectate_tick(self, dt):
        self.died_t += dt
        self.fear = 0.0
        self.blackout = self.glitch_t = 0.0
        self.hall = self.say = self.app = self.dash = None
        self.eyes, self.later, self.dlg = [], [], None
        tg = self.spec_targets()
        if self.spec_pid not in tg:
            self.spec_pid = tg[0] if tg else None
        p = self.peers.get(self.spec_pid)
        if not p or p.get('dx') is None:
            self.ghosts = []
            return
        self.px, self.py, self.fx, self.fy = p['dx'], p['dy'], p['fx'], p['fy']      # الكاميرا على اللاعب اللي بنتفرّج عليه
        self.moving = bool(p['fl'] & 2)
        self.flash, self.battery = bool(p['fl'] & 1), 100.0
        self.ghosts = [dict(x=g[0], y=g[1], a=g[2], say=None) for g in p['g']]     # الوحوش اللي بتطارده
        for o in self.objs:
            if o.kind == 'door':
                o.solid = o.can = o.id not in p['op']

    def net_play(self, dt):
        """كل فريم أثناء اللعب أونلاين: لو لسه عايش بنبعت مكانّا، ولو مش عايش بنتفرّج"""
        if self.me_status != 'alive':
            self.spectate_tick(dt)
            return
        self.pos_t -= dt
        if self.pos_t <= 0:
            self.pos_t = 1 / 12
            gl = [[int(g['x']), int(g['y']), round(max(0.0, g['a']), 2)] for g in self.ghosts[:4]]
            self.net.send({'t': 'pos', 'e': self.epoch, 'x': int(self.px), 'y': int(self.py),
                           'fx': round(self.fx, 2), 'fy': round(self.fy, 2),
                           'f': (1 if self.flash_ok() else 0) | (2 if self.moving else 0), 'g': gl})
        op = sorted(self.opened)
        if op != self.op_sent:
            self.op_sent = op
            self.net.send({'t': 'op', 'e': self.epoch, 'ids': op})

    # ------------------------------------------------ خضّات
    def scare(self, kind, after=None, text=""):
        D = diff(getattr(self, 'level', 1))
        self.cd = max(self.cd if hasattr(self, 'cd') else 0, D['cd'])
        if kind in ('face', 'flash'):
            dur = 1.5 if kind == 'face' else 0.32
            self.js_t = self.js_dur = dur
            self.js_after, self.js_text = after, text
            self.js_face = random.choice(A['faces'])
            self.fear = min(100, self.fear + (22 if kind == 'face' else 8))
            self.shake = 0.6
            play(random.choice(('scare', 'shriek')) if kind == 'face' else 'static')
            if kind == 'face' and text and text == self.name():
                self.voice(1.0, 'v_choir')
            if kind == 'face':
                self.after(dur + 0.4, lambda: play('breath', 0.7))
                if self.level >= 3 and random.random() < 0.2:          # خضّة تانية بعد ما تهدا
                    self.after(dur + 3.2, lambda: self.scare('flash'))
        elif kind == 'bang':
            play('bang')
            self.shake = 0.5
            self.fear = min(100, self.fear + 14)
            self.toast("حاجة وقعت وراك!!", 2.5)
            self.app = [self.px - self.fx * 150, self.py - self.fy * 150, 0.45]
            if self.level >= 2 and random.random() < 0.4:
                self.after(1.2, lambda: play('laugh', 0.6))
        elif kind == 'flicker':
            self.blackout = 3.0
            self.fear = min(100, self.fear + 10)
            play('whisper', 0.9)
            self.toast("كل الأنوار طفت!...", 3)
            self.after(1.4, lambda: play('step', 0.6))
            self.after(2.0, lambda: play('creak', 0.6))
            self.after(2.5, lambda: play('breath', 0.7))
            if self.level >= 4 and random.random() < 0.5:
                self.after(3.1, lambda: self.spawn_ghost(near=True, force=True))
        elif kind == 'name':
            self.name_sequence()
        elif kind == 'near':
            self.fear = min(100, self.fear + 8)
            play('whisper', 0.8)
            self.spawn_ghost(near=True, force=True)
        elif kind == 'dash':                       # ضلّ بيجري قدامك بسرعة
            self.dash = dict(t=0.0, dur=0.55, dir=random.choice((-1, 1)))
            play('shriek', 0.8)
            play('bang', 0.5)
            self.shake = 0.5
            self.fear = min(100, self.fear + 14)
        elif kind == 'knock':                      # خبط من جوه الحيطة
            play('knock', 1.0)
            self.shake = 0.3
            self.fear = min(100, self.fear + 8)
            self.toast("حد بيخبط... من جوه الحيطة!", 3)
            if self.level >= 3 and random.random() < 0.4:
                self.after(2.0, lambda: self.scare('name'))
        elif kind == 'eyes':                       # عيون في الضلمة
            self.fear = min(100, self.fear + 6)
            self.spawn_eyes(random.choice((2, 3)), 160, 380)
            self.toast("حاسس إن في عيون بتبصلك من الضلمة...", 3)
        elif kind == 'watch':                      # شبح بيتحرك لما تدير ضهرك
            if self.spawn_watcher():
                self.fear = min(100, self.fear + 6)
            else:
                self.scare('near')

    def name_sequence(self):
        """أرعب نداء: صمت تام... نفس... اسمك بالمقلوب... همس في ودنك... الاسم بيتكتب حرف حرف...
        وبعدين كورال شياطين من ورا ضهرك... وآخرها وش بيصرخ باسمك"""
        nm = self.name()
        self.cd = max(self.cd, 45)
        self.fear = min(100, self.fear + 15)
        self.blackout = 6.0                                   # ضلمة تامة
        self.heart_t = 5.0
        if AUDIO and 'drone' in SND:
            SND['drone'].set_volume(0)                        # الصمت قبل العاصفة
        self.after(0.6, lambda: play('breath', 0.9))
        self.after(1.8, lambda: self.voice(0.55, 'v_rev'))    # الاسم بالمقلوب
        self.after(3.2, lambda: (self.voice(0.85, 'v_whisper'), play('creak', 0.5)))
        gap = min(0.22, 1.8 / max(1, len(nm)))
        for i in range(1, len(nm) + 1):                       # الاسم بيتكتب قدامك حرف حرف
            self.after(3.4 + gap * i, lambda i=i: setattr(self, 'say', [nm[:i], 2.2]))

        def behind():
            self.shake = 1.0
            self.fear = min(100, self.fear + 25)
            self.voice(1.0, 'v_choir')
            play('bang', 0.6)
            play('heart', 1.0)
            self.after(0.45, lambda: play('heart', 1.0))
            self.app = [self.px - self.fx * 70, self.py - self.fy * 70, 1.6]
            self.say = [nm, 2.4]
        self.after(5.4, behind)
        self.after(7.6, lambda: apply_volume())
        self.after(8.4, lambda: self.voice(0.9, 'v_child'))   # من ناحية تانية
        self.after(10.2, lambda: self.scare('face', text=nm))  # وش بيصرخ باسمك

    def roll_scare(self):
        """احتمال خضّة وإنت بتقلّب في حاجة (بتزيد مع المراحل)"""
        if self.cd > 0 or random.random() > min(0.35, 0.08 + 0.025 * self.level):
            return None
        return random.choice(['face', 'face', 'bang', 'bang', 'flicker', 'flicker', 'dash', 'knock', 'eyes'])

    def ambient(self, kind):
        play(kind, 0.6 if kind in ('creak', 'whisper', 'step') else 0.8)
        if kind in ('slam', 'knock'):
            self.shake = max(self.shake, 0.3)
        self.toast(AMB_TEXT[kind], 3)
        self.fear = min(100, self.fear + (5 if kind in ('laugh', 'cry', 'musicbox', 'slam', 'knock') else 3))

    def first_visit(self):
        """أول مرة تدخل أوضة: ساعات حاجة بتحصل"""
        if self.sc_cd > 0 or self.cd > 3:
            return
        if random.random() < (0.22 if self.level == 1 else 0.38):
            self.sc_cd = random.uniform(20, 35)
            kinds = ['slam', 'slam', 'knock', 'breath']
            if self.level >= 2:
                kinds += ['laugh', 'cry']
            if self.level >= 3:
                kinds.append('musicbox')
            k = random.choice(kinds)
            if k == 'slam':
                play('slam', 0.9)
                self.shake = 0.35
                self.toast("الباب اتقفل وراك بقوة!", 3)
                self.fear = min(100, self.fear + 6)
            else:
                self.ambient(k)

    def dark_company(self):
        """الكشاف مات... والضلمة مش فاضية"""
        if self.flash_ok():
            return
        play('breath', 0.9)
        self.toast("في الضلمة... حد بيتنفّس جنبك.", 3)
        self.fear = min(100, self.fear + 8)
        self.after(2.2, lambda: None if self.flash_ok() else self.scare('near'))

    def wall_at(self, x, y):
        tx, ty = int(x // T), int(y // T)
        lv = self.lv
        return tx < 0 or ty < 0 or tx >= lv.W or ty >= lv.H or lv.grid[ty][tx] == 1

    def spawn_eyes(self, n=2, dmin=170, dmax=420):
        if len(self.eyes) >= 4:
            return
        tx, ty = int(self.px // T), int(self.py // T)
        rect = None
        for _nm, (x, y, w, h), _c in self.lv.rooms:
            if x <= tx < x + w and y <= ty < y + h:
                rect = (x, y, w, h)
                break
        if not rect:
            return
        x0, y0, w, h = rect
        for _ in range(n):
            for _t in range(40):
                ex = (x0 + random.randrange(w)) * T + 16
                ey = (y0 + random.randrange(h)) * T + 16
                d = math.hypot(ex - self.px, ey - self.py)
                if dmin <= d <= dmax and not self.blocked(pygame.Rect(ex - 8, ey - 8, 16, 16)):
                    self.eyes.append(dict(x=float(ex), y=float(ey), t=0.0, life=random.uniform(6, 11),
                                          ph=random.random() * 4))
                    break
        if self.eyes:
            play('whisper', 0.35)

    def spawn_watcher(self):
        """شبح واقف في الضلمة: مش بيتحرك طول ما إنت بتبصله... أول ما تدير ضهرك بيقرّب"""
        if len(self.ghosts) >= 3:
            return False
        for sgn in (1, -1):
            best = 0
            for dist in range(80, 361, 20):
                r = pygame.Rect(int(self.px + self.fx * sgn * dist) - 10, int(self.py + self.fy * sgn * dist) - 10, 20, 20)
                if self.blocked(r):
                    break
                best = dist
            if best >= 160:
                self.ghosts.append(dict(x=self.px + self.fx * sgn * best, y=self.py + self.fy * sgn * best,
                                        a=0.0, life=20.0, say=None, kind='watch', t=1.2))
                play('whisper', 0.6)
                self.toast("فيه حاجة واقفة في الضلمة... متدّيش ضهرك!", 3.5)
                return True
        return False

    def update_watcher(self, g, dt, d, gx, gy, facing):
        g['life'] -= dt
        looking = facing > 0.5
        lit = self.flash_ok() and looking and d < 330
        if g['life'] > 0:
            g['a'] = min(0.9, g['a'] + dt * 0.9)
        else:
            g['a'] -= dt * 0.8
        if lit:
            g['life'] -= dt * 3
        if g['a'] <= 0 and g['life'] <= 0:
            self.ghosts.remove(g)
            return False
        if not looking:                              # ضهرك ليه = بيقرّب
            g['t'] -= dt
            if g['t'] <= 0:
                g['t'] = random.uniform(0.8, 1.5)
                nx, ny = g['x'] + gx / d * 85, g['y'] + gy / d * 85
                if not self.wall_at(nx, ny):
                    g['x'], g['y'] = nx, ny
                    play('step', 0.45)
                    self.fear = min(100, self.fear + 3)
        if d < 320:
            self.fear = min(100, self.fear + 5 * dt)
        if d < 95 and g['a'] > 0.4:
            if self.net:                             # أونلاين: لمسة الوحش = موت
                self.die('ghost')
                return True
            self.ghosts.remove(g)
            self.scare('face', text=self.name())
            return True
        return False

    def add_decals(self):
        """بعد ما النور يرجع: كتابة بالدم وبصمات إيد ظهرت"""
        new = []
        px, py = self.px + self.fx * 120, self.py + self.fy * 120
        if not self.blocked(pygame.Rect(int(px) - 40, int(py) - 14, 80, 28)):
            word = self.name() if (self.level >= 3 and random.random() < 0.4) else random.choice(DECAL_WORDS)
            new.append(dict(kind='text', x=px, y=py, text=word, size=34, ang=random.randint(-12, 12)))
        for _ in range(random.randint(1, 2)):
            hx, hy = self.px + random.randint(-110, 110), self.py + random.randint(-90, 90)
            if not self.blocked(pygame.Rect(int(hx) - 10, int(hy) - 10, 20, 20)):
                new.append(dict(kind='hand', x=hx, y=hy, ang=random.randint(-40, 40)))
        self.decals = (self.decals + new)[-12:]
        if new:
            play('whisper', 0.5)

    def snuff_candle(self):
        lit = [i for i, (cx, cy) in enumerate(self.lv.candles)
               if i not in self.out_c and 80 < math.hypot(cx * T + 16 - self.px, cy * T + 16 - self.py) < 380]
        if not lit or len(self.out_c) >= max(1, len(self.lv.candles) // 2):
            return
        self.out_c.add(random.choice(lit))
        play('snuff', 0.8)
        self.toast("الشمعة طفت لوحدها!", 3)
        self.fear = min(100, self.fear + 4)
        if random.random() < 0.5:
            self.after(1.0, lambda: play('whisper', 0.6))

    def spawn_ghost(self, near=False, force=False):
        D = diff(self.level)
        if not force and len(self.ghosts) >= D['gmax']:
            return
        if not near and self.level >= 2 and random.random() < 0.35 and self.spawn_watcher():
            self.ghost_cd = random.uniform(0.7, 1.2) * D['gcd']
            return
        if near:
            x, y = self.px - self.fx * 230, self.py - self.fy * 230
        else:
            for _ in range(60):
                tx, ty = random.choice(self.lv.floors)
                x, y = tx * T + 16, ty * T + 16
                if 380 < math.hypot(x - self.px, y - self.py) < 700:
                    break
        g = dict(x=x, y=y, a=0.3 if near else 0.0, life=14.0, say=None)
        if self.level >= 2 and random.random() < 0.6:
            g['say'] = [self.name_line(), 5.0]
            self.after(0.8, lambda: self.voice(0.7, 'v_whisper'))
        self.ghosts.append(g)
        self.ghost_cd = random.uniform(0.7, 1.2) * D['gcd']
        if not near:
            self.toast("حاسس إن في حد بيراقبك...", 3)
        play('whisper', 0.7)

    # ------------------------------------------------ تفاعل
    def nearest(self):
        best, bd = None, 1e9
        for o in self.objs:
            if o.can and o.rect.inflate(44, 44).collidepoint(self.px, self.py):
                d = math.hypot(o.rect.centerx - self.px, o.rect.centery - self.py)
                if d < bd:
                    best, bd = o, d
        return best

    def interact(self):
        o = self.nearest()
        if not o:
            return
        k = o.kind
        if k in ('flavor', 'note'):
            sc = self.roll_scare()
            self.dialog(o.title, o.text, on_close=(lambda: self.scare(sc)) if sc else None)
        elif k == 'battery':
            if o.id in self.done:
                self.toast("دوّرت تاني... مفيش حاجة.")
            else:
                self.done.add(o.id)
                self.spare += 1
                play('pickup')
                self.toast(S("لقيت بطارية للكشاف {w}!", w=o.where), 3.5)
                sc = self.roll_scare()
                if sc:
                    self.after(1.2, lambda: self.scare(sc))
        elif k == 'special':
            self.interact_special(o)
        elif k == 'container':
            self.open_container(o)
        elif k == 'door':
            if o.need in self.inv:
                o.solid = o.can = False
                self.opened.add(o.id)
                play('unlock')
                self.toast(o.toast, 3)
            else:
                self.dialog(o.title, o.locked)
        elif k == 'exit':
            if o.need in self.inv:
                if self.level >= 3 and random.random() < 0.5:      # آخر لحظة: حاجة بتطلعلك قدام الباب
                    self.scare('face', after=self.go_next)
                else:
                    self.go_next()
            else:
                self.dialog(o.title, o.locked)

    def interact_special(self, o):
        self.fear = min(100, self.fear + 6)
        if o.sp == 'piano':
            play('creak', 0.8)
            self.toast("النغمة طلعت من البيانو... وإيدك لسه ما لمستوش!", 3.5)
        elif o.sp == 'mirror':
            if o.id in self.done:
                play('whisper', 0.6)
                self.toast("المراية ساكتة... بس حاسس إنها مستنية.", 3)
            else:
                self.done.add(o.id)
                self.dialog("المراية الكبيرة", ["بصّيت في المراية... مفيش غير انعكاسك.",
                                                "لحظة... ليه انعكاسك بيبتسم؟"],
                            on_close=lambda: self.scare('face'))
        elif o.sp == 'doll':
            if o.id in self.done:
                play('laugh', 0.7)
                self.toast("الدُمية بتبصلك... ومكانها اتغيّر!", 3)
            else:
                self.done.add(o.id)

                def doll_end():
                    play('laugh', 0.9)
                    self.shake = 0.4
                    self.after(1.1, lambda: self.scare('bang'))
                self.dialog("الدُمية الكبيرة", ["دُمية قديمة وعنيها زجاج لامع.",
                                                 "رقبتها مايلة ناحيتك... مكانتش كده من شوية."],
                            on_close=doll_end)
        else:
            play('whisper', 0.8)
            self.dialog("الصورة", ["راجل عينيه بتتابعك في كل مكان...", "ويمكن عينيه اتحركت فعلًا."])

    def open_container(self, o):
        if o.id in self.done:
            self.toast(o.empty)
            return
        if o.need and o.need not in self.inv:
            self.dialog(o.title, o.locked)
            return
        self.done.add(o.id)
        if o.give:
            self.inv.add(o.give)
            play('pickup')

        def show():
            on = None
            if o.finale:
                on = lambda: (self.scare('flicker'), self.after(2.0, lambda: self.scare('face')))
            self.dialog(o.title, o.lines, on_close=on)
        if o.scare == 'face':
            self.scare('face', after=show)
        else:
            if o.scare:
                self.scare(o.scare)
            show()

    # ------------------------------------------------ تحديث
    def blocked(self, r):
        lv = self.lv
        for ty in range(r.top // T, (r.bottom - 1) // T + 1):
            for tx in range(r.left // T, (r.right - 1) // T + 1):
                if tx < 0 or ty < 0 or tx >= lv.W or ty >= lv.H or lv.grid[ty][tx] == 1:
                    return True
        return any(o.solid and r.colliderect(o.rect) for o in self.objs)

    def tick_js(self, dt):
        if self.js_t > 0:
            self.js_t -= dt
            if self.js_t <= 0 and self.js_after:
                fn, self.js_after = self.js_after, None
                fn()

    def update(self, dt):
        self.t += dt
        D = diff(self.level)
        self.shake = max(0.0, self.shake - dt)
        if self.toast_t > 0:
            self.toast_t -= dt
        if self.state == 'pause' and not self.net:     # أونلاين: اللعبة مبتقفش لما تفتح القايمة
            return
        if self.say:
            self.say[1] -= dt
            if self.say[1] <= 0:
                self.say = None
        for it in self.later[:]:
            it[0] -= dt
            if it[0] <= 0:
                self.later.remove(it)
                it[1]()
        if self.app:
            self.app[2] -= dt
            if self.app[2] <= 0:
                self.app = None
        if self.dash:
            self.dash['t'] += dt
            if self.dash['t'] >= self.dash['dur']:
                self.dash = None
        if self.hall:
            self.hall[0] -= dt
            if self.hall[0] <= 0:
                self.hall = None
        if self.glitch_t > 0:
            self.glitch_t -= dt
        paused_net = bool(self.net) and self.state == 'pause'
        if self.net:
            self.net_play(dt)
            if self.me_status != 'alive':
                return
        if self.js_t > 0 or self.dlg or (self.state != 'play' and not paused_net):
            return
        if self.net and self.fear >= FEAR_DEATH - 0.01:          # الخوف اتملى = موت
            self.die('fear')
            return

        if self.blackout > 0:
            self.blackout -= dt
            if self.blackout <= 0:
                self.toast("النور رجع...", 2)
                self.add_decals()
        self.cd -= dt
        self.voice_cd -= dt
        self.sc_cd -= dt
        self.phantom_cd -= dt

        k = pygame.key.get_pressed()
        dx = (k[pygame.K_d] or k[pygame.K_RIGHT]) - (k[pygame.K_a] or k[pygame.K_LEFT])
        dy = (k[pygame.K_s] or k[pygame.K_DOWN]) - (k[pygame.K_w] or k[pygame.K_UP])
        if self.joy[0] or self.joy[1]:                                # جويستيك اللمس
            dx, dy = self.joy
        if paused_net:                                                # قايمة الأونلاين: الأسهم للقايمة مش للحركة
            dx = dy = 0
        self.moving = bool(dx or dy)
        if (self.was_moving and not self.moving and self.level >= 2 and self.fear > 20
                and self.phantom_cd <= 0 and random.random() < 0.35):
            self.phantom_cd = random.uniform(25, 45)              # وقفت؟ فيه خطوات لسه جاية ناحيتك
            for i, dl in enumerate((0.45, 0.9, 1.35)):
                self.after(dl, lambda i=i: play('foot1' if i % 2 == 0 else 'foot2', 0.38 - 0.08 * i))
            self.after(1.9, lambda: play('breath', 0.5))
        self.was_moving = self.moving
        if dx or dy:
            n = math.hypot(dx, dy)
            dx, dy = dx / n, dy / n
            self.fx, self.fy = dx, dy
            run = k[pygame.K_LSHIFT] or k[pygame.K_RSHIFT] or self.joy_run
            sp = 190 if run else 125
            nx = self.px + dx * sp * dt
            if not self.blocked(pygame.Rect(int(nx) - 10, int(self.py) - 10, 20, 20)):
                self.px = nx
            ny = self.py + dy * sp * dt
            if not self.blocked(pygame.Rect(int(self.px) - 10, int(ny) - 10, 20, 20)):
                self.py = ny
            self.step_t -= dt
            if self.step_t <= 0:
                self.foot = not getattr(self, 'foot', False)
                play('foot1' if self.foot else 'foot2', FOOTSTEP_VOL * (1.5 if run else 1.0))
                self.step_t = 0.38 if run else 0.55
                if self.level >= 2 and random.random() < 0.08 + self.fear / 700:
                    self.after(0.3, lambda: play('foot2', 0.3))          # صدى خطوة ورا ضهرك

        if self.battery <= 0 and self.spare > 0:
            self.spare -= 1
            self.battery = 100.0
            self.dead_warned = False
            self.toast("غيّرت بطارية الكشاف.", 2)
        if self.flash_ok():
            self.battery = max(0.0, self.battery - D['drain'] * dt)
            if self.battery <= 0 and not self.dead_warned:
                self.dead_warned = True
                self.toast("الكشاف فصل! دوّر على بطاريات.", 3)
                if self.spare <= 0:
                    self.after(2.6, self.dark_company)

        tx, ty = int(self.px // T), int(self.py // T)
        for ri, (nm, (x, y, w, h), _c) in enumerate(self.lv.rooms):
            if x <= tx < x + w and y <= ty < y + h:
                self.room = nm
                if ri not in self.visited:
                    self.visited.add(ri)
                    if len(self.visited) > 1:
                        self.first_visit()

        pr = pygame.Rect(int(self.px) - 10, int(self.py) - 10, 20, 20)
        for tr in self.lv.triggers:
            if not tr['fired'] and self.cd <= 0 and pr.colliderect(tr['rect']):
                tr['fired'] = True
                self.scare(tr['kind'])
                break

        # عيون في الضلمة
        self.eye_cd -= dt
        if self.eye_cd <= 0:
            self.eye_cd = random.uniform(16, 30)
            if not self.eyes and self.blackout <= 0:
                self.spawn_eyes(random.choice((1, 2)))
        for e in self.eyes[:]:
            e['t'] += dt
            e['life'] -= dt
            ex, ey = e['x'] - self.px, e['y'] - self.py
            d = math.hypot(ex, ey) or 1
            e['x'] -= ex / d * 9 * dt
            e['y'] -= ey / d * 9 * dt
            lit = self.flash_ok() and d < 260 and (ex / d * self.fx + ey / d * self.fy) > 0.75
            if e['life'] <= 0 or lit or d < 70:
                self.eyes.remove(e)
                if lit or d < 70:
                    play('whisper', 0.5)
                    self.fear = min(100, self.fear + 5)
                    if random.random() < 0.4:
                        self.after(0.8, lambda: self.spawn_eyes(1, 110, 190))

        # الأشباح
        if len(self.ghosts) < D['gmax']:
            self.ghost_cd -= dt
            if self.ghost_cd <= 0:
                self.spawn_ghost()
        for g in self.ghosts[:]:
            gx, gy = self.px - g['x'], self.py - g['y']
            d = math.hypot(gx, gy) or 1
            facing = (-gx / d) * self.fx + (-gy / d) * self.fy
            if g.get('kind') == 'watch':
                if self.update_watcher(g, dt, d, gx, gy, facing):
                    break
                continue
            g['life'] -= dt
            g['a'] = min(1.0, g['a'] + dt * 0.5) if g['life'] > 0 else g['a'] - dt * 0.8
            if g['say']:
                g['say'][1] -= dt
                if g['say'][1] <= 0:
                    g['say'] = None
            if g['a'] <= 0 and g['life'] <= 0:
                self.ghosts.remove(g)
                continue
            rep = self.flash_ok() and d < 240 and facing > 0.6
            sp = -45 if rep else 62 + D['gspd'] + self.fear * 0.2
            if rep:
                g['life'] -= dt * 2.5
            g['x'] += gx / d * sp * dt
            g['y'] += gy / d * sp * dt
            if d < 320:
                self.fear = min(100, self.fear + 7 * dt)
                if random.random() < dt * 0.4:
                    play('whisper', 0.6 * (1 - d / 320))
                if d < 220 and random.random() < dt * 0.15:
                    play('breath', 0.5 * (1 - d / 220))
            if d < 300 and g['a'] > 0.4 and self.voice_cd <= 0:
                self.voice_cd = random.uniform(7, 12)
                g['say'] = [self.name_line(), 3.5]
                kv = 'v_whisper' if d > 170 else ('v_child' if (self.level >= 4 and random.random() < 0.3) else 'voice')
                self.voice(min(1.0, 1.15 - d / 300), kv)
            if d < 26 and g['a'] > 0.5:
                if self.net:                         # أونلاين: لمسة الوحش = موت
                    self.die('ghost')
                    return
                self.ghosts.remove(g)
                self.scare('face', text=self.name() if (self.level >= 2 and random.random() < 0.6) else "")
                break

        near_candle = any(ci not in self.out_c and
                          math.hypot(cx * T + 16 - self.px, cy * T + 16 - self.py) < 110
                          for ci, (cx, cy) in enumerate(self.lv.candles))
        seen = any(g['a'] > 0.2 for g in self.ghosts)
        if near_candle and self.blackout <= 0:
            self.fear = max(0, self.fear - 6 * dt)
        elif not self.flash_ok() and self.fear < 45:
            self.fear += 2.5 * dt
        elif self.fear > 0 and not seen:
            self.fear = max(0, self.fear - 1.2 * dt)
        if self.fear > 35:
            self.heart_t -= dt
            if self.heart_t <= 0:
                play('heart', self.fear / 100 + 0.2)
                self.heart_t = 1.2 - 0.7 * self.fear / 100

        # الشموع بتطفي لوحدها
        self.snuff_cd -= dt
        if self.snuff_cd <= 0:
            self.snuff_cd = random.uniform(22, 40)
            if self.level >= 2:
                self.snuff_candle()

        # هلوسة: حاجة بتلمع في طرف عينك لحظة
        if self.fear > 55 and self.hall is None and random.random() < dt * (self.fear - 50) / 220:
            self.hall = [random.uniform(0.15, 0.3), random.choice(['ghost', 'word', 'eyes']),
                         random.randint(80, SW - 80), random.randint(220, SH - 150),
                         random.choice(HALL_WORDS + [self.name()])]
        if self.fear > 65 and self.glitch_t <= 0 and random.random() < dt * 0.8 * (self.fear - 60) / 40:
            self.glitch_t = 0.12

        self.amb -= dt
        if self.amb <= 0:
            self.amb = random.uniform(0.7, 1.2) * D['amb']
            kinds = ['creak', 'whisper', 'step', 'knock', 'breath']
            if self.level >= 2:
                kinds += ['cry', 'laugh', 'slam']
            if self.level >= 3:
                kinds.append('musicbox')
            self.ambient(random.choice(kinds))

    # ------------------------------------------------ رسم
    def draw(self, s):
        st = self.state
        if st in ('title', 'profile'):
            self.draw_title(s)
        elif st == 'online':
            self.draw_online(s)
        elif st == 'trans':
            self.draw_trans(s)
        else:
            self.draw_world(s)
            if st == 'pause':
                self.draw_pause(s)
            elif st == 'win':
                self.draw_win(s)
        if self.js_t > 0:
            self.draw_js(s)

    def draw_decal(self, s, dc, cx, cy):
        x, y = int(dc['x'] - cx), int(dc['y'] - cy)
        if x < -140 or y < -140 or x > SW + 140 or y > SH + 140:
            return
        if dc['kind'] == 'hand':
            draw_hand(s, x, y, dc['ang'])
        else:
            surf = pygame.transform.rotate(txt(dc['text'], dc['size'], (150, 14, 14)), dc['ang'])
            s.blit(surf, (x - surf.get_width() // 2, y - surf.get_height() // 2))

    def draw_dash(self, s):
        d = self.dash
        k = d['t'] / d['dur']
        spr = A['ghost_big'] if d['dir'] > 0 else A['ghost_big_f']
        w, h = spr.get_size()
        x = -w + (SW + w) * k if d['dir'] > 0 else SW - (SW + w) * k
        y = SH - h + 120 + math.sin(self.t * 40) * 6
        red = pygame.Surface((SW, SH))
        red.fill((120, 0, 0))
        red.set_alpha(55)
        s.blit(red, (0, 0))
        spr.set_alpha(235)
        s.blit(spr, (int(x), int(y)))
        for ex in (109, 143):
            lx = ex if d['dir'] > 0 else w - ex
            glow(s, int(x + lx), int(y + 85), 26, (255, 40, 30), 240)

    def glitch(self, s):
        snap = s.copy()
        for _ in range(random.randint(2, 4)):
            y = random.randint(0, SH - 40)
            s.blit(snap, (random.randint(-30, 30), y), (0, y, SW, random.randint(6, 30)))
        for _ in range(8):
            y = random.randint(0, SH)
            pygame.draw.line(s, (120, 0, 0), (0, y), (SW, y), 1)

    def tiles(self):
        """الأرضيات والحيطان بتترسم مرة واحدة لكل مرحلة وبعدين بس بننسخ الجزء اللي ظاهر"""
        lv = self.lv
        bg = getattr(lv, '_bg', None)
        if bg is None:
            bg = pygame.Surface((lv.W * T, lv.H * T))
            bg.fill((0, 0, 0))
            grid, floorc = lv.grid, lv.floorc
            for j in range(lv.H):
                for i in range(lv.W):
                    x, y = i * T, j * T
                    if grid[j][i] == 1:
                        pygame.draw.rect(bg, (44, 36, 34), (x, y, T, T))
                        if j + 1 < lv.H and grid[j + 1][i] == 0:
                            pygame.draw.rect(bg, (84, 62, 54), (x, y + T - 12, T, 12))
                    else:
                        c = floorc[j][i]
                        v = (i * 7 + j * 13) % 5 * 2
                        pygame.draw.rect(bg, (c[0] + v, c[1] + v, c[2] + v), (x, y, T, T))
                        pygame.draw.line(bg, (c[0] // 2, c[1] // 2, c[2] // 2), (x, y + T - 1), (x + T, y + T - 1))
            lv._bg = bg
        return bg

    def draw_world(self, s):
        lv = self.lv
        shx = shy = 0
        if self.shake > 0:
            shx, shy = random.randint(-6, 6), random.randint(-6, 6)
        elif self.fear > 75:
            shx, shy = random.randint(-1, 1), random.randint(-1, 1)
        cx = int(max(0, min(lv.W * T - SW, self.px - SW / 2))) + shx
        cy = int(max(0, min(lv.H * T - SH, self.py - SH / 2))) + shy
        s.fill((0, 0, 0))
        s.blit(self.tiles(), (-cx, -cy))
        for a, b, c_, d_, col in lv.rugs:
            pygame.draw.rect(s, col, (a * T - cx, b * T - cy, c_ * T, d_ * T), border_radius=6)
        for dc in self.decals:
            self.draw_decal(s, dc, cx, cy)
        for o in self.objs:
            r = o.rect.move(-cx, -cy)
            if r.right < 0 or r.bottom < 0 or r.left > SW or r.top > SH:
                continue
            if o.kind == 'door' and not o.solid:
                continue
            if 'هز' in str(o.name):                                   # الكرسي الهزّاز بيهتز لوحده
                r.x += int(math.sin(self.t * 2.2) * 2)
            pygame.draw.rect(s, o.color, r, border_radius=3)
            pygame.draw.rect(s, tuple(max(0, c - 40) for c in o.color), r, 3, border_radius=3)
            if o.kind in ('door', 'exit'):
                pygame.draw.circle(s, (220, 190, 60), (r.right - 8, r.centery), 4)
        for ci, (tx, ty) in enumerate(lv.candles):
            x, y = tx * T + 16 - cx, ty * T + 16 - cy
            pygame.draw.rect(s, (230, 225, 200), (x - 3, y - 2, 6, 12))
            if self.blackout <= 0 and ci not in self.out_c:
                pygame.draw.ellipse(s, (255, 190, 60), (x - 3, y - 9, 6, 8 + random.random() * 2))
        for g in self.ghosts:
            draw_ghost(s, g['x'] - cx, g['y'] - cy, int(max(0, g['a']) * 190), self.t)
        if self.net:
            self.draw_peers(s, cx, cy)
        px, py = int(self.px - cx), int(self.py - cy)
        if not self.hide_self():
            self.draw_player(s, px, py, tint=self.my_tint())

        dk = self.dark
        dk.fill((0, 0, 6, 255 if self.blackout > 0 else 250))
        if self.blackout <= 0:
            for ci, (tx, ty) in enumerate(lv.candles):
                if ci in self.out_c:
                    continue
                x, y = tx * T + 16 - cx, ty * T + 16 - cy
                if -150 < x < SW + 150 and -150 < y < SH + 150:
                    light(dk, x, y, 125 * (1 + 0.06 * math.sin(self.t * 9 + tx) + random.random() * 0.03), 215)
        light(dk, px, py, 56, 200)
        if self.flash_ok():
            m = 1.0
            if self.battery < 20 or self.fear > 70:
                m = random.choice([1, 1, 1, 0.85, 0.55])
            light(dk, int(px + self.fx * 55), int(py + self.fy * 55), 150 * m, 240)
            light(dk, int(px + self.fx * 150), int(py + self.fy * 150), 110 * m, 235)
        if self.net:                                                  # نور اللاعبين التانيين (وكشافاتهم)
            for pr in self.live_peers():
                rx, ry = int(pr['dx'] - cx), int(pr['dy'] - cy)
                light(dk, rx, ry, 56, 200)
                if pr['fl'] & 1:
                    light(dk, int(rx + pr['fx'] * 55), int(ry + pr['fy'] * 55), 120, 225)
                    light(dk, int(rx + pr['fx'] * 140), int(ry + pr['fy'] * 140), 90, 215)
        s.blit(dk, (0, 0))
        if self.net:                                                  # أسماء اللاعبين القريبين
            for pr in self.live_peers():
                if math.hypot(pr['dx'] - self.px, pr['dy'] - self.py) < 340:
                    draw_text(s, pr['name'], 16, PCOL[pr['slot'] % len(PCOL)], int(pr['dx'] - cx), int(pr['dy'] - cy) - 36, 'c')

        for e in self.eyes:                                           # عيون حمرا في الضلمة
            if (self.t * 0.9 + e['ph']) % 4 < 0.14:
                continue
            a = min(1.0, e['t'] * 1.5)
            ex, ey = int(e['x'] - cx), int(e['y'] - cy)
            if -30 < ex < SW + 30 and -30 < ey < SH + 30:
                for off in (-9, 9):
                    glow(s, ex + off, ey, 12, (255, 30, 20), (80, 140, 200)[min(2, int(a * 3))])
                    pygame.draw.ellipse(s, (255, 200, 190), (ex + off - 3, ey - 2, 6, 4))
        for g in self.ghosts:
            gxx, gyy = draw_ghost_pos(g['x'] - cx, g['y'] - cy, self.t)
            ghost_eyes(s, gxx, gyy, g['a'])
            if g['say'] and g['a'] > 0.3:
                draw_text(s, str(g['say'][0]).replace("{name}", self.name()), 24, (220, 30, 30), gxx + 48, gyy - 26, 'c')
        if self.app:
            gxx, gyy = draw_ghost(s, self.app[0] - cx, self.app[1] - cy, 225, self.t)
            ghost_eyes(s, gxx, gyy, 1.0)
        if self.dash:
            self.draw_dash(s)
        if self.hall:                                                 # هلوسة سريعة
            _t, kind, hx, hy, word = self.hall
            if kind == 'ghost':
                draw_ghost(s, hx, hy + 90, 150, self.t)
            elif kind == 'word':
                draw_text(s, word, 64, (200, 10, 10), hx, hy, 'c')
            else:
                for off in (-14, 14):
                    glow(s, hx + off, hy, 14, (255, 30, 20), 200)
        if self.say:
            draw_text(s, self.say[0], 52, (200, 20, 20), SW // 2 + random.randint(-4, 4),
                      SH // 2 - 130 + random.randint(-4, 4), 'c')
        if self.fear > 5:
            pulse = 1.0 + (0.12 * math.sin(self.t * (4 + self.fear / 15)) if self.fear > 40 else 0.0)
            A['vig'].set_alpha(min(255, int(255 * min(1, self.fear / 100) * pulse)))
            s.blit(A['vig'], (0, 0))
        if self.glitch_t > 0:
            self.glitch(s)
        self.draw_hud(s)
        if self.net:
            self.draw_roster(s)
        if self.show_map and not self.spectating():
            self.draw_map(s)

    def draw_map(self, s):
        lv = self.lv
        sc = min((SW - 160) / lv.W, (SH - 200) / lv.H)
        ox, oy = (SW - lv.W * sc) / 2, 100 + (SH - 200 - lv.H * sc) / 2
        ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 248))
        s.blit(ov, (0, 0))
        draw_text(s, "الخريطة - Tab للإغلاق", 30, (240, 200, 100), SW // 2, 36, 'c')
        seen = []
        for i, (nm, (x, y, w, h), c) in enumerate(lv.rooms):
            r = pygame.Rect(int(ox + x * sc), int(oy + y * sc), int(w * sc), int(h * sc))
            if i in self.visited:
                seen.append(pygame.Rect(x - 3, y - 3, w + 6, h + 6))
                pygame.draw.rect(s, tuple(min(255, v + 30) for v in c), r)
                pygame.draw.rect(s, (200, 170, 110), r, 1)
                if r.w > 70 and r.h > 24:
                    draw_text(s, nm, 16, (255, 255, 255), r.centerx, r.centery - 9, 'c')
            else:
                pygame.draw.rect(s, (46, 40, 38), r, 1)
        for o in self.objs:
            if o.kind in ('door', 'exit') and o.solid and any(z.collidepoint(o.rect.centerx // T, o.rect.centery // T) for z in seen):
                r = pygame.Rect(int(ox + o.rect.x / T * sc) - 2, int(oy + o.rect.y / T * sc) - 2,
                                max(5, int(o.rect.w / T * sc)) + 4, max(5, int(o.rect.h / T * sc)) + 4)
                pygame.draw.rect(s, (220, 40, 40) if o.kind == 'exit' else (230, 190, 60), r)
        pygame.draw.circle(s, (90, 200, 255), (int(ox + self.px / T * sc), int(oy + self.py / T * sc)), 5 + int(2 * math.sin(self.t * 6)))
        draw_text(s, "أحمر: باب الشقة   أصفر: باب مقفول   أزرق: إنت", 18, (180, 180, 180), SW // 2, SH - 40, 'c')

    def draw_player(self, s, px, py, tint=None, fx=None, fy=None, mv=None, flash=None, me=True):
        t = self.t
        fx = self.fx if fx is None else fx
        fy = self.fy if fy is None else fy
        mv = self.moving if mv is None else mv
        tint = tint or PCOL[0]
        edge = tuple(int(c * 0.58) for c in tint)
        hood = tuple(int(c * 0.73) for c in tint)
        bob = math.sin(t * 13) * 2 if mv else math.sin(t * 2) * 1
        pygame.draw.ellipse(s, (0, 0, 0), (px - 12, py + 6, 24, 10))
        tx, ty = px - fx * 18 + math.sin(t * 6) * 3, py + 12 - fy * 12
        cape = [(px - 9, py - 5 + bob), (px + 9, py - 5 + bob), (tx + 8, ty + 3), (tx - 8, ty - 2)]
        pygame.draw.polygon(s, tint, cape)
        pygame.draw.polygon(s, edge, cape, 2)
        pygame.draw.ellipse(s, (46, 66, 108), (px - 8, py - 8 + bob, 16, 20))
        pygame.draw.line(s, (200, 160, 60), (px - 8, py + 3 + bob), (px + 8, py + 3 + bob), 2)
        pygame.draw.rect(s, (30, 24, 24), (px - 6, py + 10, 5, 4))
        pygame.draw.rect(s, (30, 24, 24), (px + 1, py + 10 + (2 if mv and int(t * 8) % 2 else 0), 5, 4))
        hx, hy = px + fx * 2, py - 13 + bob
        pygame.draw.circle(s, hood, (int(px), int(py - 12 + bob)), 9)
        pygame.draw.circle(s, (232, 200, 168), (int(hx), int(hy + fy * 1.5)), 6)
        pygame.draw.circle(s, (20, 16, 16), (int(hx + fx * 2.5 - 2), int(hy + 1 + fy * 2)), 1)
        pygame.draw.circle(s, (20, 16, 16), (int(hx + fx * 2.5 + 2), int(hy + 1 + fy * 2)), 1)
        ax, ay = px + fx * 15, py - 2 + fy * 15 + bob
        pygame.draw.line(s, (232, 200, 168), (px + fx * 5, py - 2 + bob), (ax, ay), 3)
        pygame.draw.circle(s, (120, 120, 126), (int(ax), int(ay)), 4)
        if self.flash_ok() if flash is None else flash:
            glow(s, int(ax), int(ay), 14, (255, 240, 170), 200)
            pygame.draw.circle(s, (255, 250, 200), (int(ax + fx * 2), int(ay + fy * 2)), 2)
        if me:
            pygame.draw.circle(s, (90, 230, 255), (int(px), int(py - 1 + bob)), 2)

    def draw_bar(self, s, x, y, w, frac, color):
        pygame.draw.rect(s, (20, 20, 24), (x, y, w, 14))
        pygame.draw.rect(s, color, (x, y, int(w * max(0, min(1, frac))), 14))
        pygame.draw.rect(s, (150, 150, 150), (x, y, w, 14), 1)

    def draw_button(self, s, text, rect, selected=False, size=26):
        pygame.draw.rect(s, (60, 14, 14) if selected else (24, 20, 22), rect, border_radius=8)
        pygame.draw.rect(s, (200, 150, 80) if selected else (110, 90, 70), rect, 2, border_radius=8)
        draw_text(s, text, size, (255, 240, 210) if selected else (200, 190, 180), rect.centerx,
                  rect.centery - size * 0.7, 'c')

    def draw_hud(self, s):
        if self.spectating():
            self.draw_spec_hud(s)
            return
        panel = pygame.Surface((SW, 78), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 120))
        s.blit(panel, (0, 0))
        draw_text(s, "الكشاف", 20, (230, 230, 200), 16, 8, 'l')
        self.draw_bar(s, 90, 12, 150, self.battery / 100 if self.flash else 0, (240, 210, 90))
        draw_text(s, S("بطاريات: {n}", n=self.spare), 20, (230, 230, 200), 252, 8, 'l')
        draw_text(s, "الخوف", 20, (230, 160, 160), 16, 38, 'l')
        self.draw_bar(s, 90, 42, 150, self.fear / 100, (200, 30, 30))
        draw_text(s, S("الشقة {a} / {b}", a=self.level, b=MAX_LEVEL), 22, (240, 200, 120), SW // 2, 6, 'c')
        r = pygame.Rect(SW // 2 - 50, 38, 100, 30)
        if not self.net:
            self.draw_button(s, "حفظ" if TOUCH else "حفظ - K", r, False, 20)
        rx = SW - 16 - (125 if TOUCH else 0)                 # على اللمس: مكان لزراير الخريطة والقايمة
        draw_text(s, self.room, 26, (255, 255, 255), rx, 6, 'r')
        items = [str(self.lv.item_names[i]) if isinstance(self.lv.item_names[i], S) else tr(self.lv.item_names[i])
                 for i in ('ka', 'kb', 'small', 'exit') if i in self.inv and i in self.lv.item_names]
        draw_text(s, S("معاك: {i}", i=("، " if LANG == 'ar' else ", ").join(items) if items else "مفيش حاجة"), 18, (240, 210, 100), rx, 44, 'r')
        draw_text(s, S("الهدف: {g}", g=self.lv.goal(self)), 20, (200, 200, 200), 16, SH - 32, 'l')
        if not TOUCH:
            draw_text(s, "E: تفاعل   F: كشاف   Shift: جري   Tab: خريطة   Esc: قايمة", 18, (140, 140, 140), SW - 16, SH - 30, 'r')
        self.btns = [(r, 'save')] if (self.state == 'play' and not self.net) else []
        o = self.nearest()
        if o and not self.dlg and self.js_t <= 0 and self.state == 'play':
            draw_text(s, S("المس زر التفاعل - {n}" if TOUCH else "اضغط E - {n}", n=o.name), 24, (255, 255, 255), SW // 2, SH - 90, 'c')
        if self.toast_t > 0 and not self.dlg:
            t = txt(self.toast_s, 24, (255, 235, 200))
            bg = pygame.Surface((t.get_width() + 30, t.get_height() + 14), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 170))
            s.blit(bg, (SW // 2 - bg.get_width() // 2, 100))
            s.blit(t, (SW // 2 - t.get_width() // 2, 107))
        if self.dlg:
            rtl = LANG == 'ar'
            lines = [tr(str(x)).replace("{name}", self.name()) for x in self.dlg]
            n = len(lines)
            h = 90 + 34 * n
            box = pygame.Surface((SW - 120, h), pygame.SRCALPHA)
            box.fill((10, 8, 8, 235))
            by = SH - h - 30
            s.blit(box, (60, by))
            pygame.draw.rect(s, (150, 120, 70), (60, by, SW - 120, h), 2)
            ax, al = (SW - 84, 'r') if rtl else (84, 'l')
            draw_text(s, self.dlg_title, 26, (240, 200, 100), ax, by + 10, al)
            for i, ln in enumerate(lines):
                draw_text(s, ln, 24, (230, 230, 230), ax, by + 50 + i * 34, al)
            draw_text(s, "المس الشاشة للمتابعة" if TOUCH else "اضغط E للمتابعة", 18, (150, 150, 150), 84 if rtl else SW - 84, by + h - 28, 'l' if rtl else 'r')

    def draw_js(self, s):
        el = self.js_dur - self.js_t
        if el < 0.07:
            s.fill((255, 255, 255))
            return
        s.fill((8, 0, 0))
        z = 2.2 + el * 0.5
        f = pygame.transform.scale(self.js_face or A['faces'][0], (int(300 * z), int(380 * z)))
        ox, oy = random.randint(-10, 10), random.randint(-10, 10)
        s.blit(f, (SW // 2 - f.get_width() // 2 + ox, SH // 2 - f.get_height() // 2 + oy - 40))
        red = pygame.Surface((SW, SH))
        red.fill((170, 0, 0))
        red.set_alpha(60 + random.randint(0, 30))
        s.blit(red, (0, 0))
        if self.js_text:
            draw_text(s, self.js_text, 72, (230, 20, 20), SW // 2 + random.randint(-6, 6),
                      SH - 170 + random.randint(-6, 6), 'c')
        fade = min(0.35, self.js_dur * 0.4)
        if self.js_t < fade:
            blk = pygame.Surface((SW, SH))
            blk.set_alpha(int(255 * (1 - self.js_t / fade)))
            s.blit(blk, (0, 0))

    # ------------------------------------------------ رسم الأونلاين
    def live_peers(self):
        """اللاعبين التانيين الأحياء اللي ليهم مكان (من غير اللي بنتفرّج عليه، لأنه هو الكاميرا)"""
        skip = self.spec_pid if self.spectating() else None
        return [p for pid, p in self.peers.items()
                if pid != self.pid and pid != skip and p.get('st') == 'alive' and p.get('dx') is not None]

    def hide_self(self):
        return self.spectating() and self.spec_pid not in self.peers

    def my_tint(self):
        if not self.net:
            return None
        if self.spectating():
            p = self.peers.get(self.spec_pid)
            return PCOL[p['slot'] % len(PCOL)] if p else None
        return PCOL[self.slot % len(PCOL)]

    def draw_peers(self, s, cx, cy):
        for pid, p in self.peers.items():                             # قبور اللي ماتوا
            if pid != self.pid and p.get('st') == 'dead':
                gx, gy = p.get('gx', 0) - cx, p.get('gy', 0) - cy
                if -40 < gx < SW + 40 and -40 < gy < SH + 40:
                    pygame.draw.rect(s, (56, 56, 62), (gx - 3, gy - 18, 6, 26))
                    pygame.draw.rect(s, (56, 56, 62), (gx - 10, gy - 11, 20, 6))
                    pygame.draw.rect(s, PCOL[p['slot'] % len(PCOL)], (gx - 10, gy - 11, 20, 6), 1)
        for p in self.live_peers():
            self.draw_player(s, int(p['dx'] - cx), int(p['dy'] - cy), tint=PCOL[p['slot'] % len(PCOL)],
                             fx=p['fx'], fy=p['fy'], mv=bool(p['fl'] & 2), flash=bool(p['fl'] & 1), me=False)

    def draw_roster(self, s):
        y = 104 if self.spectating() else 88
        for p in sorted(self.peers.values(), key=lambda q: q['slot']):
            col = PCOL[p['slot'] % len(PCOL)]
            st = p.get('st')
            bx = pygame.Rect(SW - 28, y + 2, 14, 14)
            pygame.draw.rect(s, col if st == 'alive' else tuple(c // 3 for c in col), bx)
            if p['slot'] == self.slot:
                pygame.draw.rect(s, (255, 255, 255), bx.inflate(4, 4), 1)
            if st == 'dead':
                pygame.draw.line(s, (230, 40, 40), bx.topleft, bx.bottomright, 3)
                pygame.draw.line(s, (230, 40, 40), bx.topright, bx.bottomleft, 3)
            elif st == 'escaped':
                pygame.draw.lines(s, (120, 230, 120), False, [(bx.x + 2, bx.centery), (bx.x + 6, bx.bottom - 3), (bx.right - 2, bx.y + 3)], 3)
            draw_text(s, p['name'], 17, (235, 235, 235) if st == 'alive' else (140, 140, 140), SW - 36, y, 'r')
            y += 22

    def draw_spec_hud(self, s):
        panel = pygame.Surface((SW, 96), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 150))
        s.blit(panel, (0, 0))
        dead = self.me_status == 'dead'
        draw_text(s, S("الشقة {a} / {b}", a=self.level, b=MAX_LEVEL), 22, (240, 200, 120), SW // 2, 6, 'c')
        draw_text(s, "إنت مُتّ!" if dead else "هربت من الشقة!", 28, (225, 60, 60) if dead else (120, 225, 120), SW // 2, 34, 'c')
        draw_text(s, "مستني زمايلك يوصلوا للشقة الجاية..." if dead else "مستني الباقي يخلّصوا...", 20, (210, 200, 190), SW // 2, 68, 'c')
        p = self.peers.get(self.spec_pid)
        if p:
            draw_text(s, S("بتتفرّج على: {n}", n=p['name']), 24, PCOL[p['slot'] % len(PCOL)], SW // 2, 108, 'c')
            if len(self.spec_targets()) > 1:
                draw_text(s, "المس زر التفاعل لتبديل اللاعب" if TOUCH else "← → أو E: تبديل اللاعب", 17, (150, 150, 150), SW // 2, 140, 'c')
        else:
            draw_text(s, "مفيش حد حي تتفرّج عليه دلوقتي.", 22, (170, 170, 170), SW // 2, 108, 'c')
        if dead and self.died_t < 3.2:                                # كلمة "مُتّ" بتختفي ببطء
            t = txt("مُتّ", 110, (200, 10, 10))
            t.set_alpha(int(255 * max(0.0, 1 - max(0.0, self.died_t - 1.6) / 1.6)))
            s.blit(t, (SW // 2 - t.get_width() // 2, SH // 2 - 60))
            why = {'fear': "الخوف ملا قلبك...", 'ghost': "الوحش مسكك!"}.get(self.me_why)
            if why:
                draw_text(s, why, 28, (220, 170, 170), SW // 2, SH // 2 + 70, 'c')
        if self.wipe_t > 0:
            ov = pygame.Surface((SW, 70), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 190))
            s.blit(ov, (0, SH // 2 + 90))
            draw_text(s, "كلكم متّم... الشقة هتتعاد!", 36, (230, 60, 60), SW // 2, SH // 2 + 104, 'c')
        self.btns = []

    def draw_online(self, s):
        s.fill((0, 0, 0))
        self.btns = []
        {'menu': self.draw_on_menu, 'join': self.draw_on_join, 'lobby': self.draw_on_lobby}[self.on_view](s)
        A['vig'].set_alpha(110)
        s.blit(A['vig'], (0, 0))

    def draw_on_menu(self, s):
        fl = 150 + int(80 * abs(math.sin(self.t * 3))) if random.random() > 0.05 else 60
        draw_text(s, "اللعب أونلاين", 64, (fl, 20, 20), SW // 2, 40, 'c')
        draw_text(s, "لحد 8 لاعبين على نفس الشبكة (LAN)", 26, (220, 205, 190), SW // 2, 130, 'c')
        draw_text(s, S("اسمك: {n}", n=self.name()), 24, (240, 200, 100), SW // 2, 172, 'c')
        self.sel = min(self.sel, 2)
        for i, (a, label) in enumerate([('create', "إنشاء غرفة"), ('joinview', "الانضمام لغرفة"), ('onback', "رجوع")]):
            r = pygame.Rect(SW // 2 - 215, 225 + i * 80, 430, 66 if TOUCH else 58)
            self.draw_button(s, label, r, i == self.sel, 26)
            self.btns.append((r, a))
        if self.net_msg:
            draw_text(s, self.net_msg, 22, (230, 90, 90), SW // 2, 482, 'c')
        draw_text(s, "كل اللاعبين لازم يكونوا على نفس الواي فاي أو الشبكة.", 20, (150, 150, 150), SW // 2, 538, 'c')
        draw_text(s, "في الأونلاين: لو الخوف اتملى أو وحش لمسك... بتموت!", 20, (200, 120, 120), SW // 2, 572, 'c')

    def draw_on_join(self, s):
        rtl = LANG == 'ar'
        r = pygame.Rect(10, 8, 120, 42)
        self.draw_button(s, "رجوع", r, False, 22)
        self.btns.append((r, 'onback'))
        draw_text(s, "الانضمام لغرفة", 34, (240, 200, 100), SW // 2, 10, 'c')
        w = 590
        x0 = 60 if TOUCH else (SW - 640) // 2
        box = pygame.Rect(x0, 70, w - 200, 56)
        pygame.draw.rect(s, (24, 20, 22), box, border_radius=8)
        pygame.draw.rect(s, (220, 170, 80), box, 2, border_radius=8)
        cur = "|" if int(self.t * 2) % 2 == 0 else " "
        if self.join_id:
            draw_text(s, self.join_id + cur, 30, (255, 255, 255), box.x + 14, box.y + 8, 'l')
        else:
            draw_text(s, "رقم الغرفة أو IP المضيف", 20, (110, 105, 100), box.x + 14, box.y + 16, 'l')
        jr = pygame.Rect(x0 + w - 190, 70, 190, 56)
        self.draw_button(s, "انضم", jr, True, 26)
        self.btns.append((jr, 'joingo'))
        draw_text(s, "الغرف المتاحة على الشبكة:", 20, (200, 190, 180), x0 + w if rtl else x0, 140, 'r' if rtl else 'l')
        rooms = self.scan.listing() if self.scan else []
        for i, (rid, info) in enumerate(rooms[:5]):
            rr = pygame.Rect(x0, 172 + i * 62, w, 54)
            open_ = info['st'] == 'lobby' and info['n'] < info['max']
            label = S("{r}   |   {h}   |   {n}/{m}", r=rid, h=info['host'], n=info['n'], m=info['max'])
            if info['st'] != 'lobby':
                label = S("{r}   |   {h}   |   (اللعبة بدأت)", r=rid, h=info['host'])
            self.draw_button(s, label, rr, self.join_id == rid, 22 if open_ else 20)
            if open_:
                self.btns.append((rr, 'room:' + rid))
        if not rooms:
            draw_text(s, "بدوّر على غرف على الشبكة...", 22, (170, 170, 170), x0 + w // 2, 200, 'c')
            draw_text(s, "لو مفيش حاجة بتظهر: اتأكد إن المضيف فتح غرفة وإنكم على نفس الشبكة.", 18, (130, 130, 130), x0 + w // 2, 236, 'c')
        if self.net_msg:
            busy = bool(self.net or self.join_wait)
            draw_text(s, self.net_msg, 22, (240, 200, 120) if busy else (230, 90, 90), x0 + w // 2, 498, 'c')
        if TOUCH:                                                     # كيبورد أرقام على الشاشة
            kw, kh, gp = 90, 64, 8
            kx = SW - 3 * kw - 2 * gp - 20
            keys = [('j:1', '1'), ('j:2', '2'), ('j:3', '3'), ('j:4', '4'), ('j:5', '5'), ('j:6', '6'),
                    ('j:7', '7'), ('j:8', '8'), ('j:9', '9'), ('j:.', '.'), ('j:0', '0'), ('jbk', "مسح")]
            for n, (a, lab) in enumerate(keys):
                rc = pygame.Rect(kx + (n % 3) * (kw + gp), 150 + (n // 3) * (kh + gp), kw, kh)
                self.draw_button(s, lab, rc, False, 28)
                self.btns.append((rc, a))
        else:
            draw_text(s, "اكتب رقم الغرفة واضغط Enter... أو اختار غرفة من القايمة.", 20, (150, 150, 150), SW // 2, SH - 62, 'c')
            draw_text(s, "لو الغرفة مش بتظهر: اكتب IP جهاز المضيف (زي 192.168.1.5).", 18, (120, 120, 120), SW // 2, SH - 34, 'c')

    def draw_on_lobby(self, s):
        draw_text(s, "رقم الغرفة", 26, (220, 205, 190), SW // 2, 18, 'c')
        draw_text(s, self.room_id or "......", 84, (230, 60, 50), SW // 2, 48, 'c')
        draw_text(s, S("عنوان المضيف: {ip}", ip=self.room_ip), 20, (150, 150, 150), SW // 2, 150, 'c')
        draw_text(s, "ابعت الرقم ده لأصحابك علشان ينضموا.", 22, (210, 200, 190), SW // 2, 178, 'c')
        pl = sorted(self.peers.values(), key=lambda q: q['slot'])
        draw_text(s, S("اللاعبين: {n} / {m}", n=len(pl), m=netplay.MAX_PLAYERS), 24, (240, 200, 100), SW // 2, 214, 'c')
        for i in range(netplay.MAX_PLAYERS):
            rc = pygame.Rect(SW // 2 - 310 + (i // 4) * 320, 252 + (i % 4) * 46, 300, 40)
            pygame.draw.rect(s, (24, 20, 22), rc, border_radius=6)
            pygame.draw.rect(s, (110, 90, 70), rc, 1, border_radius=6)
            if i < len(pl):
                p = pl[i]
                pygame.draw.rect(s, PCOL[p['slot'] % len(PCOL)], (rc.right - 28, rc.y + 11, 18, 18))
                nm = S("{n}  (المضيف)", n=p['name']) if p.get('host') else p['name']
                draw_text(s, nm, 22, (240, 235, 225), rc.right - 40, rc.y + 5, 'r')
            else:
                draw_text(s, "...", 22, (80, 76, 72), rc.right - 40, rc.y + 5, 'r')
        bh = 62 if TOUCH else 56
        if self.is_host:
            r = pygame.Rect(SW // 2 - 215, 446, 430, bh)
            self.draw_button(s, "ابدأ اللعبة", r, self.sel == 0, 26)
            self.btns.append((r, 'lobby_start'))
        else:
            draw_text(s, "مستني المضيف يبدأ اللعبة...", 26, (200, 190, 180), SW // 2, 462, 'c')
        r = pygame.Rect(SW // 2 - 215, 446 + bh + 12, 430, 52)
        self.draw_button(s, "خروج من الغرفة", r, (self.sel == 1) if self.is_host else True, 24)
        self.btns.append((r, 'leave'))

    def title_opts(self):
        o = []
        if self.profile and self.saved:
            o.append(('continue', S("كمّل اللعبة: {p} - الشقة {l}", p=self.profile['name'], l=self.saved['level'])))
        o += [('new', "لعبة جديدة"), ('online', "اللعب أونلاين"), ('quit', "خروج")]
        return o

    def draw_title(self, s):
        s.fill((0, 0, 0))
        self.btns = []
        if self.state == 'title':
            self.draw_menu(s)
        elif TOUCH:
            self.draw_profile_touch(s)
        else:
            self.draw_profile(s)
        A['vig'].set_alpha(90 if self.state == 'title' else 140)
        s.blit(A['vig'], (0, 0))

    def draw_menu(self, s):
        logo = title_logo()
        logo.set_alpha(235 if random.random() > 0.04 else 110)             # وميض خفيف
        s.blit(logo, (28, (SH - logo.get_height()) // 2))
        cx = 705
        draw_text(s, "10 شقق... كل واحدة أكبر وأخطر.", 24, (210, 200, 190), cx, 62, 'c')
        draw_text(s, "دوّر على المفتاح واهرب.", 24, (210, 200, 190), cx, 96, 'c')
        draw_text(s, "مفيش موت في اللعب الفردي... بس خضّات كتير!", 21, (200, 120, 120), cx, 134, 'c')
        opts = self.title_opts()
        self.sel = min(self.sel, len(opts) - 1)
        bh, gap = (62, 76) if TOUCH else (52, 66)
        for i, (a, label) in enumerate(opts):
            r = pygame.Rect(cx - 215, 195 + i * gap, 430, bh)
            self.draw_button(s, label, r, i == self.sel, 24)
            self.btns.append((r, a))
        r = pygame.Rect(SW - 196, 10, 180, 48 if TOUCH else 40)
        self.draw_button(s, "English" if LANG == 'ar' else "العربية", r, False, 22)
        self.btns.append((r, 'lang'))
        if TOUCH:
            tips = ["الجويستيك: حركة - اسحبه بعيد للجري", "زر تفاعل: فتح وتقليب   |   زر كشاف: نور"]
        else:
            tips = ["WASD / الأسهم: حركة   |   Shift: جري", "E: تفاعل   |   F: كشاف   |   Tab: خريطة",
                    "L: اللغة   |   M: كتم الصوت   |   F11: ملء الشاشة"]
        tips += ["الكشاف بيخلّي الشبح يتراجع، والشموع بتهدّي خوفك.", "حاجة بتتحرك لما تدير ضهرك؟ بصّلها بالكشاف."]
        ty0 = 195 + (len(opts) - 1) * gap + bh + 16
        for i, ln in enumerate(tips):
            draw_text(s, ln, 18, (150, 150, 150), cx, ty0 + i * 25, 'c')

    def draw_profile(self, s):
        fl = 150 + int(80 * abs(math.sin(self.t * 3))) if random.random() > 0.05 else 60
        draw_text(s, "بيت الهمس", 72, (fl, 20, 20), SW // 2, 50, 'c')
        draw_text(s, "عرّفنا بنفسك...", 34, (240, 200, 100), SW // 2, 140, 'c')
        labels = [('name', "الاسم"), ('day', "يوم الميلاد من 1 إلى 31"), ('month', "شهر الميلاد من 1 إلى 12")]
        rtl = LANG == 'ar'
        for i, (key, lab) in enumerate(labels):
            y = 230 + i * 80
            if rtl:
                draw_text(s, lab, 26, (230, 230, 220), SW // 2 + 300, y, 'r')
                box = pygame.Rect(SW // 2 - 300, y - 8, 360, 48)
            else:
                draw_text(s, lab, 26, (230, 230, 220), SW // 2 - 300, y, 'l')
                box = pygame.Rect(SW // 2 - 40, y - 8, 360, 48)
            pygame.draw.rect(s, (24, 20, 22), box, border_radius=6)
            pygame.draw.rect(s, (220, 170, 80) if i == self.field else (100, 90, 80), box, 2, border_radius=6)
            cur = "|" if (i == self.field and int(self.t * 2) % 2 == 0) else " "
            val = self.form[key]
            if val or i == self.field:
                if rtl:
                    draw_text(s, val + cur, 28, (255, 255, 255), box.right - 12, box.y + 6, 'r')
                else:
                    draw_text(s, val + cur, 28, (255, 255, 255), box.x + 12, box.y + 6, 'l')
            self.btns.append((box, 'field%d' % i))
        if self.form_err:
            draw_text(s, self.form_err, 22, (230, 80, 80), SW // 2, 470, 'c')
        r = pygame.Rect(SW // 2 - 150, 520, 300, 54)
        self.draw_button(s, "ابدأ - Enter", r, True)
        self.btns.append((r, 'submit'))
        draw_text(s, "Tab: الحقل اللي بعده   |   Esc: رجوع", 18, (140, 140, 140), SW // 2, 595, 'c')

    def draw_profile_touch(self, s):
        """شاشة التسجيل على الموبايل: كيبورد على الشاشة (من غير كيبورد النظام)"""
        rtl = LANG == 'ar'
        draw_text(s, "عرّفنا بنفسك...", 28, (240, 200, 100), SW // 2, 6, 'c')
        r = pygame.Rect(10, 8, 120, 42)
        self.draw_button(s, "رجوع", r, False, 22)
        self.btns.append((r, 'back'))
        spec = [(0, 'name', "الاسم", 330), (1, 'day', "يوم الميلاد", 190), (2, 'month', "شهر الميلاد", 190)]
        total = sum(w for _i, _k, _l, w in spec) + 40
        order = list(reversed(spec)) if rtl else spec
        x = (SW - total) // 2
        for i, key, lab, w in order:
            draw_text(s, lab, 17, (200, 200, 190), x + (w if rtl else 0), 54, 'r' if rtl else 'l')
            box = pygame.Rect(x, 78, w, 50)
            on = i == self.field
            pygame.draw.rect(s, (24, 20, 22), box, border_radius=8)
            pygame.draw.rect(s, (220, 170, 80) if on else (100, 90, 80), box, 2, border_radius=8)
            val = self.form[key] + ("|" if (on and int(self.t * 2) % 2 == 0) else " ")
            if self.form[key] or on:
                if rtl:
                    draw_text(s, val, 28, (255, 255, 255), box.right - 10, box.y + 6, 'r')
                else:
                    draw_text(s, val, 28, (255, 255, 255), box.x + 10, box.y + 6, 'l')
            self.btns.append((box, 'field%d' % i))
            x += w + 20
        if self.form_err:
            draw_text(s, self.form_err, 19, (230, 80, 80), SW // 2, 136, 'c')
        nxt = "التالي" if self.field < 2 else "ابدأ"
        top = 168
        if self.field == 0:
            rows = AR_ROWS if self.kb_lang == 'ar' else EN_ROWS
            kw, kh, gp = 70, 74, 8
            y = top
            for row in rows:
                x0 = (SW - (len(row) * kw + (len(row) - 1) * gp)) // 2
                for j, ch in enumerate(row):
                    rc = pygame.Rect(x0 + j * (kw + gp), y, kw, kh)
                    self.draw_button(s, ch, rc, False, 28)
                    self.btns.append((rc, 'k:' + ch))
                y += kh + gp
            bar = [('kbmode', "ABC" if self.kb_lang == 'ar' else "أب", 120), ('k: ', "مسافة", 330),
                   ('bksp', "مسح", 140), ('next', nxt, 200)]
            x0 = (SW - (sum(w for _a, _l, w in bar) + gp * (len(bar) - 1))) // 2
            for a, lab, w in bar:
                rc = pygame.Rect(x0, y + 6, w, kh)
                self.draw_button(s, lab, rc, a == 'next', 24)
                self.btns.append((rc, a))
                x0 += w + gp
        else:
            kw, kh, gp = 140, 78, 8
            x0 = (SW - (3 * kw + 2 * gp)) // 2
            keys = [('k:1', '1'), ('k:2', '2'), ('k:3', '3'), ('k:4', '4'), ('k:5', '5'), ('k:6', '6'),
                    ('k:7', '7'), ('k:8', '8'), ('k:9', '9'), ('bksp', "مسح"), ('k:0', '0'), ('next', nxt)]
            for n, (a, lab) in enumerate(keys):
                rc = pygame.Rect(x0 + (n % 3) * (kw + gp), top + (n // 3) * (kh + gp), kw, kh)
                self.draw_button(s, lab, rc, a == 'next', 28)
                self.btns.append((rc, a))

    def draw_trans(self, s):
        s.fill((0, 0, 0))
        a = min(1.0, self.trans_t / 0.8, (3.4 - self.trans_t) / 0.6)
        col = lambda c: tuple(int(v * max(0, a)) for v in c)
        n = self.next_n
        cells = DIMS[n][0] * DIMS[n][1]
        draw_text(s, S("الشقة {n}", n=n), 80, col((200, 30, 30)), SW // 2 + random.randint(-2, 2), 190, 'c')
        draw_text(s, "المفتاح فتح الباب... وقدامك شقة تانية.", 28, col((210, 200, 190)), SW // 2, 320, 'c')
        draw_text(s, S("عدد الأوض: {n}", n=cells), 28, col((240, 200, 100)), SW // 2, 370, 'c')
        if n >= 6:
            draw_text(s, "الأشباح هنا أكتر... خلّي بالك.", 24, col((200, 90, 90)), SW // 2, 430, 'c')
        elif n >= 3:
            draw_text(s, "الشقة دي أصعب... والخضّات أكتر.", 24, col((200, 90, 90)), SW // 2, 430, 'c')

    def pause_opts(self):
        if self.net:                                   # أونلاين: مفيش حفظ، والخروج بيسيب الغرفة
            return [('resume', "كمّل"), ('lang', "English" if LANG == 'ar' else "العربية"),
                    ('menu', "خروج من الغرفة"), ('quit', "خروج")]
        return [('resume', "كمّل"), ('save', "حفظ اللعبة"), ('lang', "English" if LANG == 'ar' else "العربية"),
                ('menu', "القايمة الرئيسية"), ('quit', "خروج")]

    def draw_pause(self, s):
        ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        s.blit(ov, (0, 0))
        draw_text(s, "قايمة اللعبة", 44, (240, 200, 100), SW // 2, 130, 'c')
        self.btns = []
        for i, (a, label) in enumerate(self.pause_opts()):
            r = pygame.Rect(SW // 2 - 200, 190 + i * 66, 400, 52)
            self.draw_button(s, label, r, i == self.sel)
            self.btns.append((r, a))
        if self.toast_t > 0:
            draw_text(s, self.toast_s, 24, (255, 235, 200), SW // 2, 520, 'c')

    def draw_win(self, s):
        self.win_t += 1 / 60
        ov = pygame.Surface((SW, SH))
        ov.fill((245, 245, 235))
        ov.set_alpha(min(255, int(self.win_t / 3 * 255)))
        s.blit(ov, (0, 0))
        if self.win_t > 2.5:
            draw_text(s, "هربت!", 80, (40, 90, 40), SW // 2, 130, 'c')
            draw_text(s, S("برافو يا {n}... عديت الشقق العشرة!", n=self.name()), 32, (50, 50, 50), SW // 2, 270, 'c')
            draw_text(s, "طلع عليك نور الفجر... والبيوت ورا ضهرك ساكتة.", 26, (50, 50, 50), SW // 2, 330, 'c')
            draw_text(s, S("بس سمعت همس بيقول: \"{n}... استنّى\"", n=self.name()), 26, (130, 40, 40), SW // 2, 380, 'c')
            draw_text(s, "المس الشاشة للرجوع للقايمة" if TOUCH else "Enter: القايمة الرئيسية      Esc: خروج", 26, (60, 60, 60), SW // 2, 500, 'c')

    # ------------------------------------------------ أحداث
    def form_input(self, text):
        key = ('name', 'day', 'month')[self.field]
        if key != 'name':
            text = text.translate({0x660 + i: ord('0') + i for i in range(10)})
            text = ''.join(c for c in text if c.isdigit())
        else:
            text = ''.join(c for c in text if c.isprintable())
        lim = 14 if key == 'name' else 2
        self.form[key] = (self.form[key] + text)[:lim]
        self.form_err = ""

    def form_next(self):
        if self.field < 2 and self.form[('name', 'day', 'month')[self.field]]:
            self.field += 1
        else:
            self.submit_form()

    def on_background(self):
        """التطبيق راح للخلفية: بنوقّف اللعبة ونحفظ"""
        if self.state == 'play' and self.js_t <= 0:
            self.state, self.sel = 'pause', 0
        try:
            if self.profile:
                self.save(silent=True)
        except Exception:
            pass

    def submit_form(self):
        n = self.form['name'].strip()
        try:
            d, m = int(self.form['day']), int(self.form['month'])
        except ValueError:
            d = m = 0
        if not n:
            self.form_err, self.field = "اكتب اسمك الأول!", 0
            return
        if not (1 <= d <= 31 and 1 <= m <= 12):
            self.form_err = "تاريخ الميلاد مش صح: اليوم من 1 إلى 31 والشهر من 1 إلى 12"
            return
        self.profile = dict(name=n, day=d, month=m, seed=random.randint(1, 10 ** 6))
        self.saved = None
        prepare_voice_async(n)
        pygame.key.stop_text_input()
        pygame.key.set_repeat()
        if self.pending_online:                        # جاي من "اللعب أونلاين": الاسم بس، من غير لعبة فردية
            self.pending_online = False
            write_save(dict(profile=self.profile))
            self.state, self.on_view, self.net_msg, self.sel = 'online', 'menu', "", 0
            return
        self.new_session()
        self.state = 'play'
        self.save(silent=True)
        self.maybe_birthday()

    def do_action(self, a):
        if a == 'quit':
            return False
        if a == 'continue':
            if 'voice' not in SND:
                prepare_voice_async(self.name())
            self.load_game()
            self.state = 'play'
            self.maybe_birthday()
        elif a == 'new':
            self.pending_online = False
            self.state, self.field, self.form_err = 'profile', 0, ""
            self.form = {'name': '', 'day': '', 'month': ''}
            self.kb_lang = LANG
            if not TOUCH:
                pygame.key.start_text_input()
                pygame.key.set_repeat(400, 40)
        elif a == 'lang':
            set_lang('en' if LANG == 'ar' else 'ar')
            pygame.display.set_caption("Whispering House" if LANG == 'en' else "بيت الهمس")
        elif a == 'resume':
            self.state = 'play'
        elif a == 'save':
            self.save()
            if self.state == 'pause':
                self.toast_t = max(self.toast_t, 2.0)
        elif a == 'online':
            self.open_online()
        elif a == 'create':
            self.create_room()
        elif a == 'joinview':
            self.open_join()
        elif a == 'joingo':
            self.join_go()
        elif a.startswith('room:'):
            r = self.scan.rooms.get(a[5:]) if self.scan else None
            if r and not self.net:
                self.join_id = a[5:]
                self.connect_to(r['ip'], r['port'])
        elif a.startswith('j:'):
            self.join_type(a[2:])
        elif a == 'jbk':
            self.join_id = self.join_id[:-1]
        elif a == 'lobby_start':
            if self.is_host and self.net:
                self.net.send({'t': 'start'})
        elif a in ('onback', 'leave'):
            if self.on_view == 'join' or self.on_view == 'lobby':
                self.leave_online()
                self.on_view, self.net_msg, self.sel = 'menu', "", 0
            else:
                self.state, self.sel = 'title', 0
        elif a == 'menu':
            self.leave_online()
            self.saved = (load_save() or {}).get('game')
            self.state, self.sel = 'title', 0
        elif a == 'submit':
            self.submit_form()
        elif a == 'back':
            pygame.key.stop_text_input()
            pygame.key.set_repeat()
            self.state = 'title'
        elif a.startswith('k:'):
            self.form_input(a[2:])
        elif a == 'bksp':
            key = ('name', 'day', 'month')[self.field]
            self.form[key] = self.form[key][:-1]
        elif a == 'kbmode':
            self.kb_lang = 'en' if self.kb_lang == 'ar' else 'ar'
        elif a == 'next':
            self.form_next()
        elif a.startswith('field'):
            self.field = int(a[5:])
        return True

    def handle(self, e):
        st = self.state
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self.js_t <= 0 and not self.dlg:
            for r, a in self.btns:
                if r.collidepoint(e.pos):
                    return self.do_action(a)
        elif e.type == pygame.MOUSEMOTION and st in ('title', 'pause', 'online'):
            for i, (r, _a) in enumerate(self.btns):
                if r.collidepoint(e.pos):
                    self.sel = i
        elif e.type == pygame.TEXTINPUT and st == 'profile':
            self.form_input(e.text)
        elif e.type == pygame.TEXTINPUT and st == 'online' and self.on_view == 'join':
            self.join_type(e.text)
        elif e.type == pygame.KEYDOWN:
            k = e.key
            if st == 'title':
                n = len(self.title_opts())
                if k == pygame.K_UP:
                    self.sel = (self.sel - 1) % n
                elif k == pygame.K_DOWN:
                    self.sel = (self.sel + 1) % n
                elif k in (pygame.K_RETURN, pygame.K_SPACE) and self.btns:
                    return self.do_action(self.btns[self.sel][1])
                elif k == pygame.K_ESCAPE:
                    return False
            elif st == 'profile':
                if k == pygame.K_ESCAPE:
                    pygame.key.stop_text_input()
                    pygame.key.set_repeat()
                    self.state = 'title'
                elif k in (pygame.K_TAB, pygame.K_DOWN):
                    self.field = (self.field + 1) % 3
                elif k == pygame.K_UP:
                    self.field = (self.field - 1) % 3
                elif k == pygame.K_BACKSPACE:
                    key = ('name', 'day', 'month')[self.field]
                    self.form[key] = self.form[key][:-1]
                elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if self.field < 2 and self.form[('name', 'day', 'month')[self.field]]:
                        self.field += 1
                    else:
                        self.submit_form()
            elif st == 'online':
                v = self.on_view
                if k == pygame.K_ESCAPE:
                    return self.do_action('onback')
                if v == 'menu':
                    n = max(1, len(self.btns))
                    if k == pygame.K_UP:
                        self.sel = (self.sel - 1) % n
                    elif k == pygame.K_DOWN:
                        self.sel = (self.sel + 1) % n
                    elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and self.btns:
                        return self.do_action(self.btns[self.sel][1])
                elif v == 'join':
                    if k == pygame.K_BACKSPACE:
                        self.join_id = self.join_id[:-1]
                    elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        self.join_go()
                elif v == 'lobby':
                    if k in (pygame.K_UP, pygame.K_DOWN) and self.is_host:
                        self.sel = 1 - min(self.sel, 1)
                    elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                        return self.do_action('lobby_start' if (self.is_host and self.sel == 0) else 'leave')
            elif st == 'play' and self.js_t <= 0 and self.spectating():
                if k == pygame.K_ESCAPE:
                    self.state, self.sel = 'pause', 0
                elif k in (pygame.K_e, pygame.K_SPACE, pygame.K_RETURN, pygame.K_RIGHT, pygame.K_d):
                    self.spec_cycle(1)
                elif k in (pygame.K_LEFT, pygame.K_a):
                    self.spec_cycle(-1)
            elif st == 'play' and self.js_t <= 0:
                if k == pygame.K_ESCAPE:
                    if self.dlg:
                        self.close_dialog()
                    else:
                        self.state, self.sel = 'pause', 0
                elif k in (pygame.K_e, pygame.K_SPACE, pygame.K_RETURN):
                    if self.dlg:
                        self.close_dialog()
                    else:
                        self.interact()
                elif k == pygame.K_f and not self.dlg:
                    self.flash = not self.flash
                elif k == pygame.K_k:
                    self.save()
                elif k == pygame.K_TAB:
                    self.show_map = not self.show_map
            elif st == 'pause':
                if k == pygame.K_ESCAPE:
                    self.state = 'play'
                elif k == pygame.K_UP:
                    self.sel = (self.sel - 1) % len(self.pause_opts())
                elif k == pygame.K_DOWN:
                    self.sel = (self.sel + 1) % len(self.pause_opts())
                elif k in (pygame.K_RETURN, pygame.K_SPACE):
                    return self.do_action(self.btns[self.sel][1])
            elif st == 'win':
                if k == pygame.K_ESCAPE:
                    return False
                if k == pygame.K_RETURN and self.win_t > 2.5:
                    self.leave_online()
                    self.saved = None
                    self.state, self.sel = 'title', 0
        return True


# ================================================================= الشاشة واللمس
REAL_GEO = dict(ox=0, oy=0, sc=1.0)
_TLOGO = {}
_pres = {}


def title_logo():
    if 'img' not in _TLOGO:
        img = pygame.image.load(asset("logo.png")).convert()
        h = SH - 16
        _TLOGO['img'] = pygame.transform.smoothscale(img, (int(img.get_width() * h / img.get_height()), h))
    return _TLOGO['img']


def show_splash(screen, msg=""):
    """شاشة تحميل باللوجو"""
    try:
        img = title_logo()
        screen.fill((0, 0, 0))
        screen.blit(img, ((SW - img.get_width()) // 2, 8))
        if msg:
            pygame.draw.rect(screen, (0, 0, 0), (0, SH - 60, SW, 60))
            draw_text(screen, msg, 22, (200, 190, 180), SW // 2, SH - 44, 'c')
        present(screen)
        pygame.event.pump()
    except Exception:
        pass


def present(canvas, touch=None, game=None):
    """على الموبايل: بنكبّر الصورة على الشاشة الحقيقية (بنفس النسبة) وبنرسم أزرار اللمس فوقها"""
    real = pygame.display.get_surface()
    if not TOUCH or real is None or real is canvas:
        pygame.display.flip()
        return
    rw, rh = real.get_size()
    key = (rw, rh, id(real))
    if _pres.get('key') != key:
        sc = min(rw / SW, rh / SH)
        dw, dh = max(1, int(SW * sc)), max(1, int(SH * sc))
        ox, oy = (rw - dw) // 2, (rh - dh) // 2
        real.fill((0, 0, 0))
        _pres.update(key=key, size=(dw, dh), sub=real.subsurface((ox, oy, dw, dh)))
        REAL_GEO.update(ox=ox, oy=oy, sc=sc)
    ox, oy = REAL_GEO['ox'], REAL_GEO['oy']
    if ox:
        real.fill((0, 0, 0), (0, 0, ox, rh))
        real.fill((0, 0, 0), (rw - ox, 0, ox, rh))
    if oy:
        real.fill((0, 0, 0), (0, 0, rw, oy))
        real.fill((0, 0, 0), (0, rh - oy, rw, oy))
    try:
        if ANDROID:
            pygame.transform.scale(canvas, _pres['size'], _pres['sub'])
        else:
            pygame.transform.smoothscale(canvas, _pres['size'], _pres['sub'])
    except Exception:
        real.blit(pygame.transform.scale(canvas, _pres['size']), (ox, oy))
    if touch is not None:
        touch.draw(real, game)
    pygame.display.flip()


class Touch:
    """زراير اللمس: جويستيك (بيظهر مكان إصبعك في الشمال) + تفاعل + كشاف + خريطة + قايمة"""
    DEAD = 0.2
    KEYS = {'E': (pygame.K_e, 'e'), 'F': (pygame.K_f, 'f'), 'MAP': (pygame.K_TAB, ''), 'PAUSE': (pygame.K_ESCAPE, '')}
    LABELS = {'E': "تفاعل", 'F': "كشاف", 'MAP': "خريطة", 'PAUSE': None}

    def __init__(self):
        self.stick = None            # dict(id, ox, oy, x, y)
        self.held = {}               # إصبع -> زر
        self.finger_seen = False
        self._spr = {}

    # ---------------- أماكن الأزرار (بالبكسل الحقيقي للشاشة)
    def geo(self, rw, rh):
        u = rh / 640.0
        ox, oy, sc = REAL_GEO['ox'], REAL_GEO['oy'], REAL_GEO['sc']
        return {'E': ((rw - 135 * u, rh - 140 * u), 66 * u),
                'F': ((rw - 275 * u, rh - 92 * u), 48 * u),
                'MAP': ((ox + (SW - 112) * sc, oy + 39 * sc), 27 * sc),
                'PAUSE': ((ox + (SW - 44) * sc, oy + 39 * sc), 27 * sc)}

    def active(self, game):
        return game.state == 'play' and not game.dlg and game.js_t <= 0 and not game.show_map

    def to_logical(self, x, y):
        sc = REAL_GEO['sc'] or 1.0
        return (x - REAL_GEO['ox']) / sc, (y - REAL_GEO['oy']) / sc

    def hit(self, x, y, rw, rh):
        for role, ((cx, cy), r) in self.geo(rw, rh).items():
            if math.hypot(x - cx, y - cy) <= r * 1.25:
                return role
        return None

    def key(self, game, k, ch=''):
        return game.handle(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode=ch, scancode=0))

    # ---------------- الأحداث: بيرجّع (اتصرّف فيه؟، اللعبة شغّالة؟)
    def handle_event(self, e, game):
        t = e.type
        real = pygame.display.get_surface()
        rw, rh = real.get_size()
        if t in (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION):
            self.finger_seen = True
            x, y, fid = e.x * rw, e.y * rh, ('f', e.finger_id)
            kind = {pygame.FINGERDOWN: 'down', pygame.FINGERUP: 'up', pygame.FINGERMOTION: 'move'}[t]
        elif t == pygame.MOUSEBUTTONDOWN and e.button == 1:
            x, y, fid, kind = e.pos[0], e.pos[1], ('m',), 'down'
        elif t == pygame.MOUSEBUTTONUP and e.button == 1:
            x, y, fid, kind = e.pos[0], e.pos[1], ('m',), 'up'
        elif t == pygame.MOUSEMOTION and e.buttons[0]:
            x, y, fid, kind = e.pos[0], e.pos[1], ('m',), 'move'
        else:
            return False, True
        if fid == ('m',) and self.finger_seen:                # الماوس هنا مجرد نسخة مكرّرة من اللمس
            return True, True
        if kind == 'down':
            return True, self.down(fid, x, y, game, rw, rh)
        if kind == 'move':
            self.move(fid, x, y, rh, game)
        else:
            self.up(fid, game)
        return True, True

    def down(self, fid, x, y, game, rw, rh):
        st = game.state
        if self.active(game):
            role = self.hit(x, y, rw, rh)
            if role:
                self.held[fid] = role
                return self.key(game, *self.KEYS[role])
            if x < rw * 0.5 and self.stick is None:               # جويستيك عايم: بيظهر مكان إصبعك
                self.stick = dict(id=fid, ox=x, oy=y, x=x, y=y)
                return True
        lx, ly = self.to_logical(x, y)
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(int(lx), int(ly)), button=1)
        if st == 'play':
            if game.js_t > 0:
                return True
            if game.dlg:
                return self.key(game, pygame.K_e, 'e')            # أي لمسة = كمّل الكلام
            if game.show_map:
                return self.key(game, pygame.K_TAB)
            return game.handle(click)                             # زرار الحفظ في الـ HUD
        if st == 'win':
            return self.key(game, pygame.K_RETURN)
        if st in ('title', 'pause', 'profile', 'online'):
            return game.handle(click)
        return True

    def move(self, fid, x, y, rh, game):
        st = self.stick
        if not st or st['id'] != fid:
            return
        st['x'], st['y'] = x, y
        R = 92 * rh / 640.0
        dx, dy = x - st['ox'], y - st['oy']
        d = math.hypot(dx, dy)
        v = min(1.0, d / R)
        if v < self.DEAD:
            game.joy, game.joy_run = (0.0, 0.0), False
        else:
            game.joy, game.joy_run = (dx / d, dy / d), d > R * 1.2    # اسحب بره الدايرة = جري

    def up(self, fid, game):
        self.held.pop(fid, None)
        if self.stick and self.stick['id'] == fid:
            self.stick = None
            game.joy, game.joy_run = (0.0, 0.0), False

    # ---------------- الرسم
    def sprite(self, role, r, state):
        k = (role, int(r), state, LANG)
        sp = self._spr.get(k)
        if sp is None:
            R = int(r)
            d = 2 * R + 6
            sp = pygame.Surface((d, d), pygame.SRCALPHA)
            fill = {'n': (18, 8, 8, 140), 'h': (96, 24, 22, 190), 'p': (160, 48, 36, 220)}[state]
            edge = (150, 110, 70, 200) if state == 'n' else (235, 185, 100, 240)
            pygame.draw.circle(sp, fill, (R + 3, R + 3), R)
            pygame.draw.circle(sp, edge, (R + 3, R + 3), R, max(2, R // 16))
            if role == 'PAUSE':
                bw, bh = max(4, R // 5), max(10, R // 2)
                for dx in (-bw, bw):
                    pygame.draw.rect(sp, (255, 240, 215, 240), (R + 3 + dx - bw // 2, R + 3 - bh // 2, bw, bh), border_radius=2)
            else:
                t = txt(self.LABELS[role], max(12, int(R * 0.44)), (255, 240, 215))
                sp.blit(t, ((d - t.get_width()) // 2, (d - t.get_height()) // 2))
            self._spr[k] = sp
        return sp

    def ring(self, r, kind):
        k = ('ring', int(r), kind)
        sp = self._spr.get(k)
        if sp is None:
            R = int(r)
            d = 2 * R + 6
            sp = pygame.Surface((d, d), pygame.SRCALPHA)
            if kind == 'base':
                pygame.draw.circle(sp, (255, 255, 255, 22), (R + 3, R + 3), R)
                pygame.draw.circle(sp, (255, 255, 255, 80), (R + 3, R + 3), R, 3)
            elif kind == 'idle':
                pygame.draw.circle(sp, (255, 255, 255, 12), (R + 3, R + 3), R)
                pygame.draw.circle(sp, (255, 255, 255, 45), (R + 3, R + 3), R, 2)
            else:
                pygame.draw.circle(sp, (214, 150, 90, 130), (R + 3, R + 3), R)
                pygame.draw.circle(sp, (240, 200, 130, 200), (R + 3, R + 3), R, 3)
            self._spr[k] = sp
        return sp

    def draw(self, real, game):
        if game is None or not self.active(game):
            return
        rw, rh = real.get_size()
        u = rh / 640.0
        R = 92 * u
        if self.stick:
            st = self.stick
            real.blit(self.ring(R, 'base'), (st['ox'] - R - 3, st['oy'] - R - 3))
            dx, dy = st['x'] - st['ox'], st['y'] - st['oy']
            d = math.hypot(dx, dy)
            if d > R:
                dx, dy = dx / d * R, dy / d * R
            real.blit(self.ring(40 * u, 'knob'), (st['ox'] + dx - 40 * u - 3, st['oy'] + dy - 40 * u - 3))
        else:
            real.blit(self.ring(R, 'idle'), (150 * u - R - 3, rh - 150 * u - R - 3))
        near = game.nearest() is not None
        pressed = set(self.held.values())
        for role, ((cx, cy), r) in self.geo(rw, rh).items():
            if role in pressed:
                state = 'p'
            elif (role == 'E' and near) or (role == 'F' and game.flash and game.battery > 0):
                state = 'h'
            else:
                state = 'n'
            real.blit(self.sprite(role, r, state), (cx - r - 3, cy - r - 3))


# ================================================================= التشغيل
def setup():
    global SR, AUDIO, SND
    pygame.mixer.pre_init(44100, -16, 1, 1024 if ANDROID else 512)
    pygame.init()
    pygame.display.set_caption("Whispering House")
    try:
        pygame.display.set_icon(pygame.image.load(asset("icon_window.png")))      # أيقونة اللعبة
    except Exception:
        pass
    if TOUCH:
        try:
            pygame.display.set_mode((0, 0) if ANDROID else (1280, 576),
                                    pygame.FULLSCREEN if ANDROID else pygame.RESIZABLE)
        except Exception:
            pygame.display.set_mode((SW, SH))
        screen = pygame.Surface((SW, SH)).convert()                                  # اللعبة بترسم هنا وبعدين بتتكبّر
    else:
        try:
            screen = pygame.display.set_mode((SW, SH), pygame.FULLSCREEN | pygame.SCALED)   # ملء الشاشة
        except Exception:
            screen = pygame.display.set_mode((SW, SH))
    show_splash(screen)
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(44100, -16, 1, 1024 if ANDROID else 512)
        SR = pygame.mixer.get_init()[0]
        SND = load_or_build_sounds(lambda m: show_splash(screen, m))
        AUDIO = True
    except Exception as ex:
        print("الصوت مش شغال:", ex)
        AUDIO = False
    A['faces'] = [make_face(7, 0), make_face(21, 1), make_face(33, 2)]
    A['ghost'] = make_ghost()
    A['ghost_big'] = pygame.transform.smoothscale(A['ghost'], (250, 416))
    A['ghost_big_f'] = pygame.transform.flip(A['ghost_big'], True, False)
    A['vig'] = make_vignette()
    return screen


def main():
    load_settings()
    screen = setup()
    game = Game()
    touch = Touch() if TOUCH else None
    pygame.display.set_caption("Whispering House" if LANG == 'en' else "بيت الهمس")
    if game.profile:
        prepare_voice_async(game.name())
    clock = pygame.time.Clock()
    if AUDIO:
        SND['drone'].play(loops=-1)
        apply_volume()
    game.maybe_birthday()          # لو النهارده عيد ميلادك: الوحش بيستقبلك أول ما تفتح اللعبة
    back_key = getattr(pygame, 'K_AC_BACK', None)               # زرار الرجوع في أندرويد
    bg_event = getattr(pygame, 'APP_WILLENTERBACKGROUND', None)
    running = True
    while running:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        for e in pygame.event.get():
            if bg_event is not None and e.type == bg_event:
                game.on_background()
                continue
            if touch:
                handled, alive = touch.handle_event(e, game)
                if handled:
                    running = running and alive
                    continue
            if e.type == pygame.KEYDOWN and back_key is not None and e.key == back_key:
                e = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode='', scancode=0)
            if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
                if not TOUCH:
                    pygame.display.toggle_fullscreen()
                continue
            if e.type == pygame.KEYDOWN and game.state != 'profile':
                if e.key == pygame.K_l:
                    game.do_action('lang')
                    continue
                if e.key == pygame.K_m:
                    change_volume(mute=True)
                    game.toast(S("الصوت: {n}%", n=int(MASTER * 100)), 1.5)
                    continue
                if e.key in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    change_volume(-0.1 if e.key in (pygame.K_MINUS, pygame.K_KP_MINUS) else 0.1)
                    game.toast(S("الصوت: {n}%", n=int(MASTER * 100)), 1.5)
                    continue
            if e.type == pygame.QUIT or not game.handle(e):
                running = False
        game.tick_js(dt)
        game.net_frame(dt)
        if game.state == 'play':
            game.update(dt)
        elif game.state == 'trans':
            game.update_trans(dt)
        else:
            game.t += dt
            if game.js_t <= 0 or game.state == 'pause':
                game.update(dt) if game.state == 'pause' else None
        game.draw(screen)
        present(screen, touch, game)
    game.leave_online()
    pygame.quit()


# ================================================================= الترجمة الإنجليزية
EN.update({
'''تحت وسادة الكنبة''': '''under the sofa cushion''',
'''في الدرج''': '''in the drawer''',
'''ورا الكتب''': '''behind the books''',
'''في الدولاب العلوي''': '''in the upper cupboard''',
'''بين الكتب''': '''between the books''',
'''البيت القديم''': '''The Old House''',
'''أوضة النوم''': '''Bedroom''',
'''المكتبة''': '''Library''',
'''المطبخ''': '''Kitchen''',
'''الصالة''': '''Hall''',
'''الحمّام''': '''Bathroom''',
'''أوضة الأطفال''': '''Children's Room''',
'''المخزن''': '''Storeroom''',
'''أوضة الضيوف''': '''Guest Room''',
'''السفرة''': '''Dining Room''',
'''البدروم''': '''Basement''',
'''العلّية''': '''Attic''',
'''المكتب''': '''Study''',
'''أوضة الغسيل''': '''Laundry Room''',
'''الشرفة''': '''Balcony''',
'''أوضة الخياطة''': '''Sewing Room''',
'''أوضة الموسيقى''': '''Music Room''',
'''المرسم''': '''Art Studio''',
'''الطرقة الكبيرة''': '''Grand Corridor''',
'''أوضة الأجداد''': '''Grandparents' Room''',
'''أوضة الصلاة''': '''Prayer Room''',
'''غرفة الكتب القديمة''': '''Old Books Room''',
'''أوضة الألعاب''': '''Playroom''',
'''الأنتريه''': '''Sitting Room''',
'''المخبأ''': '''Hideout''',
'''غرفة المراية''': '''Mirror Room''',
'''مخزن الخشب''': '''Woodshed''',
'''أوضة الساعة''': '''Clock Room''',
'''غرفة المرضى''': '''Sickroom''',
'''القبو''': '''Cellar''',
'''أوضة الضوء الأحمر''': '''Red Light Room''',
'''غرفة الدُمى''': '''Doll Room''',
'''أوضة السفرجي''': '''Butler's Room''',
'''غرفة النجف''': '''Chandelier Room''',
'''{n}... استنّى''': '''{n}... wait''',
'''مش هتهرب يا {n}''': '''You won't escape, {n}''',
'''{n}.. ورااااك''': '''{n}.. behind youuuu''',
'''أنا شايفك يا {n}''': '''I see you, {n}''',
'''تعالى يا {n}... متخافش''': '''Come here, {n}... don't be afraid''',
'''{n}... كنت مستنيك''': '''{n}... I was waiting for you''',
'''{n}... أنا واقف ورا الباب''': '''{n}... I'm standing behind the door''',
'''{n}.. بصّ ورا''': '''{n}.. look behind you''',
'''مش لوحدك يا {n}''': '''You're not alone, {n}''',
'''{n}... سامعك وإنت بتتنفّس''': '''{n}... I can hear you breathing''',
'''فاضل خطوة واحدة يا {n}''': '''One step left, {n}''',
'''ليه سبتني لوحدي يا {n}؟''': '''Why did you leave me alone, {n}?''',
'''فاضي.''': '''Empty.''',
'''مفيش حاجة هنا... بس حاسس إن حد بيبصلك.''': '''Nothing here... but it feels like someone is watching you.''',
'''الغبار هنا لسه مهزوز... حد لمس المكان من لحظة.''': '''The dust here is still disturbed... someone touched this a moment ago.''',
'''سمعت همس خفيف طالع من هنا.''': '''You hear a faint whisper coming from here.''',
'''ريحة رطوبة تقيلة... وحاجة تانية أوحش.''': '''A heavy smell of damp... and something worse.''',
'''فيه بصمة إيد صغيرة على السطح.''': '''A small handprint on the surface.''',
'''فيه خربشة على الخشب: "اخرج".''': '''Scratched into the wood: "GET OUT".''',
'''مفيش حاجة جوه... بس كان فيه حد هنا.''': '''Nothing inside... but someone was here.''',
'''حاسس إن المكان ده اتحرّك ورايا... مش متأكد.''': '''It feels like this moved behind me... not sure.''',
'''أوضة المعيشة''': '''Living Room''',
'''الممر''': '''Corridor''',
'''ورقة على الترابيزة''': '''Note on the Table''',
'''ورقة بين الكتب''': '''Note Between the Books''',
'''مذكرات قديمة''': '''Old Diary''',
'''ورقة على المكتب''': '''Note on the Desk''',
'''السرير''': '''Bed''',
'''ترابيزة القهوة''': '''Coffee Table''',
'''البوتجاز''': '''Stove''',
'''الحوض''': '''Sink''',
'''الكتب''': '''Books''',
'''الكرسي الهزّاز''': '''Rocking Chair''',
'''الخزنة''': '''Safe''',
'''الترابيزة''': '''Table''',
'''الباب الأمامي''': '''Front Door''',
'''المكتبة الصغيرة''': '''Small Bookcase''',
'''الكنبة''': '''Sofa''',
'''البيانو''': '''Piano''',
'''الكومودينو''': '''Nightstand''',
'''الدولاب''': '''Wardrobe''',
'''الدُرج''': '''Drawer''',
'''رف الكتب''': '''Bookshelf''',
'''مكتب المكتبة''': '''Library Desk''',
'''كرسي هزّاز''': '''Rocking Chair''',
'''التلاجة''': '''Fridge''',
'''الدولاب العلوي''': '''Upper Cupboard''',
'''ترابيزة السفرة''': '''Dining Table''',
'''باب المكتب - مقفول''': '''Study Door - locked''',
'''مكتب كبير''': '''Big Desk''',
'''الصورة الكبيرة''': '''Large Portrait''',
'''مفتاح المكتب النحاسي''': '''Brass Study Key''',
'''المفتاح الصغير''': '''Small Key''',
'''مفتاح الباب الأمامي''': '''Front Door Key''',
'''دوّر على مفتاح المكتب النحاسي''': '''Find the brass study key''',
'''الصندوق الخشب''': '''Wooden Chest''',
'''الخزانة''': '''Cabinet''',
'''المراية الكبيرة''': '''Large Mirror''',
'''الصورة''': '''Portrait''',
'''الدُمية الكبيرة''': '''Large Doll''',
'''مفتاح الشقة''': '''Apartment Key''',
'''فاضي دلوقتي.''': '''Empty now.''',
'''اقرا الأوراق ودوّر على المفاتيح''': '''Read the notes and look for keys''',
'''ورقة مكتوبة بخط مرتعش:''': '''A note in shaky handwriting:''',
'''"الباب الكبير اتقفل لوحده... ومش هيتفتح غير بمفتاحه.''': '''"The big door locked itself... and only its key will open it.''',
'''المفتاح في المكتب اللي فوق، والمكتب مقفول.''': '''The key is in the study upstairs, and the study is locked.''',
'''دوّر كويس... وماتبصّش ورا."''': '''Search well... and do not look behind you."''',
'''لقيت ورقة قديمة:''': '''You found an old note:''',
'''"المفتاح النحاسي بتاع المكتب كنت دايمًا''': '''"I always kept the brass key to the study''',
'''أخبّيه في دولاب أوضة النوم."''': '''hidden in the bedroom wardrobe."''',
'''"كل ليلة بسمع خطوات قدام باب الأوضة.''': '''"Every night I hear footsteps outside the bedroom door.''',
'''النهارده الخطوات وقفت... جوه الأوضة."''': '''Tonight the footsteps stopped... inside the room."''',
'''آخر صفحة متبلّلة بحاجة حمرا...''': '''The last page is soaked in something red...''',
'''"درج المكتب الكبير مفتاحه صغير.''': '''"The big desk drawer has a small key.''',
'''كنت بحطه في حتة باردة... في المطبخ."''': '''I kept it somewhere cold... in the kitchen."''',
'''السرير متبهدل... والملاية لسه دافية!''': '''The bed is a mess... and the sheet is still warm!''',
'''كوباية شاي على الترابيزة... ولسه بتطلّع بخار.''': '''A cup of tea on the table... still steaming.''',
'''البوتجاز بارد... بس سامع صوت غليان من جوه الحلّة!''': '''The stove is cold... but you hear boiling from inside the pot!''',
'''حوالين الترابيزة أربع كراسي. الكرسي الرابع لسه بيهتز.''': '''Four chairs around the table. The fourth is still shaking.''',
'''الحنفية بتنقّط... والميّه لونها مش طبيعي.''': '''The tap is dripping... and the water is an unnatural color.''',
'''كل الكتب دي عن الأرواح والأحلام المزعجة.''': '''All these books are about spirits and disturbing dreams.''',
'''كتاب مفتوح على صفحة مكتوب فيها: "هو شايفك".''': '''A book open to a page that reads: "He sees you".''',
'''الكرسي بيهتز لوحده... بعدت عنه بسرعة.''': '''The chair rocks by itself... you back away quickly.''',
'''خزنة محتاجة رقم سري، ومفيش حاجة هنا تفتحها.''': '''A safe that needs a code, and nothing here opens it.''',
'''الدولاب فاضي دلوقتي.''': '''The wardrobe is empty now.''',
'''التلاجة فاضية... وريحتها وحشة.''': '''The fridge is empty... and it smells awful.''',
'''الدرج فاضي دلوقتي.''': '''The drawer is empty now.''',
'''باب المكتب''': '''Study Door''',
'''فتحت باب المكتب!''': '''You opened the study door!''',
'''اهرب من الباب الأمامي!''': '''Escape through the front door!''',
'''افتح باب المكتب، فوق ناحية اليمين''': '''Open the study door, upper right''',
'''الشقة {n}''': '''Apartment {n}''',
'''باب الشقة''': '''Apartment Door''',
'''مفتاح {r}''': '''{r} Key''',
'''محتاج مفتاح صغير.''': '''You need a small key.''',
'''والأوضة مقفولة، وعلى بابها قفل تقيل.''': '''The room is locked, with a heavy lock on its door.''',
'''ورقة مرمية''': '''Discarded Note''',
'''اهرب من باب الشقة!''': '''Escape through the apartment door!''',
'''يا غريب''': '''stranger''',
'''الخريطة - Tab للإغلاق''': '''Map - Tab to close''',
'''أحمر: باب الشقة   أصفر: باب مقفول   أزرق: إنت''': '''Red: apartment door   Yellow: locked door   Blue: you''',
'''الكشاف''': '''Flashlight''',
'''الخوف''': '''Fear''',
'''حفظ - K''': '''Save - K''',
'''E: تفاعل   F: كشاف   Shift: جري   Tab: خريطة   Esc: قايمة''': '''E: interact   F: flashlight   Shift: run   Tab: map   Esc: menu''',
'''بيت الهمس''': '''Whispering House''',
'''المفتاح فتح الباب... وقدامك شقة تانية.''': '''The key opened the door... and another apartment lies ahead.''',
'''قايمة اللعبة''': '''Game Menu''',
'''تاريخ الميلاد مش صح: اليوم من 1 إلى 31 والشهر من 1 إلى 12''': '''Invalid birth date: day 1 to 31, month 1 to 12''',
'''جوه الدولاب لقيت مفتاح نحاسي تقيل.''': '''Inside the wardrobe you found a heavy brass key.''',
'''ده مفتاح المكتب.''': '''It is the study key.''',
'''التلاجة ريحتها وحشة...''': '''The fridge smells terrible...''',
'''لقيت مفتاح صغير متلزّق في الباب من جوه.''': '''You found a small key stuck to the door from the inside.''',
'''الدرج الكبير مقفول بقفل صغير.''': '''The big drawer is locked with a small lock.''',
'''فتحت الدرج بالمفتاح الصغير...''': '''You opened the drawer with the small key...''',
'''لقيت مفتاح كبير صدّي: مفتاح الباب الأمامي!''': '''You found a big rusty key: the front door key!''',
'''يلا اجري على الباب!''': '''Now run to the door!''',
'''الباب مقفول بمفتاح نحاسي.''': '''The door is locked with a brass key.''',
'''لازم تلاقيه.''': '''You have to find it.''',
'''الباب تقيل ومقفول بإحكام.''': '''The door is heavy and tightly locked.''',
'''محتاج مفتاحه... ومش معاك.''': '''You need its key... and you don't have it.''',
'''افتح درج المكتب''': '''Open the desk drawer''',
'''دوّر على مفتاح صغير للدرج''': '''Find a small key for the drawer''',
'''أوضة {n}''': '''Room {n}''',
'''باب {r} - مقفول''': '''{r} Door - locked''',
'''في {f} في {r}''': '''in the {f} in the {r}''',
'''في {r}''': '''in the {r}''',
'''فتحت {f}...''': '''You opened the {f}...''',
'''ولقيت {k}!''': '''and found the {k}!''',
'''فيه قفل صغير على {f}.''': '''The {f} has a small lock on it.''',
'''المفتاح الكبير بتاع الشقة جوّه {r}.''': '''The big apartment key is inside the {r}.''',
'''مفتاح {r} مخبّي {h}.''': '''The {r} key is hidden {h}.''',
'''مفتاح {r} {h}.''': '''The {r} key is {h}.''',
'''المفتاح الصغير بتاع الدُرج... {h}.''': '''The small key to the drawer... {h}.''',
'''جوه {f}''': '''inside the {f}''',
'''دوّر على مفتاح الشقة جوه {r}''': '''Find the apartment key inside the {r}''',
'''افتح باب {r}''': '''Open the {r} door''',
'''باب {r}''': '''{r} Door''',
'''فتحت باب {r}!''': '''You opened the {r} door!''',
'''الباب مقفول بقفل تقيل.''': '''The door has a heavy lock.''',
'''محتاج مفتاح {r}.''': '''You need the {r} key.''',
'''محتاج مفتاح الشقة... ومش معاك.''': '''You need the apartment key... and you don't have it.''',
'''{t} - عدد الأوض: {n}''': '''{t} - Rooms: {n}''',
'''أهلًا بيك تاني يا {n}...''': '''Welcome back, {n}...''',
'''حاسس إن في حد بيراقبك...''': '''You feel like someone is watching you...''',
'''غيّرت بطارية الكشاف.''': '''You changed the flashlight battery.''',
'''بطاريات: {n}''': '''Batteries: {n}''',
'''الشقة {a} / {b}''': '''Apartment {a} / {b}''',
'''معاك: {i}''': '''Carrying: {i}''',
'''الهدف: {g}''': '''Goal: {g}''',
'''اضغط E للمتابعة''': '''Press E to continue''',
'''لعبة جديدة''': '''New Game''',
'''خروج''': '''Exit''',
'''10 شقق... كل واحدة أكبر وأخطر. دوّر على المفتاح واهرب.''': '''10 apartments... each bigger and scarier. Find the key and escape.''',
'''مفيش موت في اللعبة... بس خضّات كتير!''': '''No death in this game... just lots of scares!''',
'''عرّفنا بنفسك...''': '''Tell us about yourself...''',
'''ابدأ - Enter''': '''Start - Enter''',
'''Tab: الحقل اللي بعده   |   Esc: رجوع''': '''Tab: next field   |   Esc: back''',
'''عدد الأوض: {n}''': '''Rooms: {n}''',
'''الأشباح هنا أكتر... خلّي بالك.''': '''More ghosts here... be careful.''',
'''هربت!''': '''You escaped!''',
'''طلع عليك نور الفجر... والبيوت ورا ضهرك ساكتة.''': '''Dawn light rises on you... and the houses behind you fall silent.''',
'''Enter: القايمة الرئيسية      Esc: خروج''': '''Enter: main menu      Esc: exit''',
'''اكتب اسمك الأول!''': '''Type your name first!''',
'''تم حفظ اللعبة''': '''Game saved''',
'''مقدرتش أحفظ الملف!''': '''Couldn't save the file!''',
'''حاجة وقعت وراك!!''': '''Something fell behind you!!''',
'''النور رجع...''': '''The lights are back...''',
'''الكشاف فصل! دوّر على بطاريات.''': '''The flashlight died! Find batteries.''',
'''اضغط E - {n}''': '''Press E - {n}''',
'''الحركة: WASD أو الأسهم | Shift: جري | E: تفاعل | F: الكشاف | Tab: خريطة''': '''Move: WASD or arrows | Shift: run | E: interact | F: flashlight | Tab: map''',
'''نصيحة: الكشاف بيخلّي الشبح يتراجع، والشموع بتهدّي خوفك.''': '''Tip: the flashlight pushes ghosts back, and candles calm your fear.''',
'''L: اللغة   M: كتم الصوت   - / +: مستوى الصوت   F11: ملء الشاشة''': '''L: language   M: mute   - / +: volume   F11: fullscreen''',
'''الاسم''': '''Name''',
'''يوم الميلاد من 1 إلى 31''': '''Birth day, 1 to 31''',
'''شهر الميلاد من 1 إلى 12''': '''Birth month, 1 to 12''',
'''الشقة دي أصعب... والخضّات أكتر.''': '''This apartment is harder... with more scares.''',
'''كمّل''': '''Resume''',
'''حفظ اللعبة''': '''Save Game''',
'''القايمة الرئيسية''': '''Main Menu''',
'''برافو يا {n}... عديت الشقق العشرة!''': '''Bravo, {n}... you cleared all ten apartments!''',
'''بس سمعت همس بيقول: "{n}... استنّى"''': '''But you heard a whisper say: "{n}... wait"''',
'''...ومكتوب في آخرها: "{name}"''': '''...and at the very end it says: "{name}"''',
'''كل الأنوار طفت!...''': '''All the lights went out!...''',
'''دوّرت تاني... مفيش حاجة.''': '''You searched again... nothing.''',
'''سمعت صرير باب بيتفتح... في مكان ما.''': '''You hear a door creaking open... somewhere.''',
'''مين اللي بيهمس؟!''': '''Who's whispering?!''',
'''خطوات... جاية من فوق.''': '''Footsteps... coming from above.''',
'''مفيش حاجة''': '''Nothing''',
'''كمّل اللعبة: {p} - الشقة {l}''': '''Continue: {p} - Apartment {l}''',
'''لقيت بطارية للكشاف {w}!''': '''You found a flashlight battery {w}!''',
'''النغمة طلعت من البيانو... وإيدك لسه ما لمستوش!''': '''A note rang out from the piano... and you haven't touched it!''',
'''الصوت: {n}%''': '''Volume: {n}%''',
'''راجل عينيه بتتابعك في كل مكان...''': '''A man whose eyes follow you everywhere...''',
'''ويمكن عينيه اتحركت فعلًا.''': '''And maybe his eyes really did move.''',
'''، ''': ''', ''',
})


EN.update({
'''حد بيخبط... من جوه الحيطة!''': '''Someone is knocking... from inside the wall!''',
'''سمعت عياط طفل... بعيد.''': '''You hear a child crying... far away.''',
'''ضحكة طفل... ورا الباب!''': '''A child's giggle... behind the door!''',
'''علبة موسيقى بتشتغل لوحدها...''': '''A music box is playing by itself...''',
'''حاسس بنفس بارد ورا رقبتك...''': '''You feel cold breath on your neck...''',
'''باب اتقفل بقوة في مكان ما!''': '''A door slammed shut somewhere!''',
'''الباب اتقفل وراك بقوة!''': '''A door slammed shut behind you!''',
'''حاسس إن في عيون بتبصلك من الضلمة...''': '''You feel eyes watching you from the dark...''',
'''فيه حاجة واقفة في الضلمة... متدّيش ضهرك!''': '''Something stands in the dark... don't turn your back!''',
'''الشمعة طفت لوحدها!''': '''The candle went out by itself!''',
'''في الضلمة... حد بيتنفّس جنبك.''': '''In the dark... someone is breathing beside you.''',
'''المراية ساكتة... بس حاسس إنها مستنية.''': '''The mirror is still... but it feels like it's waiting.''',
'''بصّيت في المراية... مفيش غير انعكاسك.''': '''You looked into the mirror... only your reflection.''',
'''لحظة... ليه انعكاسك بيبتسم؟''': '''Wait... why is your reflection smiling?''',
'''دُمية قديمة وعنيها زجاج لامع.''': '''An old doll with shiny glass eyes.''',
'''رقبتها مايلة ناحيتك... مكانتش كده من شوية.''': '''Its neck is tilted toward you... it wasn't like that a moment ago.''',
'''الدُمية بتبصلك... ومكانها اتغيّر!''': '''The doll stares at you... and it has moved!''',
'''اطلع''': '''GET OUT''',
'''هو وراك''': '''HE'S BEHIND YOU''',
'''شايفك''': '''I SEE YOU''',
'''مش هتخرج''': '''YOU WON'T LEAVE''',
'''متبصّش''': '''DON'T LOOK''',
'''وراك''': '''BEHIND YOU''',
'''هو هنا''': '''HE'S HERE''',
'''حاجة بتتحرك لما تدير ضهرك؟ بصّلها بالكشاف... وهتقف مكانها.''': '''Something moves when you turn your back? Look at it with the flashlight... and it freezes.''',
})


EN.update({
'''جاري تجهيز الأصوات... (أول مرة بس)''': '''Preparing sounds... (first launch only)''',
'''10 شقق... كل واحدة أكبر وأخطر.''': '''10 apartments... each one bigger and deadlier.''',
'''دوّر على المفتاح واهرب.''': '''Find the key and escape.''',
'''الجويستيك: حركة - اسحبه بعيد للجري''': '''Joystick: move - drag far to run''',
'''زر تفاعل: فتح وتقليب   |   زر كشاف: نور''': '''USE button: open & search   |   LIGHT button: flashlight''',
'''WASD / الأسهم: حركة   |   Shift: جري''': '''WASD / Arrows: move   |   Shift: run''',
'''E: تفاعل   |   F: كشاف   |   Tab: خريطة''': '''E: interact   |   F: flashlight   |   Tab: map''',
'''L: اللغة   |   M: كتم الصوت   |   F11: ملء الشاشة''': '''L: language   |   M: mute   |   F11: fullscreen''',
'''الكشاف بيخلّي الشبح يتراجع، والشموع بتهدّي خوفك.''': '''The flashlight pushes ghosts back, and candles calm your fear.''',
'''حاجة بتتحرك لما تدير ضهرك؟ بصّلها بالكشاف.''': '''Moves when you look away? Light it up.''',
'''تفاعل''': '''USE''',
'''كشاف''': '''LIGHT''',
'''خريطة''': '''MAP''',
'''المس زر التفاعل - {n}''': '''Tap USE - {n}''',
'''المس الشاشة للمتابعة''': '''Tap to continue''',
'''المس الشاشة للرجوع للقايمة''': '''Tap to return to the menu''',
'''يوم الميلاد''': '''Birth day''',
'''شهر الميلاد''': '''Birth month''',
'''رجوع''': '''Back''',
'''مسح''': '''DEL''',
'''مسافة''': '''Space''',
'''التالي''': '''Next''',
'''ابدأ''': '''Start''',
'''حفظ''': '''Save''',
'''حرّك الجويستيك للمشي... وزر التفاعل لفتح الحاجات.''': '''Use the joystick to move... and the USE button to open things.''',
})


EN.update({
'''اللعب أونلاين''': '''Online Mode''',
'''مفيش موت في اللعب الفردي... بس خضّات كتير!''': '''No death in single-player... just lots of scares!''',
'''لحد 8 لاعبين على نفس الشبكة (LAN)''': '''Up to 8 players on the same network (LAN)''',
'''اسمك: {n}''': '''Your name: {n}''',
'''إنشاء غرفة''': '''Create Room''',
'''الانضمام لغرفة''': '''Join Room''',
'''كل اللاعبين لازم يكونوا على نفس الواي فاي أو الشبكة.''': '''All players must be on the same Wi-Fi / network.''',
'''في الأونلاين: لو الخوف اتملى أو وحش لمسك... بتموت!''': '''Online: if your fear bar fills up or a monster touches you... you die!''',
'''رقم الغرفة أو IP المضيف''': '''Room ID or host IP''',
'''انضم''': '''Join''',
'''الغرف المتاحة على الشبكة:''': '''Rooms on your network:''',
'''{r}   |   {h}   |   (اللعبة بدأت)''': '''{r}   |   {h}   |   (in progress)''',
'''بدوّر على غرف على الشبكة...''': '''Looking for rooms on the network...''',
'''لو مفيش حاجة بتظهر: اتأكد إن المضيف فتح غرفة وإنكم على نفس الشبكة.''': '''Nothing showing up? Make sure the host opened a room and you're on the same network.''',
'''اكتب رقم الغرفة واضغط Enter... أو اختار غرفة من القايمة.''': '''Type the room ID and press Enter... or pick a room from the list.''',
'''لو الغرفة مش بتظهر: اكتب IP جهاز المضيف (زي 192.168.1.5).''': '''Room not listed? Type the host's IP address (like 192.168.1.5).''',
'''رقم الغرفة''': '''Room ID''',
'''عنوان المضيف: {ip}''': '''Host address: {ip}''',
'''ابعت الرقم ده لأصحابك علشان ينضموا.''': '''Share this ID with your friends so they can join.''',
'''اللاعبين: {n} / {m}''': '''Players: {n} / {m}''',
'''{n}  (المضيف)''': '''{n}  (host)''',
'''ابدأ اللعبة''': '''Start Game''',
'''مستني المضيف يبدأ اللعبة...''': '''Waiting for the host to start the game...''',
'''خروج من الغرفة''': '''Leave Room''',
'''إنت مُتّ!''': '''You died!''',
'''هربت من الشقة!''': '''You escaped the apartment!''',
'''مستني زمايلك يوصلوا للشقة الجاية...''': '''Waiting for your teammates to reach the next apartment...''',
'''مستني الباقي يخلّصوا...''': '''Waiting for the others to finish...''',
'''بتتفرّج على: {n}''': '''Spectating: {n}''',
'''المس زر التفاعل لتبديل اللاعب''': '''Tap USE to switch player''',
'''← → أو E: تبديل اللاعب''': '''← → or E: switch player''',
'''مفيش حد حي تتفرّج عليه دلوقتي.''': '''No one alive to watch right now.''',
'''مُتّ''': '''DEAD''',
'''الخوف ملا قلبك...''': '''Fear consumed you...''',
'''الوحش مسكك!''': '''The monster got you!''',
'''كلكم متّم... الشقة هتتعاد!''': '''Everyone died... the apartment will restart!''',
'''كلكم متّم... الشقة اتعادت من الأول.''': '''Everyone died... the apartment restarted from the beginning.''',
'''{n} مات!''': '''{n} died!''',
'''{n} هرب من الشقة!''': '''{n} escaped the apartment!''',
'''مقدرتش أفتح الغرفة... تأكد إنك متصل بشبكة.''': '''Couldn't open the room... make sure you're connected to a network.''',
'''جاري الاتصال...''': '''Connecting...''',
'''بدوّر على الغرفة...''': '''Looking for the room...''',
'''الغرفة مش موجودة على الشبكة. جرّب تكتب IP المضيف.''': '''Room not found on the network. Try typing the host's IP.''',
'''الغرفة مليانة (8 لاعبين).''': '''The room is full (8 players).''',
'''اللعبة بدأت بالفعل... مينفعش تنضم دلوقتي.''': '''The game already started... you can't join now.''',
'''نسخة اللعبة مختلفة عن نسخة المضيف.''': '''Your game version differs from the host's.''',
'''الغرفة رفضت انضمامك.''': '''The room refused your request.''',
'''مقدرتش أوصل للمضيف... اتأكد من الرقم ومن الشبكة.''': '''Couldn't reach the host... check the ID and your network.''',
'''المضيف قفل الغرفة.''': '''The host closed the room.''',
'''الاتصال بالغرفة اتقطع.''': '''Connection to the room was lost.''',
})


if __name__ == "__main__":
    main()