#!/usr/bin/env python3
"""Дайджести й огляди ВС з lpd.court.gov.ua: завантаження, зміст, тематичний каталог.

Автор: В'ячеслав Плескач

  python3 scripts/digest_sync.py                 # нові PDF + перебудова каталогу
  python3 scripts/digest_sync.py --offline       # лише перебудувати каталог з кешу
  python3 scripts/digest_sync.py --pdf-dir DIR   # взяти вже завантажені PDF з DIR

Потребує: pdftotext (poppler-utils), pypdf (необов'язково — закладки PDF).
Спершу запустити scripts/lpd_sync.py: він кешує перелік дайджестів і дерево навігації.
"""
import argparse, collections, csv, gzip, json, os, re, shutil, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest_parse as P

API = 'https://lpd-api-prod.court.gov.ua/api/v1'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'cache')
PDF = os.path.join(CACHE, 'pdf')
OUT = os.path.join(ROOT, 'dajdzhesty')
PARSED = os.path.join(CACHE, 'digest_parsed')

MONTHS = {'січ': 1, 'лют': 2, 'бер': 3, 'квіт': 4, 'трав': 5, 'черв': 6, 'лип': 7, 'серп': 8, 'верес': 9, 'жовт': 10, 'листоп': 11, 'груд': 12}
COURT_ORDER = ['Велика Палата', 'КАС', 'КГС', 'ККС', 'КЦС', 'ЄСПЛ', 'Суд ЄС']
SLUG = {'Велика Палата': 'VP', 'КАС': 'KAS', 'КГС': 'KGS', 'ККС': 'KKS', 'КЦС': 'KCS', 'ЄСПЛ': 'YESPL', 'Суд ЄС': 'SUD_YES'}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_raw():
    with gzip.open(os.path.join(CACHE, 'raw_latest.json.gz'), 'rt', encoding='utf-8') as f:
        return json.load(f)


def mirror_urls():
    """Резервні адреси PDF на supreme.court.gov.ua (з dajdzhesty/dzerkalo.csv або з поля externalUrl)."""
    p = os.path.join(OUT, 'dzerkalo.csv')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8-sig') as f:
        return {r['id']: r for r in csv.DictReader(f)}


def download(ids, pdf_dir=None, ext=None):
    os.makedirs(PDF, exist_ok=True)
    for n, i in enumerate(ids, 1):
        dst = os.path.join(PDF, f'{i}.pdf')
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            continue
        if pdf_dir and os.path.exists(os.path.join(pdf_dir, f'{i}.pdf')):
            shutil.copy(os.path.join(pdf_dir, f'{i}.pdf'), dst)
            continue
        srcs = [f'{API}/digest/file/{i}'] + ([ext[i]] if ext and ext.get(i) else [])
        for t in range(4):
            src = srcs[min(t // 2, len(srcs) - 1)]          # дві спроби з lpd, далі — дзеркало supreme.court.gov.ua
            try:
                q = urllib.request.Request(urllib.parse.quote(src, safe=':/?=&%'), headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(q, timeout=300) as r, open(dst + '.part', 'wb') as f:
                    shutil.copyfileobj(r, f)
                os.replace(dst + '.part', dst)
                if src != srcs[0]:
                    log('  pdf із дзеркала', i)
                break
            except Exception as e:
                log('  pdf', i, src, e)
                time.sleep(5 * (t + 1))
        time.sleep(0.5)
        if n % 50 == 0:
            log('  pdf', n, '/', len(ids))


def period(title):
    t = title.lower()
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s*[–-]\s*(\d{2})\.(\d{2})\.(\d{4})', t)
    if m:
        return int(m.group(6)), int(m.group(5))
    m = re.search(r'за\s+([а-яії]+)\s+(\d{4})', t) or re.search(r'\(([а-яії]+)\s+(\d{4})', t)
    if m:
        for k, v in MONTHS.items():
            if m.group(1).startswith(k):
                return int(m.group(2)), v
    m = re.search(r'(?:за|у)\s+(\d{4})\s+р', t) or re.search(r'(\d{4})\s+р[іо]к', t)
    if m:
        return int(m.group(1)), None
    ys = re.findall(r'(20\d{2})', t)
    return (int(ys[-1]), None) if ys else (None, None)


def nav_paths(nav):
    m = collections.defaultdict(list)

    def walk(n, path):
        for x in n:
            p = path + [x['title'].strip()]
            for i in x.get('digestIds', []):
                m[i].append(p)
            walk(x.get('children', []), p)
    walk(nav['navigation'], [])
    return m


def parse_all(digests):
    os.makedirs(PARSED, exist_ok=True)
    os.makedirs(os.path.join(OUT, 'tekst'), exist_ok=True)
    res = {}
    for n, d in enumerate(digests, 1):
        i = d['digestId']
        cache = os.path.join(PARSED, f'{i}.json')
        pdf = os.path.join(PDF, f'{i}.pdf')
        if os.path.exists(cache) and (not os.path.exists(pdf) or os.path.getmtime(cache) >= os.path.getmtime(pdf)):
            res[i] = json.load(open(cache))
            continue
        if not os.path.exists(pdf):
            continue
        r = P.parse(pdf, d['typeLabel'])
        with gzip.open(os.path.join(OUT, 'tekst', f'{i}.txt.gz'), 'wt', encoding='utf-8') as f:
            f.write(r.pop('text'))
        json.dump(r, open(cache, 'w'), ensure_ascii=False)
        res[i] = r
        if n % 50 == 0:
            log('  розібрано', n)
    return res


def lp_index():
    by_doc, by_case = collections.defaultdict(list), collections.defaultdict(list)
    p = os.path.join(ROOT, 'data', 'pozytsii.jsonl')
    if os.path.exists(p):
        for l in open(p, encoding='utf-8'):
            r = json.loads(l)
            for d in r['rishennia']:
                if d.get('doc_id'):
                    by_doc[str(d['doc_id'])].append(r)
                if d.get('sprava'):
                    by_case[d['sprava'].replace(' ', '')].append(r)
    return by_doc, by_case


def esc(s):
    return s.replace('|', '/').replace('\n', ' ')


def build(raw, parsed):
    nav = nav_paths(raw['digest_nav'])
    by_doc, by_case = lp_index()
    mir = mirror_urls()
    items = []
    for d in raw['digests']:
        i = d['digestId']
        court, kind = d['typeLabel'].split(' • ')[:2]
        p = parsed.get(i, {})
        y, mth = period(d['title'])
        cases = p.get('cases', [])
        revs = p.get('edrsr_doc_ids', [])
        lps = {}
        for x in revs:
            for r in by_doc.get(x, []):
                lps[r['id']] = r
        for c in cases:
            for r in by_case.get(c, []):
                lps[r['id']] = r
        items.append({'id': i, 'nazva': d['title'].strip(), 'sud': court, 'typ': 'Тематичний' if kind.startswith('Темат') else 'Періодичний',
                      'rik': y, 'misiats': mth, 'storinok': p.get('pages') or int(re.sub(r'\D', '', d.get('pageLabel', '0')) or 0),
                      'temy_saitu': [' / '.join(x) for x in nav.get(i, [])], 'pdf': f'{API}/digest/file/{i}', 'dzherelo': d.get('externalUrl'),
                      'zmist_metod': p.get('toc_method'), 'zmist': p.get('toc', []), 'spravy': cases, 'edrsr': revs,
                      'pozytsii_bazy': sorted(lps), 'opublikovano': (mir.get(i) or {}).get('data_publikatsii') or ''})
    return items, by_doc


def toc_lines(it, maxlvl=None, limit=None):
    out = []
    for e in it['zmist']:
        if maxlvl is not None and e.get('lvl') is not None and e['lvl'] > maxlvl:
            continue
        ind = '  ' * max((e.get('lvl') or 1) - 1, 0)
        pg = f" — с. {e['p']}" if e.get('p') else ''
        out.append(f"{ind}- {esc(e['t'])}{pg}")
        if limit and len(out) >= limit:
            out.append(f"{ind}- … (повний зміст — у файлі змісту)")
            break
    return out


def write(items, by_doc):
    os.makedirs(os.path.join(OUT, 'zmist'), exist_ok=True)
    os.makedirs(os.path.join(OUT, 'tematychni'), exist_ok=True)
    os.makedirs(os.path.join(OUT, 'periodychni'), exist_ok=True)
    pos_title = {}
    for lst in by_doc.values():
        for r in lst:
            pos_title[r['id']] = r
    # 1) зміст кожного дайджесту
    for it in items:
        L = [f"# {it['nazva']}", '', f"- Суд / тип: {it['sud']}, {it['typ'].lower()} ({it['storinok']} с.)" + (f"; оприлюднено {it['opublikovano']}" if it['opublikovano'] else ''),
             f"- PDF: {it['pdf']}" + (f" · джерело: {it['dzherelo']}" if it['dzherelo'] else ''),
             f"- Теми на сайті: {'; '.join(it['temy_saitu']) or '—'}", f"- Текст: `dajdzhesty/tekst/{it['id']}.txt.gz` (сторінки розділені символом \\f)", '',
             '## Зміст', '']
        L += toc_lines(it) or ['_Зміст автоматично не виділено — див. текст._']
        if it['pozytsii_bazy']:
            L += ['', f"## Позиції бази, рішення яких процитовано в дайджесті ({len(it['pozytsii_bazy'])})", '']
            for pid in it['pozytsii_bazy']:
                r = pos_title.get(pid)
                if r:
                    L.append(f"- [{esc(r['nazva'])}]({r['link']}) — {r['riven_nazva']}, {r['sud']} `#{pid}`")
        if it['spravy']:
            L += ['', f"## Справи, згадані в тексті ({len(it['spravy'])})", '', ', '.join(it['spravy'])]
        open(os.path.join(OUT, 'zmist', f"{it['id']}.md"), 'w').write('\n'.join(L) + '\n')
    # 2) зведені таблиці
    flat = []
    for it in items:
        for e in it['zmist']:
            flat.append({'id': it['id'], 'sud': it['sud'], 'typ': it['typ'], 'rik': it['rik'] or '', 'storinka': e.get('p') or '', 'riven': e.get('lvl') if e.get('lvl') is not None else '',
                         'punkt': esc(e['t']), 'dajdzhest': esc(it['nazva'])})
    with open(os.path.join(OUT, 'zmist_usi.tsv'), 'w', encoding='utf-8') as f:
        w = csv.DictWriter(f, ['id', 'sud', 'typ', 'rik', 'storinka', 'riven', 'punkt', 'dajdzhest'], delimiter='\t')
        w.writeheader()
        w.writerows(flat)
    with open(os.path.join(OUT, 'katalog.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['id', 'sud', 'typ', 'rik', 'misiats', 'opublikovano', 'storinok', 'nazva', 'temy_saitu', 'punktiv_zmistu', 'zmist_metod', 'sprav', 'pozytsii_bazy', 'pdf', 'dzherelo'])
        for it in items:
            w.writerow([it['id'], it['sud'], it['typ'], it['rik'] or '', it['misiats'] or '', it['opublikovano'], it['storinok'], it['nazva'], '; '.join(it['temy_saitu']),
                        len(it['zmist']), it['zmist_metod'], len(it['spravy']), len(it['pozytsii_bazy']), it['pdf'], it['dzherelo'] or ''])
    json.dump([{k: v for k, v in it.items() if k != 'zmist'} | {'punktiv_zmistu': len(it['zmist'])} for it in items],
              open(os.path.join(OUT, 'katalog.json'), 'w'), ensure_ascii=False)
    # 3) тематичні — за темами сайту
    them = [it for it in items if it['typ'] == 'Тематичний']
    groups = collections.OrderedDict()
    for it in them:
        paths = it['temy_saitu'] or [f"Без рубрики на сайті / {it['sud']}"]
        for p in paths:
            parts = p.split(' / ')
            if parts[0].startswith('Огляди судової практики касаційних'):
                parts = parts[1:]
            parts = [x for x in parts if x not in ('Тематичні огляди', 'Тематичні дайджести')]
            full = {'КАС': 'Касаційний адміністративний суд', 'КГС': 'Касаційний господарський суд', 'ККС': 'Касаційний кримінальний суд',
                    'КЦС': 'Касаційний цивільний суд', 'ЄСПЛ': 'Огляди рішень Європейського суду з прав людини',
                    'Суд ЄС': 'Огляди практики Суду Європейського Союзу', 'Велика Палата': 'Дайджести судової практики Великої Палати Верховного Суду'}
            sec = parts[0] if parts else full.get(it['sud'], it['sud'])
            sub = ' / '.join(parts[1:]) or '—'
            groups.setdefault(sec, collections.OrderedDict()).setdefault(sub, []).append(it)

    def sec_order(s):
        order = ['Дайджести судової практики Великої Палати', 'Міжюрисдикційні', 'Касаційний адміністративний', 'Касаційний господарський',
                 'Касаційний кримінальний', 'Касаційний цивільний', 'Огляди рішень Європейського', 'Огляди практики Суду Європейського', 'Без рубрики']
        return next((k for k, o in enumerate(order) if s.startswith(o)), 99)

    idx = ['# Тематичний каталог дайджестів і оглядів Верховного Суду', '',
           "Автор: В'ячеслав Плескач. Згенеровано `scripts/digest_sync.py` з lpd.court.gov.ua.", '',
           f"Усього: {len(items)} документів — тематичних {len(them)}, періодичних {len(items) - len(them)}.", '',
           'Як шукати:',
           '- за темою — розділи нижче (теми сайту); у кожному розділі — назви дайджестів, далі файл розділу з короткими змістами;',
           '- за конкретним питанням — пошук у `dajdzhesty/zmist_usi.tsv` (один рядок = пункт змісту) або в текстах `dajdzhesty/tekst/*.txt.gz`; скрипт `scripts/poshuk.py`;',
           '- повний зміст і пов\'язані позиції бази — `dajdzhesty/zmist/<id>.md`.', '',
           '## Тематичні дайджести й огляди', '']
    for k, (sec, subs) in enumerate(sorted(groups.items(), key=lambda x: sec_order(x[0])), 1):
        fn = f"{k:02d}_{re.sub(r'[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9]+', '_', sec)[:50].strip('_')}.md"
        n = sum(len(v) for v in subs.values())
        idx += [f'### {sec} ({n})', '', f'Короткий зміст кожного: [tematychni/{fn}](tematychni/{fn})', '']
        S = [f'# {sec}', '', '[← до каталогу](../KATALOG.md)', '']
        for sub, lst in subs.items():
            if sub != '—':
                idx.append(f'**{sub}**')
                S += [f'## {sub}', '']
            for it in lst:
                idx.append(f"- {esc(it['nazva'])} ({it['storinok']} с.{', оприлюднено ' + it['opublikovano'] if it['opublikovano'] else ''}) — [зміст](zmist/{it['id']}.md) · [PDF]({it['dzherelo'] or it['pdf']})")
                S += [f"### {esc(it['nazva'])}", '', f"{it['sud']}, {it['storinok']} с. · [повний зміст](../zmist/{it['id']}.md) · [PDF]({it['dzherelo'] or it['pdf']})"
                      + (f" · позицій бази: {len(it['pozytsii_bazy'])}" if it['pozytsii_bazy'] else ''), '']
                S += toc_lines(it, maxlvl=2, limit=60) or ['_Зміст автоматично не виділено._']
                S.append('')
            idx.append('')
        open(os.path.join(OUT, 'tematychni', fn), 'w').write('\n'.join(S) + '\n')
    # 4) періодичні — за судом і роком
    idx += ['## Періодичні дайджести й огляди', '']
    per = [it for it in items if it['typ'] == 'Періодичний']
    for court in COURT_ORDER:
        lst = sorted([it for it in per if it['sud'] == court], key=lambda x: (x['rik'] or 0, x['misiats'] or 13), reverse=True)
        if not lst:
            continue
        fn = f"{SLUG[court]}.md"
        yrs = collections.Counter(it['rik'] for it in lst)
        idx.append(f"- **{court}** — {len(lst)} ({', '.join(f'{y}: {c}' for y, c in sorted(yrs.items(), key=lambda x: x[0] or 0, reverse=True))}) → [periodychni/{fn}](periodychni/{fn})")
        S = [f'# {court}: періодичні дайджести й огляди', '', '[← до каталогу](../KATALOG.md)', '']
        cur = None
        for it in lst:
            if it['rik'] != cur:
                cur = it['rik']
                S += [f'## {cur or "Рік не визначено"}', '']
            S += [f"### {esc(it['nazva'])}", '', f"{it['storinok']} с. · [повний зміст](../zmist/{it['id']}.md) · [PDF]({it['dzherelo'] or it['pdf']})"
                  + (f" · позицій бази: {len(it['pozytsii_bazy'])}" if it['pozytsii_bazy'] else ''), '']
            S += toc_lines(it, maxlvl=2, limit=60) or ['_Зміст автоматично не виділено._']
            S.append('')
        open(os.path.join(OUT, 'periodychni', fn), 'w').write('\n'.join(S) + '\n')
    open(os.path.join(OUT, 'KATALOG.md'), 'w').write('\n'.join(idx) + '\n')
    st = collections.Counter(it['zmist_metod'] for it in items)
    return {'dokumentiv': len(items), 'tematychnykh': len(them), 'z_vydilenym_zmistom': sum(1 for it in items if len(it['zmist']) >= 2),
            'metody_zmistu': dict(st), 'punktiv_zmistu': len(flat), 'zviazkiv_z_pozytsiiamy': sum(len(it['pozytsii_bazy']) for it in items)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--pdf-dir')
    a = ap.parse_args()
    raw = load_raw()
    ids = [d['digestId'] for d in raw['digests']]
    if not a.offline:      # завантажуємо лише ще не розібрані (PDF у репозиторій не входять)
        ext = {d['digestId']: d.get('externalUrl') for d in raw['digests']}
        ext.update({k: v['dzerkalo_pdf'] for k, v in mirror_urls().items() if v.get('dzerkalo_pdf')})
        download([i for i in ids if not os.path.exists(os.path.join(PARSED, f'{i}.json'))], a.pdf_dir, ext)
    parsed = parse_all(raw['digests'])
    items, by_doc = build(raw, parsed)
    print(json.dumps(write(items, by_doc), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
