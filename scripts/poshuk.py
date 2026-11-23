#!/usr/bin/env python3
"""Пошук у базі правових позицій ВС і в дайджестах.

Автор: В'ячеслав Плескач

Позиції (сортування: зразкові → ВП → ОП → палати → колегії, далі новіші):
  python3 scripts/poshuk.py "дисциплінарн* скарг*"
  python3 scripts/poshuk.py "строк* звернення" --riven 3 --sud КАС
  python3 scripts/poshuk.py --sprava 990SCGC/12/24
  python3 scripts/poshuk.py "відступ*" --rubryka "ВРП"
Дайджести:
  python3 scripts/poshuk.py "електронн* доказ*" --dajdzhesty            # за змістом
  python3 scripts/poshuk.py "дисциплінарн* відповідальн* судд*" --dajdzhesty --tekst   # повний текст, зі сторінками

Запит: слова через пробіл (усі мають бути), * у кінці — будь-яке закінчення, "лапки" — точна фраза.
"""
import argparse, csv, gzip, json, os, re, shlex, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patterns(q):
    pats = []
    for t in shlex.split(q or ''):
        if t.endswith('*'):
            pats.append(re.compile(r'\b' + re.escape(t[:-1]) + r'\w*', re.I))
        else:
            pats.append(re.compile(r'\b' + re.escape(t) + r'\b', re.I))
    return pats


def hit(text, pats):
    return all(p.search(text) for p in pats)


def snippet(text, pats, w=160):
    m = pats[0].search(text) if pats else None
    if not m:
        return text[:w * 2]
    s = max(0, m.start() - w)
    return ('…' if s else '') + text[s:m.end() + w].replace('\n', ' ') + '…'


def search_positions(a, pats):
    n = 0
    for l in open(os.path.join(ROOT, 'data', 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if a.riven and r['riven'] > a.riven:
            continue
        if a.sud and (r['sud'] or '').lower() != a.sud.lower():
            continue
        if a.rubryka and not any(a.rubryka.lower() in x.lower() for x in r['rubryky']):
            continue
        if a.sprava and not any(a.sprava.replace(' ', '') == (d.get('sprava') or '').replace(' ', '') for d in r['rishennia']):
            continue
        if a.poznachka and not r['poznachka']:
            continue
        blob = r['nazva'] + '\n' + r['tekst']
        if pats and not hit(blob, pats):
            continue
        n += 1
        if n <= a.limit:
            d = r['rishennia'][0] if r['rishennia'] else {}
            mk = f" [{r['poznachka']}]" if r['poznachka'] else ''
            print(f"#{r['id']} {r['riven_nazva']} | {r['sud']} | {d.get('data') or ''} № {d.get('sprava') or '—'}{mk}\n  {r['nazva']}\n  {snippet(r['tekst'], pats)}\n  {r['link']}  {d.get('edrsr') or ''}\n")
    print(f'Знайдено позицій: {n}' + (f' (показано {a.limit})' if n > a.limit else ''))


def search_digests(a, pats):
    cat = {x['id']: x for x in json.load(open(os.path.join(ROOT, 'dajdzhesty', 'katalog.json'), encoding='utf-8'))}
    if not a.tekst:
        n = 0
        with open(os.path.join(ROOT, 'dajdzhesty', 'zmist_usi.tsv'), encoding='utf-8') as f:
            for r in csv.DictReader(f, delimiter='\t'):
                if a.sud and r['sud'].lower() != a.sud.lower():
                    continue
                if hit(r['punkt'] + ' ' + r['dajdzhest'], pats):
                    n += 1
                    if n <= a.limit:
                        print(f"[{r['sud']}, {r['typ'].lower()}, {r['rik']}] {r['dajdzhest']}\n  с. {r['storinka'] or '?'}: {r['punkt']}\n  dajdzhesty/zmist/{r['id']}.md\n")
        print(f'Знайдено пунктів змісту: {n}')
        return
    n = 0
    for i, it in cat.items():
        if a.sud and it['sud'].lower() != a.sud.lower():
            continue
        p = os.path.join(ROOT, 'dajdzhesty', 'tekst', f'{i}.txt.gz')
        if not os.path.exists(p):
            continue
        pages = gzip.open(p, 'rt', encoding='utf-8').read().split('\f')
        found = [k + 1 for k, pg in enumerate(pages) if hit(re.sub(r'\s+', ' ', pg), pats)]
        if found:
            n += 1
            if n <= a.limit:
                first = re.sub(r'\s+', ' ', pages[found[0] - 1])
                print(f"[{it['sud']}, {it['typ'].lower()}, {it['rik']}] {it['nazva']}\n  сторінки: {', '.join(map(str, found[:20]))}{' …' if len(found) > 20 else ''}\n  {snippet(first, pats)}\n  {it['dzherelo'] or it['pdf']}\n")
    print(f'Знайдено дайджестів: {n}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('zapyt', nargs='?', default='')
    ap.add_argument('--riven', type=int, help='1 зразкові, 2 +ВП, 3 +ОП, 4 +палати, 5 усі')
    ap.add_argument('--sud', help='Велика Палата / КАС / КГС / ККС / КЦС (для дайджестів також ЄСПЛ, Суд ЄС)')
    ap.add_argument('--rubryka', help='частина назви рубрики')
    ap.add_argument('--sprava', help='номер справи')
    ap.add_argument('--poznachka', action='store_true', help='лише «З відступом» / «Змінено»')
    ap.add_argument('--dajdzhesty', action='store_true')
    ap.add_argument('--tekst', action='store_true', help='шукати в повних текстах дайджестів')
    ap.add_argument('--limit', type=int, default=30)
    a = ap.parse_args()
    pats = patterns(a.zapyt)
    (search_digests if a.dajdzhesty else search_positions)(a, pats)


if __name__ == '__main__':
    main()
