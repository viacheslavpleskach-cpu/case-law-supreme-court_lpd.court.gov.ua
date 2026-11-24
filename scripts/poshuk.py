#!/usr/bin/env python3
"""Пошук у базі правових позицій ВС і в дайджестах.

Автор: В'ячеслав Плескач

Позиції (сортування: зразкові → ВП → ОП → палати → колегії, далі новіші):
  python3 scripts/poshuk.py "дисциплінарн* скарг*"
  python3 scripts/poshuk.py "строк* звернення" --riven 3 --sud КАС
  python3 scripts/poshuk.py --sprava 990SCGC/12/24
  python3 scripts/poshuk.py "відступ*" --rubryka "ВРП"
  python3 scripts/poshuk.py "строк*" --haluz P03 --typ ПП          # галузь і тип (колегії — автоматична розмітка)
  python3 scripts/poshuk.py "строк*" --haluz P03 --riven 4         # лише ЗС, ВП, ОП, палати
  python3 scripts/poshuk.py --id 14875 13289                         # повний текст, резюме, класифікація
Дайджести:
  python3 scripts/poshuk.py "електронн* доказ*" --dajdzhesty            # за змістом
  python3 scripts/poshuk.py "дисциплінарн* відповідальн* судд*" --dajdzhesty --tekst   # повний текст, зі сторінками

Запит: слова через пробіл (усі мають бути), * у кінці — будь-яке закінчення, "лапки" — точна фраза.
"""
import argparse, csv, gzip, json, os, re, shlex, sys
from vidstup_zviazky import korotko

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


HOMO = str.maketrans('АВСЕНІКМОРТХаесіорху', 'ABCEHIKMOPTXaecIopxy')


def norm_case(s):
    """№ справи без пробілів і з латиницею замість схожих кириличних літер (у lpd трапляється «990SСGС»)."""
    return (s or '').replace(' ', '').translate(HOMO).upper()


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


def load_klas():
    k = {}
    for fn in ('klasyfikatsiia.jsonl', 'klasyfikatsiia_kolehii.jsonl'):
        p = os.path.join(ROOT, 'data', fn)
        if os.path.exists(p):
            for l in open(p, encoding='utf-8'):
                d = json.loads(l)
                k[d['id']] = d
    return k


def show_id(a):
    klas = load_klas()
    for l in open(os.path.join(ROOT, 'data', 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if r['id'] in a.id:
            k = klas.get(r['id'], {})
            print(f"#{r['id']} {r['riven_nazva']} | {r['sud']} | {r['link']}")
            if k:
                print(f"  юрисдикція: {k['yurysdyktsiia']} · тип: {k['typ']}{' / ' + k['pidtyp'] if k.get('pidtyp') else ''} · галузі: {', '.join(k['haluz'])} · {k['chynnist']}"
                      + (f" · розмітка: {k['dzherelo']}" + (f", надійність {k['nadiinist']} ({k['ymovirnist']})" if k.get('ymovirnist') is not None else '') if r['riven'] == 5 else '')
                      + (f" · примітка: {k['prymitka']}" if k.get('prymitka') else ''))
            print(f"  НАЗВА: {r['nazva']}")
            if k.get('rezyume'):
                print(f"  РЕЗЮМЕ: {k['rezyume']}")
            print(f"  ТЕКСТ: {r['tekst']}")
            for d in r['rishennia']:
                print(f"  рішення: {d.get('data')} № {d.get('sprava')} провадження {d.get('provadzhennia') or '—'} склад {d.get('sklad') or '—'} {d.get('edrsr') or ''}" + (' — постанова, якою відступлено від позиції' if d.get('vidstup') else ''))
            for x in r.get('vidstupleno_u') or []:
                print(f"  ВІДСТУПЛЕНО: {korotko(x)} {x.get('edrsr') or ''} [{x['dzherelo']}]" + (f" — позиція #{x['pozytsii'][0]}" if x.get('pozytsii') else ''))
            if (r.get('poznachka') or '').startswith('Змінено') and not r.get('vidstupleno_u'):
                print('  ВІДСТУПЛЕНО: постанову не встановлено')
            print()


def search_positions(a, pats):
    n = 0
    klas = load_klas()
    for l in open(os.path.join(ROOT, 'data', 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if a.bez_kolehii and r['riven'] == 5:
            continue
        if a.haluz or a.typ or a.pidtyp:
            k = klas.get(r['id'])
            if not k or (a.haluz and a.haluz.upper() not in k['haluz']) or (a.typ and a.typ.upper() != k['typ'].upper()) \
                    or (a.pidtyp and a.pidtyp.lower() not in (k.get('pidtyp') or '').lower()):
                continue
        if a.riven and r['riven'] > a.riven:
            continue
        if a.sud and (r['sud'] or '').lower() != a.sud.lower():
            continue
        if a.rubryka and not any(a.rubryka.lower() in x.lower() for x in r['rubryky']):
            continue
        if a.sprava and not any(norm_case(a.sprava) == norm_case(d.get('sprava')) for d in r['rishennia']):
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
            k = klas.get(r['id'])
            if k:
                mk += f" · {k['typ']}{'/' + k['pidtyp'] if k.get('pidtyp') else ''} {','.join(k['haluz'])}" + (f" (авто, {k['nadiinist']})" if k.get('dzherelo', '').startswith('авто') and r['riven'] == 5 else '')
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
    ap.add_argument('--haluz', help='код галузі (C01…C14, P01…P09, K01, K02, S01, V01); для колегій — автоматична розмітка')
    ap.add_argument('--typ', help='тип питання: Ю, ПП, МП, СС; для колегій — автоматична розмітка')
    ap.add_argument('--pidtyp', help='підтип процесуального питання (частина назви, напр. «строки», «докази»)')
    ap.add_argument('--bez-kolehii', action='store_true', help='не показувати колегії')
    ap.add_argument('--id', type=int, nargs='+', help='повний текст позиції(й) за номером')
    ap.add_argument('--limit', type=int, default=30)
    a = ap.parse_args()
    if a.id:
        return show_id(a)
    pats = patterns(a.zapyt)
    (search_digests if a.dajdzhesty else search_positions)(a, pats)


if __name__ == '__main__':
    main()
