#!/usr/bin/env python3
"""Дзеркало дайджестів на supreme.court.gov.ua: звірка з каталогом lpd, дати публікації, доступність файлів.

Автор: В'ячеслав Плескач

Джерела (звичайний HTML, windows-1251, браузер не потрібен):
  • «Аналіз судової практики» — дерево груп із посиланнями на всі PDF:
    https://supreme.court.gov.ua/supreme/pokazniki-diyalnosti/analiz/
  • «Інформація про опубліковані дайджести та огляди» — анонси з датою публікації (?page=N):
    https://supreme.court.gov.ua/supreme/pres-centr/info_anons_daidgest_oglyad/

  python3 scripts/dzerkalo_supreme.py              # нові анонси + звірка
  python3 scripts/dzerkalo_supreme.py --all        # усі сторінки анонсів
  python3 scripts/dzerkalo_supreme.py --check      # + перевірити доступність кожного PDF (HEAD)

Результат: dajdzhesty/dzerkalo.csv, dajdzhesty/dodatkovi_fajly_supreme.csv, cache/anons.json.
"""
import argparse, csv, html, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'https://supreme.court.gov.ua'
ANALIZ = BASE + '/supreme/pokazniki-diyalnosti/analiz/'
ANONS = BASE + '/supreme/pres-centr/info_anons_daidgest_oglyad/'
UA = {'User-Agent': 'Mozilla/5.0 (case-law-supreme-court mirror check)'}
ACACHE = os.path.join(ROOT, 'cache', 'anons.json')


def get(url, method='GET', timeout=60):
    u = urllib.parse.quote(url, safe=':/?=&%#')
    r = urllib.request.Request(u, headers=UA, method=method)
    return urllib.request.urlopen(r, timeout=timeout)


def page(url):
    for t in range(3):
        try:
            return get(url).read().decode('cp1251', 'replace')
        except Exception as e:
            print('  помилка', url, e, file=sys.stderr)
            time.sleep(3 * (t + 1))
    raise RuntimeError(url)


def norm(u):
    return re.sub(r'^https?://(www\.)?', '', urllib.parse.unquote(u).lower().split('?')[0])


def fname(u):
    return norm(u).rsplit('/', 1)[-1]


class Tree(HTMLParser):
    """Дерево «Аналіз судової практики»: групи (documents__container-group) і документи (a.documents__container)."""

    def __init__(self):
        super().__init__()
        self.stack, self.path, self.out, self.cap, self.buf, self.href = [], [], [], False, '', None

    def handle_starttag(self, tag, a):
        a = dict(a)
        cls = a.get('class') or ''
        if tag in ('div', 'ul', 'li', 'span', 'a'):
            self.stack.append(cls)
        if tag == 'a' and 'documents__container' in cls:
            self.href = a.get('href')
        if tag == 'span' and cls == 'documents__title':
            self.cap, self.buf = True, ''

    def handle_endtag(self, tag):
        if tag == 'span' and self.cap:
            self.cap = False
            txt = re.sub(r'\s+', ' ', html.unescape(self.buf)).strip()
            if self.href:
                self.out.append({'shliakh': [p for _, p in self.path], 'nazva': txt, 'url': urllib.parse.urljoin(BASE, self.href.strip())})
                self.href = None
            else:
                d = sum(1 for c in self.stack if 'documents__documents' in c)
                self.path = [x for x in self.path if x[0] < d] + [(d, txt)]
        if tag in ('div', 'ul', 'li', 'span', 'a') and self.stack:
            self.stack.pop()

    def handle_data(self, d):
        if self.cap:
            self.buf += d


def analiz_tree():
    t = page(ANALIZ)
    p = Tree()
    p.feed(t[t.find('<ul class="documents">'):])
    return p.out


def anons(all_pages=False):
    known = json.load(open(ACACHE, encoding='utf-8')) if os.path.exists(ACACHE) else []
    seen = {a['nid'] for a in known}
    new, n = [], 1
    while True:
        t = page(ANONS + (f'?page={n}' if n > 1 else ''))
        items = [{'url': BASE + m.group(1), 'nid': m.group(2), 'nazva': re.sub(r'\s+', ' ', html.unescape(m.group(3))).strip(), 'data': m.group(4).strip()}
                 for m in re.finditer(r'href="(/supreme/pres-centr/info_anons_daidgest_oglyad/(\d+)/)".*?news__title">(.*?)</h4>.*?news_date">([^<]+)', t, re.S)]
        fresh = [a for a in items if a['nid'] not in seen]
        new += fresh
        last = re.search(r'\?page=(\d+)>Остання', t)
        if not items or (not all_pages and len(fresh) < len(items)) or (last and n >= int(last.group(1))) or (not last and n > 1):
            break
        n += 1
        time.sleep(0.5)

    def pdfs(a):
        try:
            h = page(a['url'])
            a['pdf'] = [urllib.parse.urljoin(a['url'], x) for x in re.findall(r'href="([^"]+)"', h) if re.search(r'\.(pdf|docx?)(\?|$)', x, re.I)]
        except RuntimeError:
            a['pdf'] = []
        return a
    with ThreadPoolExecutor(3) as ex:
        new = list(ex.map(pdfs, new))
    allx = new + known
    os.makedirs(os.path.dirname(ACACHE), exist_ok=True)
    json.dump(allx, open(ACACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    return allx, len(new)


MONTHS = {'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4, 'травня': 5, 'червня': 6, 'липня': 7, 'серпня': 8, 'вересня': 9, 'жовтня': 10, 'листопада': 11, 'грудня': 12}


def iso(d):
    m = re.match(r'(\d{1,2})\s+(\S+)\s+(\d{4})', d or '')
    return f'{m.group(3)}-{MONTHS.get(m.group(2), 0):02d}-{int(m.group(1)):02d}' if m else ''


def head(u):
    try:
        with get(u, 'HEAD') as r:
            return r.status, int(r.headers.get('Content-Length') or -1)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 'помилка: ' + str(e)[:40], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    cat = json.load(open(os.path.join(ROOT, 'dajdzhesty', 'katalog.json'), encoding='utf-8'))
    tree = analiz_tree()
    an, n_new = anons(a.all)
    t_by_file = {fname(x['url']): x for x in tree}
    an_by_file = {}
    for x in an:
        for u in x.get('pdf', []):
            an_by_file.setdefault(fname(u), x)
    rows, used = [], set()
    for it in cat:
        f = fname(it['dzherelo']) if it.get('dzherelo') else None
        t = t_by_file.get(f) if f else None
        z = an_by_file.get(f) if f else None
        if f:
            used.add(f)
        rows.append({'id': it['id'], 'sud': it['sud'], 'typ': it['typ'], 'nazva': it['nazva'], 'lpd_pdf': it['pdf'],
                     'dzerkalo_pdf': t['url'] if t else (it.get('dzherelo') or ''), 'na_storintsi_analiz': 'так' if t else 'ні',
                     'rozdil_analiz': ' / '.join(t['shliakh']) if t else '', 'data_publikatsii': iso(z['data']) if z else '',
                     'anons': z['url'] if z else '', 'dostupnist': '', 'rozmir': ''})
    if a.check:
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda r: head(r['dzerkalo_pdf']) if r['dzerkalo_pdf'] else ('немає', None), rows))
        for r, (s, l) in zip(rows, res):
            r['dostupnist'], r['rozmir'] = s, l if l is not None else ''
    out = os.path.join(ROOT, 'dajdzhesty', 'dzerkalo.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    extra = []
    for x in tree:
        if fname(x['url']) not in used:
            extra.append({'dzherelo': 'Аналіз судової практики', 'nazva': x['nazva'], 'rozdil': ' / '.join(x['shliakh']), 'data_publikatsii': '', 'pdf': x['url']})
    for x in an:
        for u in x.get('pdf', []):
            if fname(u) not in used and fname(u) not in t_by_file:
                extra.append({'dzherelo': 'анонс', 'nazva': x['nazva'], 'rozdil': '', 'data_publikatsii': iso(x['data']), 'pdf': u})
    with open(os.path.join(ROOT, 'dajdzhesty', 'dodatkovi_fajly_supreme.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, ['dzherelo', 'nazva', 'rozdil', 'data_publikatsii', 'pdf'])
        w.writeheader()
        w.writerows(extra)
    st = {'u_katalozi_lpd': len(cat), 'na_storintsi_analiz': len(tree), 'zbig_z_lpd': sum(1 for r in rows if r['na_storintsi_analiz'] == 'так'),
          'lyshe_v_lpd': [r['nazva'] for r in rows if r['na_storintsi_analiz'] == 'ні'][:30], 'anonsiv': len(an), 'novykh_anonsiv': n_new,
          'datovano': sum(1 for r in rows if r['data_publikatsii']), 'dodatkovykh_fajliv': len(extra)}
    if a.check:
        st['dostupni_200'] = sum(1 for r in rows if r['dostupnist'] == 200)
    print(json.dumps(st, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
