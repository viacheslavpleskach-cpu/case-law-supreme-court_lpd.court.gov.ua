"""Зв'язки «від позиції відступлено» → постанова, у якій здійснено відступ.

Автор: В'ячеслав Плескач

API lpd не заповнює linkedLegalPositions, тому зв'язок виводиться з текстів (у порядку надійності):
  А) текст самої позиції «Змінено» («Відступлено … постановою ВП ВС від … у справі № …»);
  Б) тексти інших позицій: у реченні з «відступ…» після слова «відступ» названо № справи
     позиції «Змінено»; постанова, що відступила, — названа в цьому реченні до «відступ…»
     або та, з якої виведено цю іншу позицію;
  В) повні тексти постанов ВП / ОП / палат, з яких виведено позиції «З відступом»:
     у тексті згадано № справи позиції «Змінено» (поруч зі словом «відступ…» — «підтверджено»,
     інакше — «ймовірно»).
  Ручні уточнення — data/vidstupy_ruchni.csv (id;sprava;data;prymitka) мають перевагу.
Кандидат приймається, лише якщо постанова пізніша за найранішу дату рішень позиції «Змінено».
Результат: r['vidstupleno_u'] = [{sprava, data, sud, sklad, doc_id, edrsr, pozytsii, dzherelo, nadiinist}].
"""
import base64
import collections
import concurrent.futures as cf
import csv
import gzip
import html
import json
import os
import re
import urllib.request

API = 'https://lpd-api-prod.court.gov.ua/api/v1'
HOMO = str.maketrans('АВСЕНІКМОРТХаесіорху', 'ABCEHIKMOPTXaecIopxy')
CASE = re.compile(r'(?:№|N)\s*([0-9][0-9A-Za-zА-Яа-яІіЇїЄєҐґ.\-/]*/[0-9]{2,4}(?:-[а-яієa-z]{1,3})?|[0-9]\.[0-9]{3}\.[0-9]{4}\.[0-9]{6})')
MONTHS = {'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4, 'травня': 5, 'червня': 6, 'липня': 7, 'серпня': 8,
          'вересня': 9, 'жовтня': 10, 'листопада': 11, 'грудня': 12}
DATE_W = re.compile(r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(\d{4})')
DATE_D = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})')
VID = re.compile(r'відступ', re.I)
PASSIVE = re.compile(r'відступлено|здійснено відступ|відступ\w*\s+від\s+(?:цього|цієї|цих|вказаного|зазначеного|згаданого|такого|даного|'
                     r'наведеного|викладеного\s+вище|висновк\w*,?\s+викладен\w*\s+у\s+цій)', re.I)
SENT = re.compile(r'(?<=[.;!?»"])\s+(?=[А-ЯІЇЄҐA-Z0-9])')
RANK = {'ВП': 0, 'ОП': 1, 'палата': 2}
NADIINIST = {'підтверджено': 0, 'ймовірно': 1}


def norm(c):
    c = (c or '').translate(HOMO).lower()
    c = re.sub(r'\s', '', c).rstrip('.,;)')
    return re.sub(r'-[а-яієa-z]{1,3}$', '', c)


def dates_in(s):
    out = []
    for m in DATE_W.finditer(s):
        out.append((m.start(), f'{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}'))
    for m in DATE_D.finditer(s):
        if 1 <= int(m.group(2)) <= 12:
            out.append((m.start(), f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'))
    return out


def date_near(s, pos):
    """Остання дата перед № справи (не далі 120 символів)."""
    best = None
    for p, d in dates_in(s):
        if p < pos and pos - p <= 120:
            best = d
    return best


def sentences(t):
    t = re.sub(r'\s+', ' ', t or '')
    return [s for s in SENT.split(t) if VID.search(s)]


# ---------- повні тексти постанов (кеш) ----------

def fulltext(doc, cache_dir, online=True):
    """Повний текст рішення lpd (поле id рішення в базі), кеш — cache_dir/<id>.txt.gz."""
    p = os.path.join(cache_dir, f"{doc['id']}.txt.gz")
    if os.path.exists(p):
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            return f.read()
    if not online:
        return None
    try:
        d = json.load(urllib.request.urlopen(f"{API}/document/{doc['id']}", timeout=90))
    except Exception:
        return None
    t = d.get('fullText') or ''
    try:
        t = gzip.decompress(base64.b64decode(t)).decode('utf-8', 'ignore')
    except Exception:
        pass
    t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t))).strip()
    if t:
        os.makedirs(cache_dir, exist_ok=True)
        with gzip.open(p + '.part', 'wt', encoding='utf-8') as f:
            f.write(t)
        os.replace(p + '.part', p)
    return t


def load_ruchni(path):
    out = collections.defaultdict(list)
    if path and os.path.exists(path):
        with open(path, encoding='utf-8-sig') as f:
            for x in csv.DictReader(f, delimiter=';'):
                if (x.get('id') or '').strip().isdigit():
                    out[int(x['id'])].append(x)
    return out


# ---------- основне ----------

def link_departures(rows, cache_dir=None, online=True, ruchni_path=None, threads=3, log=print):
    by_case = collections.defaultdict(list)
    for r in rows:
        for d in r['rishennia']:
            if d.get('sprava'):
                by_case[norm(d['sprava'])].append((r, d))

    def info(d, dzherelo, nadiinist, pozytsii, via=None):
        return {'sprava': d.get('sprava'), 'data': d.get('data'), 'sud': d.get('sud'), 'sklad': d.get('sklad'),
                'doc_id': d.get('doc_id'), 'edrsr': d.get('edrsr'), 'pozytsii': pozytsii,
                'dzherelo': dzherelo, 'nadiinist': nadiinist, 'cherez': via}

    def resolve(case, date, dzherelo, via=None):
        hits = by_case.get(case, [])
        use = [(r, d) for r, d in hits if date and d.get('data') == date] or ([] if date else hits)
        if use:
            return info(use[0][1], dzherelo, 'підтверджено', sorted({r['id'] for r, d in use}), via)
        return {'sprava': case, 'data': date, 'sud': None, 'sklad': None, 'doc_id': None, 'edrsr': None,
                'pozytsii': [], 'dzherelo': dzherelo, 'nadiinist': 'підтверджено', 'cherez': via}

    mention = collections.defaultdict(list)  # № справи → [(позиція, речення, позиція в реченні)]
    for r in rows:
        for s in sentences(r['tekst']):
            for m in CASE.finditer(s):
                mention[norm(m.group(1))].append((r, s, m.start()))

    mod = [r for r in rows if (r.get('poznachka') or '').startswith('Змінено')]
    unresolved = []
    for r in mod:
        own = {norm(d['sprava']) for d in r['rishennia'] if d.get('sprava')}
        d0 = min([d['data'] for d in r['rishennia'] if d.get('data')], default='0000')
        found = collections.OrderedDict()
        own_cand = []

        # А: власний текст
        for s in sentences(r['tekst']):
            k = VID.search(s).start()
            cs = [(m, norm(m.group(1))) for m in CASE.finditer(s)]
            before = [(m, c) for m, c in cs if m.start() < k]
            after = [(m, c) for m, c in cs if m.start() > k] if PASSIVE.search(s) else []
            for m, c in (before or after):
                dt = date_near(s, m.start()) or max([d.get('data') or '' for _, d in by_case.get(c, [])], default='')
                if dt and dt > d0 and c not in own:
                    found.setdefault((c, dt), resolve(c, dt, 'текст позиції'))
                elif dt and c in own and dt >= d0 and len(own) == 1 and PASSIVE.search(s):
                    own_cand.append((c, dt))  # lpd прив'язала до позиції саму постанову, яка відступила

        # Б: інші позиції
        for c in own:
            for p, s, pos in mention.get(c, []):
                k = VID.search(s).start()
                if p['id'] == r['id'] or pos < k:
                    continue
                pown = {norm(d['sprava']) for d in p['rishennia'] if d.get('sprava')}
                others = []
                for m in CASE.finditer(s):
                    cc = norm(m.group(1))
                    if m.start() >= k or cc in own or cc in pown:
                        continue
                    dt = date_near(s, m.start()) or max([d.get('data') or '' for _, d in by_case.get(cc, [])], default='')
                    if dt and dt > d0:
                        others.append((cc, dt))
                if others:
                    for cc, dt in others:
                        found.setdefault((cc, dt), resolve(cc, dt, f"текст позиції #{p['id']}", p['id']))
                    continue
                ds = [d for d in p['rishennia'] if (d.get('data') or '') > d0 and norm(d.get('sprava')) not in own]
                if not ds and (p.get('poznachka') or '').startswith('З відступом'):
                    ds = [d for d in p['rishennia'] if (d.get('data') or '') > d0]
                ds.sort(key=lambda d: (RANK.get(d.get('sklad') or '', 3), d.get('data') or ''))
                for d in ds[:1]:
                    found.setdefault((norm(d['sprava']), d['data']),
                                     info(d, f"текст позиції #{p['id']}", 'підтверджено', [p['id']], p['id']))
        if not found:  # А2: lpd дописала до старої позиції новий висновок без слова «відступ»
            dmax = max([d['data'] for d in r['rishennia'] if d.get('data')], default='0000')
            t = re.sub(r'\s+', ' ', r['tekst'] or '')
            for s in SENT.split(t):
                if not re.search(r'Велик\w* Палат|ВП ВС|ОП|[Оо]б.\w*днан\w* палат|судов\w* палат', s):
                    continue
                for m in CASE.finditer(s):
                    c = norm(m.group(1))
                    dt = date_near(s, m.start()) or ''
                    if c not in own and dt > dmax:
                        found.setdefault((c, dt), resolve(c, dt, 'текст позиції'))
        if not found:
            for c, dt in own_cand:
                found.setdefault((c, dt), resolve(c, dt, 'текст позиції'))
        # якщо є рішення, знайдене в базі, невстановлені з тією самою датою (описки в тексті) відкидаються
        dates_ok = {v['data'] for v in found.values() if v['doc_id']}
        lst = [v for v in found.values() if v['doc_id'] or v['data'] not in dates_ok]
        r['vidstupleno_u'] = lst
        if not lst:
            unresolved.append(r)

    # В: повні тексти постанов вищих складів, з яких виведено позиції «З відступом»
    if unresolved and cache_dir:
        cand = []
        for p in rows:
            if not (p.get('poznachka') or '').startswith('З відступом'):
                continue
            for d in p['rishennia']:
                if d.get('sklad') in RANK or d.get('zrazkova'):
                    cand.append((p, d))
        need = {d['id']: d for p, d in cand}
        miss = [d for d in need.values() if not os.path.exists(os.path.join(cache_dir, f"{d['id']}.txt.gz"))]
        if miss and online:
            log(f'відступи: завантажую повні тексти {len(miss)} постанов')
            with cf.ThreadPoolExecutor(max(1, min(threads, 3))) as ex:
                list(ex.map(lambda d: fulltext(d, cache_dir, True), miss))
        texts = {i: fulltext(d, cache_dir, False) for i, d in need.items()}
        for r in unresolved:
            own = [d['sprava'] for d in r['rishennia'] if d.get('sprava')]
            pats = [re.compile(r'№\s*' + re.escape(re.sub(r'-[а-яієa-z]{1,3}$', '', c)).replace('/', r'\s*/\s*') + r'(?![0-9])')
                    for c in own]
            d0 = min([d['data'] for d in r['rishennia'] if d.get('data')], default='0000')
            found = {}
            for p, d in cand:
                if p['id'] == r['id'] or (d.get('data') or '') <= d0 or d['sprava'] in own:
                    continue
                t = texts.get(d['id']) or ''
                for pt in pats:
                    m = pt.search(t)
                    if not m:
                        continue
                    win = t[max(0, m.start() - 700):m.end() + 300]
                    nd = 'підтверджено' if VID.search(win) else 'ймовірно'
                    key = (d['sprava'], d['data'])
                    if key not in found or NADIINIST[nd] < NADIINIST[found[key]['nadiinist']]:
                        found[key] = info(d, f"повний текст постанови (позиція #{p['id']})", nd, [p['id']], p['id'])
                    break
            lst = list(found.values())
            if any(v['nadiinist'] == 'підтверджено' for v in lst):
                lst = [v for v in lst if v['nadiinist'] == 'підтверджено']
            r['vidstupleno_u'] = lst

    # ручні уточнення
    byid = {r['id']: r for r in rows}
    for i, xs in load_ruchni(ruchni_path).items():
        if i in byid:
            byid[i]['vidstupleno_u'] = [dict(resolve(norm(x['sprava']), (x.get('data') or '').strip() or None, 'ручне уточнення'),
                                             prymitka=x.get('prymitka') or '') for x in xs if x.get('sprava')]

    for r in mod:
        r['vidstupleno_u'].sort(key=lambda x: (not x['doc_id'], NADIINIST.get(x['nadiinist'], 2),
                                               RANK.get(x['sklad'] or '', 3), x['data'] or ''))
    return sum(1 for r in mod if r['vidstupleno_u']), len(mod)


def korotko(v):
    """«ОП КЦС 24.02.2025 № 395/2693/23» — для покажчиків і таблиць."""
    d = v.get('data') or ''
    dd = f'{d[8:10]}.{d[5:7]}.{d[:4]}' if len(d) == 10 else ''
    sk = v.get('sklad') or ''
    sud = v.get('sud') if sk in ('ОП', 'палата', 'колегія') and v.get('sud') not in (None, '', 'Велика Палата') else ''
    head = ' '.join(x for x in (sk, sud) if x)
    s = f"{head} {dd} № {v.get('sprava')}".strip()
    return s + (' (ймовірно)' if v.get('nadiinist') == 'ймовірно' else '')
