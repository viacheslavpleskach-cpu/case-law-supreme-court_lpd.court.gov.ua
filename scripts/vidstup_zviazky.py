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

LEVEL = {'ВП': 2, 'ОП': 3, 'палата': 4, 'колегія': 5}


def load_rishennia_ruchni(path):
    """data/rishennia_ruchni.csv (id;sprava;data;prymitka): рішення, з якого виведено позицію «Змінено»,
    якщо lpd прив'язав до неї лише постанову, якою відступлено."""
    return load_ruchni(path)


def fix_own_departures(rows, by_case, ranks, rishennia_ruchni_path=None, log=print):
    """lpd часто прив'язує до старої позиції «Змінено» і саму постанову, якою відступлено, та переносить позицію
    в рубрику ОП / палати. Така постанова позначається d['vidstup'] = True, ставиться в кінець переліку рішень,
    а рівень позиції визначається за рештою рішень (якщо склад суду в них відомий)."""
    ruchni = load_rishennia_ruchni(rishennia_ruchni_path)
    changed = []
    for r in rows:
        if not (r.get('poznachka') or '').startswith('Змінено'):
            continue
        dep = {(norm(x['sprava']), x['data']) for x in r.get('vidstupleno_u') or []}
        for d in r['rishennia']:
            if (norm(d.get('sprava')), d.get('data')) in dep:
                d['vidstup'] = True
        rest = [d for d in r['rishennia'] if not d.get('vidstup')]
        if not rest and r['id'] in ruchni:
            for x in ruchni[r['id']]:
                hits = [d for _, d in by_case.get(norm(x['sprava']), []) if not x.get('data') or d.get('data') == x['data']]
                if hits:
                    nd = {k: v for k, v in hits[0].items() if k != 'vidstup'}
                    nd['dodano'] = 'ручне уточнення: ' + (x.get('prymitka') or '')
                    rest.append(nd)
            r['rishennia'] = rest + [d for d in r['rishennia'] if d.get('vidstup')]
        if any(d.get('vidstup') for d in r['rishennia']):
            r['rishennia'] = rest + [d for d in r['rishennia'] if d.get('vidstup')]
        if r['riven'] in (2, 3, 4) and rest and all(d.get('sklad') for d in rest) and not any(d.get('zrazkova') for d in rest):
            new = min(LEVEL.get(d['sklad'], 5) for d in rest)
            if new > r['riven']:
                changed.append((r['id'], r['riven_nazva'], ranks[new]))
                r['riven'], r['riven_nazva'] = new, ranks[new]
        if rest:
            r['data_rishennia'] = max([d['data'] for d in rest if d.get('data')], default=r.get('data_rishennia'))
    if changed:
        log('відступи: рівень уточнено за рішеннями без постанови, якою відступлено: ' +
            '; '.join(f'#{i} {a} → {b}' for i, a, b in changed))
    return changed


def link_departures(rows, cache_dir=None, online=True, ruchni_path=None, threads=3, log=print, ranks=None, rishennia_ruchni_path=None):
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
    if ranks:
        fix_own_departures(rows, by_case, ranks, rishennia_ruchni_path, log)
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


# ---------- позиції «З відступом»: від яких постанов відступлено ----------

END = re.compile(r'(?<![№\d])\.\s+(?=[А-ЯІЇЄҐ][а-яіїєґʼ’`\']{3,}\s)')
NEG = re.compile(r'(?:не\s+вбача\w*|не\s+знаход\w*|відсутн\w+|немає|нема)\s+(?:\w+\s+){0,3}підстав\w*\s+(?:\w+\s+){0,2}(?:для\s+)?відступ', re.I)


VID2 = re.compile(r'відступ|конкретиз|уточн\w*\s+(?:свою\s+|правов\w+\s+)?(?:висновок|позиці|правов)|відійш', re.I)
VID_STRICT = re.compile(r'відступ\w*\s+(?:\w+\s+){0,2}від\s+(?:\S+\s+){0,8}?(?:висновк|позиці|підход|практик)', re.I)


def windows(t, size=650, pat=VID2):
    """Фрагменти від слова «відступ…» (також «конкретизує», «уточнено висновок») до кінця речення (не довше size);
    заперечення («не вбачає підстав для відступу») — пропускаються."""
    t = re.sub(r'\s+', ' ', t or '')
    out = []
    for m in pat.finditer(t):
        pre = t[max(0, m.start() - 120):m.end() + 20]
        if NEG.search(pre):
            continue
        seg = t[m.start():m.start() + size]
        e = END.search(seg, 40)
        out.append((t[max(0, m.start() - 250):m.start()], seg[:e.start() + 1] if e else seg))
    return out


def link_indented(rows, cache_dir=None, online=True, threads=3, log=print):
    """r['vidstupleno_vid'] для позицій «З відступом»: постанови, від висновків яких відступлено.
    Джерела: (1) позиції «Змінено», для яких цю позицію встановлено як ту, що відступила (найнадійніше);
    (2) текст позиції — справи, названі після «відступ…» і ухвалені раніше за постанову з відступом;
    (3) якщо нічого не знайдено — повний текст постанови ВП / ОП / палати (кеш), «ймовірно»."""
    by_case = collections.defaultdict(list)
    byid = {r['id']: r for r in rows}
    for r in rows:
        for d in r['rishennia']:
            if d.get('sprava'):
                by_case[norm(d['sprava'])].append((r, d))

    def resolve(case, date, before, dzherelo, nadiinist):
        hits = by_case.get(case, [])
        use = [(r, d) for r, d in hits if date and d.get('data') == date]
        if not use and not date:
            cand = sorted([(r, d) for r, d in hits if (d.get('data') or '') < before], key=lambda x: x[1].get('data') or '')
            use = [x for x in cand if x[1].get('data') == cand[-1][1].get('data')] if cand else []
        d0 = use[0][1] if use else {}
        return {'sprava': d0.get('sprava') or case, 'data': d0.get('data') or date, 'sud': d0.get('sud'), 'sklad': d0.get('sklad'),
                'doc_id': d0.get('doc_id'), 'edrsr': d0.get('edrsr'), 'pozytsii': sorted({r['id'] for r, d in use}),
                'dzherelo': dzherelo, 'nadiinist': nadiinist}

    rev = collections.defaultdict(list)
    for m in rows:
        for x in m.get('vidstupleno_u') or []:
            for p in x.get('pozytsii') or []:
                rev[p].append((m, x))

    def from_text(t, own_dep, d_dep, dzherelo, nd, strict=False, lvl=5):
        res = {}
        for pre, seg in windows(t, pat=VID_STRICT if strict else VID2):
            for mm in CASE.finditer(seg):
                if strict and mm.start() > 450:
                    break
                c = norm(mm.group(1))
                dt = date_near(pre + seg, len(pre) + mm.start()) or ''
                if c in own_dep and (not dt or dt == d_dep):
                    continue
                if dt and dt >= d_dep:
                    continue
                if strict:
                    v = resolve(c, dt, d_dep, dzherelo, nd)
                    if v['sklad'] and LEVEL.get(v['sklad'], 5) < lvl:  # нижчий склад не відступає від вищого (ОП — від ВП)
                        continue
                key = (c, dt)
                if key not in res:
                    res[key] = resolve(c, dt, d_dep, dzherelo, nd)
        return res

    ind = [r for r in rows if (r.get('poznachka') or '').startswith('З відступом')]
    need_full = []
    for r in ind:
        docs = [d for d in r['rishennia'] if not d.get('vidstup')]
        dep = [d for d in docs if d.get('sklad') in RANK or d.get('zrazkova')] or docs
        d_dep = max([d['data'] for d in dep if d.get('data')], default='9999')
        own_dep = {norm(d['sprava']) for d in dep if d.get('sprava') and d.get('data') == d_dep}
        found = collections.OrderedDict()
        for m, x in rev.get(r['id'], []):
            md = [d for d in m['rishennia'] if not d.get('vidstup')] or m['rishennia']
            for d in sorted(md, key=lambda d: d.get('data') or '', reverse=True)[:1]:
                found.setdefault((norm(d.get('sprava')), d.get('data')),
                                 {'sprava': d.get('sprava'), 'data': d.get('data'), 'sud': d.get('sud'), 'sklad': d.get('sklad'),
                                  'doc_id': d.get('doc_id'), 'edrsr': d.get('edrsr'), 'pozytsii': [m['id']],
                                  'dzherelo': f"позиція #{m['id']} «Змінено»", 'nadiinist': 'підтверджено'})
        for k, v in from_text(r['tekst'], own_dep, d_dep, 'текст позиції', 'підтверджено').items():
            if not any(k[0] == f[0] and (not k[1] or not f[1] or k[1] == f[1]) for f in found):
                found[k] = v
        r['vidstupleno_vid'] = list(found.values())
        if not found:
            need_full.append((r, dep, own_dep, d_dep))

    if need_full and cache_dir:
        miss = [d for r, dep, _, _ in need_full for d in dep if d.get('sklad') in RANK or d.get('zrazkova')]
        miss = [d for d in miss if not os.path.exists(os.path.join(cache_dir, f"{d['id']}.txt.gz"))]
        if miss and online:
            log(f'відступи: завантажую повні тексти {len(miss)} постанов')
            with cf.ThreadPoolExecutor(max(1, min(threads, 3))) as ex:
                list(ex.map(lambda d: fulltext(d, cache_dir, True), miss))
        for r, dep, own_dep, d_dep in need_full:
            res = {}
            for d in dep:
                if not (d.get('sklad') in RANK or d.get('zrazkova')):
                    continue
                t = fulltext(d, cache_dir, False) or ''
                lvl = 1 if d.get('zrazkova') else LEVEL.get(d.get('sklad'), 5)
                res.update(from_text(t, own_dep, d_dep, 'повний текст постанови', 'ймовірно', strict=True, lvl=lvl))
            r['vidstupleno_vid'] = list(res.values())[:6]
    for r in ind:
        dated = {norm(x['sprava']) for x in r['vidstupleno_vid'] if x.get('data')}
        r['vidstupleno_vid'] = [x for x in r['vidstupleno_vid'] if x.get('data') or norm(x['sprava']) not in dated]
        r['vidstupleno_vid'].sort(key=lambda x: (NADIINIST.get(x['nadiinist'], 2), x['data'] or ''), reverse=False)
        own = {(norm(d.get('sprava')), d.get('data')) for d in r['rishennia']}
        for d in r['rishennia']:
            if any((norm(x['sprava']), x['data']) == (norm(d.get('sprava')), d.get('data')) for x in r['vidstupleno_vid']):
                d['vidstup_vid'] = True  # lpd прив'язав до нової позиції й постанову, від якої відступлено
    n = sum(1 for r in ind if r['vidstupleno_vid'])
    log(f'відступи: постанови, від яких відступлено, встановлено для {n} з {len(ind)} позицій «З відступом»')
    return n, len(ind)
