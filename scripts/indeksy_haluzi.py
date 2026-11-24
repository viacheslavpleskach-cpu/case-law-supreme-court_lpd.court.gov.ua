#!/usr/bin/env python3
"""Індекси практики ВС вищих рівнів за галузями права: pokazhchyky/haluzi/<код>.md + README.md.

Автор: В'ячеслав Плескач

Кожна галузь: розділи за типом питання (юрисдикція / процесуальне — за підтипами / матеріальне / статус суддів),
усередині — від нових до старих; рівень, суд, дата і № справи основного рішення, № провадження, позначка відступу,
#id позиції (повний текст: python3 scripts/poshuk.py --id <id>). Позиція з двома галузями є в обох індексах.
Запускається з scripts/storinka.py.
"""
import collections, json, os
from vidstup_zviazky import korotko

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(ROOT, 'pokazhchyky', 'haluzi')
RIVEN = {1: 'ЗС', 2: 'ВП', 3: 'ОП', 4: 'Палата'}
TYP_ORDER = ['Ю', 'ПП', 'МП', 'СС']


def main():
    pos = {}
    for l in open(os.path.join(DATA, 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if r['riven'] <= 4:
            pos[r['id']] = r
    tx = json.load(open(os.path.join(DATA, 'taksonomiia.json'), encoding='utf-8'))
    hn = {c: n for g in tx['taksonomiia'].values() for c, n in g}
    by = collections.defaultdict(list)
    for l in open(os.path.join(DATA, 'klasyfikatsiia.jsonl'), encoding='utf-8'):
        k = json.loads(l)
        if k['id'] in pos:
            for i, h in enumerate(k['haluz']):
                by[h].append((k, i))
    os.makedirs(OUT, exist_ok=True)
    for fn in os.listdir(OUT):
        if fn.endswith('.md'):
            os.remove(os.path.join(OUT, fn))
    summary = []
    for g, lst in tx['taksonomiia'].items():
        for code, name in lst:
            items = by.get(code, [])
            summary.append((g, code, name, items))
            L = [f'# {code} {name}', '', f"Практика ВС вищих рівнів (зразкові справи, ВП, ОП, палати). Позицій: {len(items)} "
                 f"(основна галузь — {sum(1 for _, i in items if i == 0)}, друга — {sum(1 for _, i in items if i == 1)}). "
                 "Рядок: дата основного рішення · рівень · суд · справа (провадження) — назва позиції `#id`. "
                 "⚠ від позиції відступлено (під рядком — постанова, якою відступлено); ↺ позиція містить відступ (під рядком — постанови, від висновків яких відступлено). Повний текст і резюме: `python3 scripts/poshuk.py --id <id>` "
                 "або сторінка https://viacheslavpleskach-cpu.github.io/case-law-supreme-court_lpd.court.gov.ua/", '']
            for t in TYP_ORDER:
                sub = [(k, i) for k, i in items if k['typ'] == t]
                if not sub:
                    continue
                L += [f"## {tx['typy'][t]} ({len(sub)})", '']
                groups = collections.defaultdict(list)
                for k, i in sub:
                    groups[k.get('pidtyp') or ''].append((k, i))
                for pt in sorted(groups, key=lambda x: (x == '', x)):
                    if pt:
                        L += [f'### {pt} ({len(groups[pt])})', '']
                    for k, i in sorted(groups[pt], key=lambda x: (x[0].get('data') or '', x[0]['id']), reverse=True):
                        r = pos[k['id']]
                        d = next((x for x in r['rishennia'] if x.get('sprava') == k.get('sprava') and x.get('data') == k.get('data')), r['rishennia'][0] if r['rishennia'] else {})
                        mk = ' ⚠' if k['chynnist'] == 'від неї відступлено' else (' ↺' if k['chynnist'] == 'містить відступ' else '')
                        pr = f" ({d.get('provadzhennia')})" if d.get('provadzhennia') else ''
                        sud = '' if r['sud'] == 'Велика Палата' else f" {r['sud']}"
                        other = '' if len(k['haluz']) < 2 else f" [також: {hn.get(k['haluz'][1 - i], '')}]"
                        dd = k.get('data') or ''
                        dd = f'{dd[8:10]}.{dd[5:7]}.{dd[:4]}' if dd else '—'
                        L.append(f"- {dd} · {RIVEN[r['riven']]}{sud} · № {d.get('sprava') or '—'}{pr} — {r['nazva'].strip()}{mk}{other} `#{r['id']}`")
                        if k['chynnist'] == 'від неї відступлено':
                            vu = r.get('vidstupleno_u') or []
                            L.append('  - відступлено: ' + ('; '.join((f"[{korotko(x)}]({x['edrsr']})" if x.get('edrsr') else korotko(x)) for x in vu[:2])
                                                          if vu else 'постанову не встановлено'))
                        if k['chynnist'] == 'містить відступ' and r.get('vidstupleno_vid'):
                            vv = r['vidstupleno_vid']
                            L.append('  - відступлено від: ' + '; '.join((f"[{korotko(x)}]({x['edrsr']})" if x.get('edrsr') else korotko(x)) for x in vv[:4])
                                     + (f' та ще {len(vv) - 4}' if len(vv) > 4 else ''))
                    L.append('')
            open(os.path.join(OUT, f'{code}.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    R = ['# Індекси практики ВС за галузями права', '', "Автор: В'ячеслав Плескач. Зразкові справи, Велика Палата, об'єднані палати, палати — "
         f"{len(pos)} позицій з lpd.court.gov.ua, класифікація перевірена. Позиція з двома галузями є в обох індексах.", '',
         '| Код | Галузь | Позицій | з них основна | Ю | ПП | МП | СС |', '|---|---|---|---|---|---|---|---|']
    cur = None
    for g, code, name, items in summary:
        if g != cur:
            R.append(f'| | **{g}** | | | | | | |')
            cur = g
        c = collections.Counter(k['typ'] for k, _ in items)
        R.append(f"| [{code}]({code}.md) | {name} | {len(items)} | {sum(1 for _, i in items if i == 0)} | {c['Ю']} | {c['ПП']} | {c['МП']} | {c['СС']} |")
    kol = kolehii(tx, hn)
    if kol:
        R += ['', f"Колегії суддів ({kol} позицій, автоматична розмітка): [`../haluzi_kolehii/`](../haluzi_kolehii/README.md)."]
    open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write('\n'.join(R) + '\n')
    print('індексів:', len(summary))


def kolehii(tx, hn):
    """pokazhchyky/haluzi_kolehii/<код>.md — позиції колегій за галуззю (автоматична розмітка), за судом і типом питання."""
    kp = os.path.join(DATA, 'klasyfikatsiia_kolehii.jsonl')
    if not os.path.exists(kp):
        return 0
    pos = {}
    for l in open(os.path.join(DATA, 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if r['riven'] == 5:
            pos[r['id']] = r
    out = os.path.join(ROOT, 'pokazhchyky', 'haluzi_kolehii')
    os.makedirs(out, exist_ok=True)
    for fn in os.listdir(out):
        if fn.endswith('.md'):
            os.remove(os.path.join(out, fn))
    by = collections.defaultdict(list)
    n = 0
    for l in open(kp, encoding='utf-8'):
        k = json.loads(l)
        if k['id'] in pos:
            n += 1
            for i, h in enumerate(k['haluz']):
                by[h].append((k, i))
    R = ['# Колегії суддів ВС за галузями права (автоматична розмітка)', '',
         f"Автор: В'ячеслав Плескач. {n} позицій колегій з lpd.court.gov.ua. Галузь і тип питання визначено автоматично моделлю, "
         "навченою на перевірених позиціях зразкових справ, ВП, ОП і палат; розмітка приблизна. Позначка ? — низька надійність "
         "(галузь може бути визначена неточно; позицію додано також до галузі за правилами). Резюме немає; повний текст — "
         "`python3 scripts/poshuk.py --id <id>`.", '', '| Код | Галузь | Позицій | КАС | КГС | ККС | КЦС |', '|---|---|---|---|---|---|---|']
    for g, lst in tx['taksonomiia'].items():
        R.append(f'| | **{g}** | | | | | |')
        for code, name in lst:
            items = by.get(code, [])
            c = collections.Counter(k['sud'] for k, _ in items)
            R.append(f"| [{code}]({code}.md) | {name} | {len(items)} | {c['КАС']} | {c['КГС']} | {c['ККС']} | {c['КЦС']} |")
            if not items:
                continue
            L = [f'# {code} {name} — колегії суддів', '', f"Позицій: {len(items)} (автоматична розмітка; основна галузь — {sum(1 for _, i in items if i == 0)}). "
                 "Рядок: дата · суд · справа (провадження) — назва `#id`; ? — низька надійність розмітки; ⚠ від позиції відступлено; ↺ містить відступ.", '']
            for sud in ('КАС', 'КГС', 'ККС', 'КЦС', ''):
                sub = [(k, i) for k, i in items if (k['sud'] or '') == sud]
                if not sub:
                    continue
                L += [f"## {sud or 'Суд не визначено'} ({len(sub)})", '']
                for t in TYP_ORDER:
                    tt = [(k, i) for k, i in sub if k['typ'] == t]
                    if not tt:
                        continue
                    L += [f"### {tx['typy'][t]} ({len(tt)})", '']
                    for k, i in sorted(tt, key=lambda x: ((x[0].get('pidtyp') or ''), x[0].get('data') or '', x[0]['id']), reverse=False if t == 'ПП' else True):
                        r = pos[k['id']]
                        d = next((x for x in r['rishennia'] if x.get('sprava') == k.get('sprava') and x.get('data') == k.get('data')), r['rishennia'][0] if r['rishennia'] else {})
                        dd = k.get('data') or ''
                        dd = f'{dd[8:10]}.{dd[5:7]}.{dd[:4]}' if dd else '—'
                        mk = ' ⚠' if k['chynnist'] == 'від неї відступлено' else (' ↺' if k['chynnist'] == 'містить відступ' else '')
                        q = ' ?' if k.get('nadiinist') == 'низька' else ''
                        pt = f" [{k['pidtyp']}]" if k.get('pidtyp') else ''
                        pr = f" ({d.get('provadzhennia')})" if d.get('provadzhennia') else ''
                        L.append(f"- {dd} · № {d.get('sprava') or '—'}{pr} — {(r['nazva'] or '').strip()}{pt}{mk}{q} `#{r['id']}`")
                        if k['chynnist'] == 'від неї відступлено':
                            vu = r.get('vidstupleno_u') or []
                            L.append('  - відступлено: ' + ('; '.join((f"[{korotko(x)}]({x['edrsr']})" if x.get('edrsr') else korotko(x)) for x in vu[:2])
                                                          if vu else 'постанову не встановлено'))
                        if k['chynnist'] == 'містить відступ' and r.get('vidstupleno_vid'):
                            vv = r['vidstupleno_vid']
                            L.append('  - відступлено від: ' + '; '.join((f"[{korotko(x)}]({x['edrsr']})" if x.get('edrsr') else korotko(x)) for x in vv[:4])
                                     + (f' та ще {len(vv) - 4}' if len(vv) > 4 else ''))
                    L.append('')
            open(os.path.join(out, f'{code}.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    open(os.path.join(out, 'README.md'), 'w', encoding='utf-8').write('\n'.join(R) + '\n')
    print('індекси колегій за галузями:', n, 'позицій')
    return n


if __name__ == '__main__':
    main()
