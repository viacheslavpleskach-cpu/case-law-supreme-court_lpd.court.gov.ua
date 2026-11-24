#!/usr/bin/env python3
"""Синхронізація бази правових позицій ВС з lpd.court.gov.ua.

Автор: В'ячеслав Плескач

Завантажує через відкритий API всі правові позиції, рубрикатор, суди, рішення ЄСПЛ
і перелік дайджестів; нормалізує їх, визначає рівень (зразкова справа → ВП → ОП →
палата → колегія), будує покажчики і журнал змін.

  python3 scripts/lpd_sync.py                # повна синхронізація
  python3 scripts/lpd_sync.py --docs 600     # + дозібрати шапки 600 рішень (склад суду)
  python3 scripts/lpd_sync.py --offline      # лише перебудувати файли з кешу

Запити послідовні, з паузою: сайт державний, не перевантажувати.
"""
from zoneinfo import ZoneInfo
import argparse, base64, collections, csv, datetime as dt, gzip, html, json, os, re, sys, time, urllib.request

API = 'https://lpd-api-prod.court.gov.ua/api/v1'
SITE = 'https://lpd.court.gov.ua'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(ROOT, 'cache')
VIEWS = os.path.join(ROOT, 'pokazhchyky')
CHANGES = os.path.join(ROOT, 'zminy')
PAUSE = 0.7

RANKS = {1: 'Зразкова справа', 2: 'Велика Палата', 3: "Об'єднана палата", 4: 'Палата', 5: 'Колегія суддів'}
COURT_BY_LEGACY = {1: '9931', 2: '9941', 3: '9951', 5: '9911', 6: '9921'}
COURT_NAME = {'9931': 'КЦС', '9941': 'ККС', '9951': 'Велика Палата', '9911': 'КГС', '9921': 'КАС'}
MARK = {'indented': 'З відступом', 'modified': 'Змінено (від позиції відступлено)'}

# рубрики-маркери рівня
CAT_ZRAZKOVI = {3403, 1982}                       # ВП «Зразкові справи», КАС «Зразкові рішення»
CAT_OP = {1936, 1983}                             # КЦС, КАС: постанови ОП
CAT_OP_OR_PALATA = {1959}                         # ККС «ОБ'ЄДНАНА ПАЛАТА, ПАЛАТА»
CAT_PALATA = {1984, 1985, 1986}                   # КАС: судові палати


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def req(path, body=None, timeout=180, tries=3):
    url = API + path
    for t in range(tries):
        try:
            if body is None:
                r = urllib.request.Request(url)
            else:
                r = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(r, timeout=timeout) as f:
                return json.load(f)
        except Exception as e:
            log('  помилка', path, e)
            time.sleep(5 * (t + 1))
    raise RuntimeError('не вдалося: ' + path)


def ddate(d):
    """Дата рішення: law_date, інакше adjudication_date (у старих записах — UTC-зсув на добу назад)."""
    v = d.get('law_date') or d.get('adjudication_date')
    if not v:
        return ''
    v = str(v)
    if 'T' in v and v[11:13] >= '18':
        return (dt.date.fromisoformat(v[:10]) + dt.timedelta(days=1)).isoformat()
    return v[:10]


def plain(h):
    if not h:
        return ''
    h = re.sub(r'</p>|<br\s*/?>|</li>', '\n', h)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', h))
    t = re.sub(r'[ \t ]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


# ---------- завантаження ----------

def fetch_all():
    os.makedirs(CACHE, exist_ok=True)
    out = {}
    log('рубрикатор, суди, дайджести…')
    out['categories'] = req('/category/list')
    out['courts'] = req('/court/list')
    out['digest_nav'] = req('/digest/navigation')
    out['digest_categories'] = req('/digest/categories')
    out['digests'] = req('/digest/search', {'query': '', 'filters': [], 'digestIds': [], 'excludeDigestIds': [], 'searchScope': 'all'})['results']
    log('позиції…')
    pos, page = [], 1
    while True:
        d = req('/legal-position/recent', {'pager': {'page': page, 'documentsOnPage': 500}})
        if not d.get('data'):
            break
        pos += d['data']
        log('  сторінка', page, len(pos))
        page += 1
        time.sleep(PAUSE)
    # пагінація нестабільна (однакові approvedAt у старих записів): прибрати дублікати й дозапитати пропущені
    seen, uniq = set(), []
    for p in pos:
        if p['id'] not in seen:
            seen.add(p['id']); uniq.append(p)
    snap = os.path.join(CACHE, 'snapshot_prev.json.gz')
    if os.path.exists(snap):
        with gzip.open(snap, 'rt') as f:
            prev = {int(k) for k in json.load(f)}
        miss = sorted(prev - seen)
        log('  дублікатів', len(pos) - len(uniq), '; пропущених порівняно зі знімком', len(miss))
        for i in miss[:500]:
            try:
                d = req(f'/legal-position/{i}', tries=2)
            except RuntimeError:
                continue
            if d and d.get('id') and d.get('status', True):
                uniq.append(d)
            time.sleep(PAUSE)
    out['positions'] = uniq
    log('рішення (номери справ)…')
    docs, page = [], 1
    while True:
        d = req('/document/list', {'pager': {'page': page, 'documentsOnPage': 500}, 'filter': {}})
        if not d.get('data'):
            break
        for x in d['data']:
            x['lp'] = [y['id'] for y in x.pop('legalPositions', []) or []]
        docs += d['data']
        page += 1
        time.sleep(PAUSE)
    log('  рішень', len(docs))
    out['documents'] = docs
    echr, page = [], 1
    while True:
        d = req('/document-echr/list', {'pager': {'page': page, 'documentsOnPage': 100}, 'filter': {}})
        if not d.get('data'):
            break
        echr += d['data']
        page += 1
        if len(d['data']) < 100:
            break
    out['echr'] = echr
    with gzip.open(os.path.join(CACHE, 'raw_latest.json.gz'), 'wt', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    return out


def load_cached():
    with gzip.open(os.path.join(CACHE, 'raw_latest.json.gz'), 'rt', encoding='utf-8') as f:
        return json.load(f)


# ---------- шапки рішень (склад суду) ----------

DOCS = os.path.join(CACHE, 'doc_heads.jsonl')


def load_heads():
    heads = {}
    for fn, op in ((DOCS + '.gz', gzip.open), (DOCS, open)):
        if not os.path.exists(fn):
            continue
        try:
            with op(fn, 'rt', encoding='utf-8') as f:
                for l in f:
                    try:
                        d = json.loads(l)
                        heads[d['id']] = d
                    except ValueError:
                        pass
        except (EOFError, OSError):      # обірваний запис — беремо прочитане
            pass
    return heads


def prov_from_head(h):
    """№ провадження з шапки рішення («Провадження № 14-48цс22», «провадження № 61-2437св24», «К/9901/…»)."""
    m = re.search(r'провадженн\w*\s*№\s*((?:\d{2}\s?-\s?\d+\s?[а-яіґ]+\s?\d{2})|(?:[КК]/\d{3,4}/\d+/\d{2}))', h[:1500], re.I)
    return re.sub(r'\s', '', m.group(1)) if m else None


NAME = re.compile(r"[А-ЯІЇЄҐ][а-яіїєґʼ’'\-]+\s+[А-ЯІЇЄҐ]\.\s?[А-ЯІЇЄҐ]\.")


def sklad_from_head(h):
    """Склад суду за шапкою рішення: ВП / ОП / палата / колегія (None — не розпізнано)."""
    h = h[:2500]
    h = re.sub(r'(?<=[а-яіїєґА-ЯІЇЄҐ])[oaeiрc](?=[а-яіїєґ])|(?<=[а-яіїєґ])[oaeic]', lambda m: 'оаеіс'['oaeic'.find(m.group(0))] if m.group(0) in 'oaeic' else m.group(0), h)
    if re.search(r'Велик\w*\s*Палат\w*\s+Верховного\s+Суду', h[:900]) or re.search(r'у\s+складі\s+Великої\s*Палати', h) \
            or re.search(r'[Пп]ровадження\s*№\s*1[1-4]\s?-\s?\d', h[:900]):
        return 'ВП'
    if re.search(r"[Оо]б\W{0,3}\s?єднан\w*\s+[Пп]алат", h[:1500]) or re.search(r'[Пп]ровадження\s*№\s*\d{2}\s?-\s?\d+\s?(?:сво|кмо)', h[:900]):
        return 'ОП'
    m = re.search(r'(?:у складі|в складі|колегією|Колегія)[^.]{0,200}', h)
    s = m.group(0) if m else h[:1500]
    if re.search(r'\b\w+\s+судов\w+\s+палат\w*\s+касаційного|\w+ою\s+судовою\s+палатою|провадження\s*№\s*\d{2}\s?-\s?\d+\s?(?:свп|кмп)', h[:900], re.I) \
            and not re.search(r'колег', h[:900], re.I):
        return 'палата'
    if re.search(r'колег\w*[\s:]+(?:суддів|\S+\s+судової\s+палати)', s, re.I) or re.search(r'[Пп]ровадження\s*№\s*\d{2}\s?-\s?\d+\s?(?:св|км|ск|кс)\s?\d', h[:900]):
        return 'колегія'
    if re.search(r'палат\w*\s+(?:з|для)\s+розгляду|(?:у|в)\s+складі\s+(?:\S+\s+)?(?:[Сс]удової\s+)?[Пп]алати|суддів\s+(?:судової\s+)?[Пп]алати', s) \
            or re.search(r'\b\w+ою\s+судовою\s+палатою|\w*ова\s+палата\s+Касаційного|[Сс]удов\w+\s+[Пп]алат\w*\s+(?:з|для)\s+розгляду', h[:900]) \
            or re.search(r'[Пп]ровадження\s*№\s*\d{2}\s?-\s?\d+\s?свп', h[:900]):
        return 'палата'
    # «у складі суддів Касаційного … суду: А. – головуючого, Б., В.» / «судді-доповідача …» — рахуємо суддів
    m = re.search(r'(?:у|в)\s+складі\s*:?\s*(?:суддів\s+|судді(?:-доповідача)?\s+)?(?:Касаційного\s+\S+\s+суду)?\s*:?(.{0,450})', h)
    if m:
        names = NAME.findall(m.group(1).split('розглянув')[0].split('за участю')[0].split('секретар')[0])
        if 1 <= len(names) <= 3:
            return 'колегія'
    return None


def fetch_heads(ids, limit, max_minutes=None, threads=2):
    """Шапки рішень (склад суду, № провадження). Пишуться рядок за рядком — переривання безпечне."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    heads = load_heads()
    todo = [i for i in ids if i not in heads][:limit]
    log('шапки рішень: є', len(heads), 'дозбираю', len(todo), 'потоків', threads)
    lock, t0, stop = threading.Lock(), time.time(), threading.Event()
    done = [0]
    f = open(DOCS, 'a', encoding='utf-8')

    def one(i):
        if stop.is_set():
            return
        if max_minutes and time.time() - t0 > max_minutes * 60:
            stop.set()
            return
        try:
            d = req(f'/document/{i}', tries=2)
        except RuntimeError:
            return
        txt = ''
        if d.get('fullText'):
            raw = gzip.decompress(base64.b64decode(d['fullText'])).decode('utf-8', 'replace')
            txt = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', raw))).strip()
        m = re.search(r'провадження\s*№\s*([0-9A-Za-zА-Яа-яіїєґ\-/ ]{3,25}?)(?=\s+[А-ЯІЇЄҐ]|\s*$)', txt[:1500])
        rec = {'id': i, 'doc_id': d.get('doc_id'), 'sklad': sklad_from_head(txt), 'provadzhennia': m.group(1).strip() if m else None,
               'head': txt[:600]}
        with lock:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
            heads[i] = rec
            done[0] += 1
            if done[0] % 500 == 0:
                log('  ', done[0], f'{time.time() - t0:.0f} c')
        time.sleep(PAUSE / 2)

    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    f.close()
    log('  зібрано', done[0], 'за', f'{time.time() - t0:.0f} c' + (' (ліміт часу)' if stop.is_set() else ''))
    return heads


# ---------- нормалізація ----------

def load_palaty():
    """Переліки ОП / палат / зразкових справ КАС і КГС з supreme.court.gov.ua (scripts/palaty_supreme.py)."""
    p = os.path.join(DATA, 'palaty_supreme.csv')
    exact, zr = {}, set()
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                for c in filter(None, r['spravy'].split('; ')):
                    c = re.sub(r'\s', '', c).lower()
                    if r['vyd'] == 'зразкова справа':
                        zr.add(c)
                    elif r['data']:
                        exact[(c, r['data'])] = r['vyd']
    return exact, zr


def build(raw, heads):
    cats = {c['id']: c for c in raw['categories']}
    pal_exact, pal_zr = load_palaty()

    def path(cid):
        p, n = [], 0
        while cid in cats and n < 15:
            p.append(cats[cid]['title'].strip())
            cid = cats[cid]['parentId']
            n += 1
        return list(reversed(p))

    def anc(cid):
        s, n = set(), 0
        while cid and n < 15:
            s.add(cid)
            cid = cats.get(cid, {}).get('parentId')
            n += 1
        return s

    dmeta = {d['id']: d for d in raw.get('documents', [])}
    root_court = {'Велика Палата': 'Велика Палата', 'Касаційний адміністративний суд': 'КАС', 'Касаційний господарський суд': 'КГС',
                  'Касаційний кримінальний суд': 'ККС', 'Касаційний цивільний суд': 'КЦС'}
    rows = []
    for r in raw['positions']:
        text = plain(r.get('text'))
        title = (r.get('title') or '').strip()
        cat_ids = [c['id'] for c in r.get('categories', [])]
        a = set().union(*[anc(c) for c in cat_ids]) if cat_ids else set()
        docs = []
        for d0 in r.get('documents', []):
            d = {**d0, **{k: v for k, v in dmeta.get(d0['id'], {}).items() if v is not None}}
            cc = d.get('court_id')
            code = COURT_BY_LEGACY.get(cc, str(cc) if cc else None)
            h = heads.get(d['id'], {})
            key = (re.sub(r'\s', '', d.get('caseNumber') or '').lower(), ddate(d))
            sk = sklad_from_head(h['head']) if h.get('head') else None
            sk_src = 'шапка рішення' if sk else None
            if not sk and key in pal_exact:
                sk, sk_src = {'ОП': 'ОП', 'палата': 'палата'}[pal_exact[key]], 'supreme.court.gov.ua'
            docs.append({'id': d['id'], 'doc_id': d.get('doc_id'), 'sprava': d.get('caseNumber'),
                         'data': ddate(d), 'zrazkova': key[0] in pal_zr and (COURT_NAME.get(code) in ('КАС', 'Велика Палата') or sk == 'ВП'),
                         'sud': COURT_NAME.get(code, code), 'sklad': sk, 'sklad_dzherelo': sk_src, 'provadzhennia': h.get('provadzhennia') or prov_from_head(h.get('head') or ''),
                         'edrsr': f"https://reyestr.court.gov.ua/Review/{d.get('doc_id')}" if d.get('doc_id') else None})
        tag = (r.get('tag') or {}).get('title')
        blob = title + ' ' + text
        # рівень
        sklady = {d['sklad'] for d in docs if d['sklad']}
        if a & CAT_ZRAZKOVI or re.match(r'\s*Зразков\w+ справ', title) or any(d['zrazkova'] for d in docs):
            rank = 1
        elif tag == 'Велика Палата' or 'ВП' in sklady or any(d['sud'] == 'Велика Палата' for d in docs):
            rank = 2
        elif a & CAT_OP or 'ОП' in sklady:
            rank = 3
        elif a & CAT_PALATA or 'палата' in sklady:
            rank = 4
        elif a & CAT_OP_OR_PALATA and not sklady:
            rank = 3 if re.search(r"об.{0,3}єднан\w*\s+палат|\bОП\s+ККС", blob, re.I) else 4
        else:
            rank = 5
        if rank == 5 and re.search(r"(?:у\s+складі|постанов\w*)\s+(?:ОП|об.{0,3}єднан\w*\s+палати)\s+К[ЦГАК]С", blob[:600]) and not sklady:
            rank = 3
        paths = [path(c) for c in cat_ids]
        sud = tag or next((d['sud'] for d in docs if d['sud']), None) or next((root_court.get(p[0]) for p in paths if p and p[0] in root_court), None)
        riven_nazva = RANKS[rank]
        if rank == 4 and a & CAT_OP_OR_PALATA and not sklady:
            riven_nazva = 'Палата або ОП (ККС, уточнити за рішенням)'
        rows.append({
            'id': r['id'], 'link': f"{SITE}/legal-position/{r['id']}", 'riven': rank, 'riven_nazva': riven_nazva,
            'sud': sud, 'nazva': title, 'tekst': text,
            'poznachka': MARK.get(r.get('mark')), 'rubryky': [' / '.join(p) for p in paths], 'rubryky_id': cat_ids,
            'rishennia': docs, 'data_rishennia': max([d['data'] for d in docs if d['data']], default=None),
            'opublikovano': (r.get('approvedAt') or r.get('createdAt') or '')[:10],
            'stvoreno': (r.get('createdAt') or '')[:10], 'zmineno': (r.get('updatedAt') or '')[:19],
        })
    rows.sort(key=lambda x: (x['riven'], -(int((x['data_rishennia'] or '0000').replace('-', '')[:8] or 0)), -x['id']))
    return rows, cats, path


# ---------- відступи ----------

CASE_RE = re.compile(r'справ[іиа]\s*№\s*([0-9]{1,4}/[0-9]{1,7}/[0-9]{2}(?:-[а-яa-z]{1,3})?)')


def vidstupy(rows):
    by_case = collections.defaultdict(list)
    for r in rows:
        for d in r['rishennia']:
            if d['sprava']:
                by_case[d['sprava'].replace(' ', '')].append(r['id'])
    out = []
    for r in rows:
        t = r['tekst']
        m = re.search(r'відступ\w*', t, re.I)
        if not r['poznachka'] and not m:
            continue
        frag = t[max(0, m.start() - 60):m.start() + 600] if m else ''
        cases = list(dict.fromkeys(CASE_RE.findall(frag)))
        own = {d['sprava'] for d in r['rishennia']}
        linked = sorted({i for c in cases if c not in own for i in by_case.get(c, []) if i != r['id']})
        out.append({'id': r['id'], 'riven': r['riven_nazva'], 'sud': r['sud'], 'poznachka': r['poznachka'] or '(у тексті є «відступ»)',
                    'nazva': r['nazva'], 'spravy_u_frahmenti': '; '.join(cases), 'pozytsii_bazy_za_tsymy_spravamy': '; '.join(map(str, linked)),
                    'frahment': re.sub(r'\s+', ' ', frag)[:700], 'link': r['link']})
    return out


# ---------- запис ----------

def write_csv(path, rows, fields):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def md_list(rows, title, intro, group_key):
    out = [f'# {title}', '', intro, '']
    groups = collections.OrderedDict()
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)
    for g, items in sorted(groups.items(), key=lambda x: x[0]):
        out += [f'## {g} ({len(items)})', '']
        for r in items:
            d = r['rishennia'][0] if r['rishennia'] else {}
            req_ = f"{d.get('sud') or ''} {d.get('data') or ''}, № {d.get('sprava') or '—'}".strip()
            mk = f" **[{r['poznachka']}]**" if r['poznachka'] else ''
            more = f" (+{len(r['rishennia']) - 1})" if len(r['rishennia']) > 1 else ''
            out.append(f"- [{r['nazva'] or '(без назви)'}]({r['link']}) — {req_}{more}{mk} `#{r['id']}`")
        out.append('')
    return '\n'.join(out)


def top_rubric(r, depth=2):
    if not r['rubryky']:
        return 'Без рубрики'
    p = r['rubryky'][0].split(' / ')
    return ' / '.join(p[:depth])


def write_all(raw, rows, cats, path):
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(VIEWS, exist_ok=True)
    with open(os.path.join(DATA, 'pozytsii.jsonl'), 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    flat = []
    for r in rows:
        d = r['rishennia'][0] if r['rishennia'] else {}
        flat.append({**{k: r[k] for k in ('id', 'riven', 'riven_nazva', 'sud', 'nazva', 'poznachka', 'data_rishennia', 'opublikovano', 'link', 'tekst')},
                     'sprava': d.get('sprava'), 'sklad': d.get('sklad'), 'edrsr': d.get('edrsr'),
                     'inshi_rishennia': len(r['rishennia']) - 1 if r['rishennia'] else 0, 'rubryka': r['rubryky'][0] if r['rubryky'] else ''})
    write_csv(os.path.join(DATA, 'pozytsii.csv'), flat, ['id', 'riven', 'riven_nazva', 'sud', 'nazva', 'poznachka', 'data_rishennia', 'sprava', 'sklad',
                                                        'inshi_rishennia', 'rubryka', 'opublikovano', 'link', 'edrsr', 'tekst'])
    # рішення
    docs = {}
    for r in rows:
        for d in r['rishennia']:
            x = docs.setdefault(d['id'], {**d, 'pozytsii': []})
            x['pozytsii'].append(r['id'])
    write_csv(os.path.join(DATA, 'rishennia.csv'), sorted(docs.values(), key=lambda x: x['data'] or '', reverse=True),
              ['id', 'doc_id', 'sprava', 'data', 'sud', 'sklad', 'sklad_dzherelo', 'zrazkova', 'provadzhennia', 'edrsr', 'pozytsii'])
    # рубрикатор
    cnt = collections.Counter(c for r in rows for c in r['rubryky_id'])
    cat_rows = [{'id': c['id'], 'parentId': c['parentId'], 'nazva': c['title'].strip(), 'shliakh': ' / '.join(path(c['id'])), 'pozytsii_bezposerednio': cnt.get(c['id'], 0)}
                for c in cats.values()]
    write_csv(os.path.join(DATA, 'rubryky.csv'), sorted(cat_rows, key=lambda x: x['shliakh']), ['id', 'parentId', 'nazva', 'shliakh', 'pozytsii_bezposerednio'])
    write_csv(os.path.join(DATA, 'yespl.csv'), raw['echr'], ['id', 'case_num', 'title', 'description', 'decided_date', 'doc_url'])
    # звірка переліків supreme.court.gov.ua з базою
    pp = os.path.join(DATA, 'palaty_supreme.csv')
    if os.path.exists(pp):
        by_case = collections.defaultdict(list)
        for r in rows:
            for d in r['rishennia']:
                by_case[re.sub(r'\s', '', d['sprava'] or '').lower()].append((r, d))
        zv = []
        with open(pp, encoding='utf-8-sig') as f:
            for x in csv.DictReader(f):
                hits = [(r, d) for c in filter(None, x['spravy'].split('; ')) for (r, d) in by_case.get(re.sub(r'\s', '', c).lower(), [])]
                same = [(r, d) for r, d in hits if d['data'] == x['data']] if x['vyd'] != 'зразкова справа' else hits
                zv.append({**x, 'u_bazi': 'так' if same else ('лише № справи' if hits else 'ні'),
                           'pozytsii': '; '.join(sorted({str(r['id']) for r, d in same}))})
        write_csv(os.path.join(DATA, 'palaty_supreme_zvirka.csv'), zv, list(zv[0].keys()))
    v = vidstupy(rows)
    write_csv(os.path.join(DATA, 'vidstupy.csv'), v, ['id', 'riven', 'sud', 'poznachka', 'nazva', 'spravy_u_frahmenti', 'pozytsii_bazy_za_tsymy_spravamy', 'frahment', 'link'])
    # покажчики за пріоритетом
    by = collections.defaultdict(list)
    for r in rows:
        by[r['riven']].append(r)
    intro = ('Згенеровано скриптом `scripts/lpd_sync.py`. Пункт: назва позиції (посилання на lpd.court.gov.ua) — суд, дата і номер справи '
             'основного рішення; `#id` — номер позиції в базі. Позначки сайту: «З відступом» — нова позиція з відступом від попередньої практики; '
             '«Змінено» — від цієї позиції вже відступлено.')
    open(os.path.join(VIEWS, '1_zrazkovi_spravy.md'), 'w').write(md_list(by[1], 'Зразкові справи', intro, lambda r: r['sud'] or '—'))
    open(os.path.join(VIEWS, '2_velyka_palata.md'), 'w').write(md_list(by[2], 'Велика Палата Верховного Суду', intro, lambda r: top_rubric(r, 2)))
    open(os.path.join(VIEWS, '3_obiednani_palaty.md'), 'w').write(md_list(by[3], "Об'єднані палати касаційних судів", intro, lambda r: f"{r['sud']} — {top_rubric(r, 2)}"))
    open(os.path.join(VIEWS, '4_palaty.md'), 'w').write(md_list(by[4], 'Судові палати касаційних судів', intro, lambda r: f"{r['sud']} — {top_rubric(r, 2)}"))
    for sud in ('КАС', 'КГС', 'ККС', 'КЦС'):
        items = [r for r in by[5] if r['sud'] == sud]
        open(os.path.join(VIEWS, f'5_kolehii_{sud}.md'), 'w').write(md_list(items, f'{sud}: колегії суддів', intro, lambda r: top_rubric(r, 3)))
    rest = [r for r in by[5] if r['sud'] not in ('КАС', 'КГС', 'ККС', 'КЦС')]
    if rest:
        open(os.path.join(VIEWS, '5_kolehii_inshi.md'), 'w').write(md_list(rest, 'Колегії: суд не визначено', intro, lambda r: top_rubric(r, 2)))
    mk = [r for r in rows if r['poznachka']]
    open(os.path.join(VIEWS, '6_vidstupy.md'), 'w').write(md_list(mk, 'Позиції з позначками «З відступом» і «Змінено»', intro, lambda r: f"{r['riven']}. {r['riven_nazva']} — {r['poznachka']}"))
    stats = {'onovleno': dt.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M'), 'pozytsii': len(rows),
             'za_rivnem': {RANKS[k]: len(v) for k, v in sorted(by.items())},
             'za_sudom': dict(collections.Counter(r['sud'] for r in rows).most_common()),
             'poznachky': dict(collections.Counter(r['poznachka'] for r in rows if r['poznachka'])),
             'rishennia': len(docs), 'rishennia_zi_skladom': sum(1 for d in docs.values() if d['sklad']),
             'yespl': len(raw['echr']), 'dajdzhesty': len(raw['digests'])}
    json.dump(stats, open(os.path.join(DATA, 'statystyka.json'), 'w'), ensure_ascii=False, indent=1)
    return stats


# ---------- журнал змін ----------

def diff(rows):
    os.makedirs(CHANGES, exist_ok=True)
    snap = os.path.join(CACHE, 'snapshot_prev.json.gz')
    cur = {r['id']: {'z': r['zmineno'], 'p': r['poznachka'], 'n': r['nazva']} for r in rows}
    if not os.path.exists(snap):
        with gzip.open(snap, 'wt') as f:
            json.dump(cur, f)
        return None
    with gzip.open(snap, 'rt') as f:
        prev = {int(k): v for k, v in json.load(f).items()}
    new = [i for i in cur if i not in prev]
    gone = [i for i in prev if i not in cur]
    changed = [i for i in cur if i in prev and cur[i]['z'] != prev[i]['z']]
    marks = [i for i in changed if cur[i]['p'] != prev[i]['p']]
    today = dt.datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat()
    rec = {'data': today, 'novi': new, 'zmineni': changed, 'zmina_poznachky': marks, 'zniknuli': gone}
    if new or gone or changed:
        fn = os.path.join(CHANGES, f'{today}.json')
        if os.path.exists(fn):          # кілька запусків за день — об'єднати, а не перезаписати
            old = json.load(open(fn))
            for k in ('novi', 'zmineni', 'zmina_poznachky', 'zniknuli'):
                rec[k] = sorted(set(old.get(k, [])) | set(rec[k]))
            back = set(rec['novi']) & set(rec['zniknuli'])      # зникла й повернулася того самого дня
            rec['novi'] = [i for i in rec['novi'] if i not in back]
            rec['zniknuli'] = [i for i in rec['zniknuli'] if i not in back]
        json.dump(rec, open(fn, 'w'), ensure_ascii=False, indent=1)
        with open(os.path.join(CHANGES, 'ZHURNAL.md'), 'a') as f:
            f.write(f'- {today}: нових {len(new)}, змінених {len(changed)} (з них змінено позначку {len(marks)}), зникли {len(gone)}\n')
    with gzip.open(snap, 'wt') as f:
        json.dump(cur, f)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--docs', type=int, default=0, help='скільки шапок рішень дозібрати')
    ap.add_argument('--docs-minutes', type=float, default=None, help='обмеження часу на шапки, хв')
    ap.add_argument('--docs-threads', type=int, default=2, help='паралельних запитів (не більше 3)')
    a = ap.parse_args()
    raw = load_cached() if a.offline else fetch_all()
    if a.docs:
        rows0, _, _ = build(raw, load_heads())     # спочатку рішення зразкових, ВП, ОП, палат; далі новіші
        ids = list(dict.fromkeys(d['id'] for r in sorted(rows0, key=lambda x: (x['riven'] if x['riven'] != 2 else 9, -(x['id']))) for d in r['rishennia']))
        heads = fetch_heads(ids, a.docs, a.docs_minutes, min(max(a.docs_threads, 1), 3))
    else:
        heads = load_heads()
    rows, cats, path = build(raw, heads)
    stats = write_all(raw, rows, cats, path)
    ch = diff(rows)
    print(json.dumps({'statystyka': stats, 'zminy': {k: (len(v) if isinstance(v, list) else v) for k, v in (ch or {}).items()}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
