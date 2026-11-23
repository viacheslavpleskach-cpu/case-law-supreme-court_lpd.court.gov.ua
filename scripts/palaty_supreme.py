#!/usr/bin/env python3
"""Переліки рішень палат, об'єднаних палат і зразкових справ на supreme.court.gov.ua.

Автор: В'ячеслав Плескач

Сторінки (звичайний HTML, дерево груп як на сторінці «Аналіз судової практики»):
  КАС: /supreme/pro_sud/rishennya_sud_palat/, /rishennya_obedn_palati/, /zrazkova-sprava/
  КГС: /supreme/pro_sud/rishennya_obedn_palati_kgs_vs/, /rishennya_sud_palat_kgs_vs/

  python3 scripts/palaty_supreme.py      → data/palaty_supreme.csv

Рядок: суд, вид (ОП / палата / зразкова справа), розділ (назва палати, рік), вид рішення, дата, № справи,
№ провадження, посилання на сторінку рішення. lpd_sync.py використовує цей файл для визначення рівня позицій.
"""
import csv, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dzerkalo_supreme import Tree, page, BASE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = [('КАС', 'палата', 'rishennya_sud_palat'), ('КАС', 'ОП', 'rishennya_obedn_palati'), ('КАС', 'зразкова справа', 'zrazkova-sprava'),
         ('КГС', 'ОП', 'rishennya_obedn_palati_kgs_vs'), ('КГС', 'палата', 'rishennya_sud_palat_kgs_vs')]
MON = {'січня': 1, 'лютого': 2, 'березня': 3, 'квітня': 4, 'травня': 5, 'червня': 6, 'липня': 7, 'серпня': 8, 'вересня': 9, 'жовтня': 10, 'листопада': 11, 'грудня': 12}
CASE = re.compile(r'№\s*([0-9]{1,4}/[0-9]{1,7}/[0-9]{2}(?:-[а-яa-z]{1,3})?|[0-9]{3}[A-Z]{3,5}/[0-9]+/[0-9]{2})')


def parse_date(t):
    m = re.search(r'від\s+(\d{1,2})\s+([а-яії]+)\s+(\d{4})', t)
    if m and m.group(2) in MON:
        return f'{m.group(3)}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}'
    m = re.search(r'від\s+(\d{2})\.(\d{2})\.(\d{4})', t)
    return f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''


def main():
    rows = []
    for sud, vyd, slug in PAGES:
        url = f'{BASE}/supreme/pro_sud/{slug}/'
        t = page(url)
        p = Tree()
        p.feed(t[t.find('<ul class="documents">'):])
        for x in p.out:
            title = x['nazva']
            cases = [c.rstrip('.') for c in re.findall(r'справ[іиа]\s*№\s*([^\s(,;]+)', title)] + CASE.findall(title)
            cases += re.findall(r'\((?:№\s*)?([0-9]{2,4}/[0-9]{1,7}/[0-9]{2}(?:-[а-яa-z]{1,3})?)\s*\)', title)
            m = re.search(r'провадження\s*№\s*([^)]+)\)', title) or re.search(r'№\s*(Пз/\S+)', title)
            kind = (re.match(r'\s*(Постанова|Ухвала|Рішення|Додаткова постанова|Окрема думка)', title) or [None, ''])[1]
            path = x['shliakh']
            v = vyd
            if slug == 'rishennya_obedn_palati' and any('палат' in s and 'об' not in s.lower() for s in path[:1]):
                v = 'ОП'
            rows.append({'sud': sud, 'vyd': v, 'storinka': slug, 'rozdil': ' / '.join(path), 'vyd_rishennia': kind, 'data': parse_date(title),
                         'spravy': '; '.join(dict.fromkeys(cases)), 'provadzhennia': m.group(1).strip() if m else '', 'nazva': title,
                         'url': x['url'] if x['url'].startswith('http') else f'{BASE}/supreme/pro_sud/{slug}/{x["url"]}'})
        time.sleep(0.5)
    out = os.path.join(ROOT, 'data', 'palaty_supreme.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    import collections
    print(json.dumps({'zapysiv': len(rows), 'za_vydom': dict(collections.Counter((r['sud'], r['vyd']) for r in rows).__iter__() and
                      {f'{k[0]} {k[1]}': v for k, v in collections.Counter((r['sud'], r['vyd']) for r in rows).items()}),
                      'bez_nomera_spravy': sum(1 for r in rows if not r['spravy'])}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
