#!/usr/bin/env python3
"""Індекси практики ВС вищих рівнів за галузями права: pokazhchyky/haluzi/<код>.md + README.md.

Автор: В'ячеслав Плескач

Кожна галузь: розділи за типом питання (юрисдикція / процесуальне — за підтипами / матеріальне / статус суддів),
усередині — від нових до старих; рівень, суд, дата і № справи основного рішення, № провадження, позначка відступу,
#id позиції (повний текст: python3 scripts/poshuk.py --id <id>). Позиція з двома галузями є в обох індексах.
Запускається з scripts/storinka.py.
"""
import collections, json, os

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
                 "⚠ від позиції відступлено; ↺ позиція містить відступ. Повний текст і резюме: `python3 scripts/poshuk.py --id <id>` "
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
    open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8').write('\n'.join(R) + '\n')
    print('індексів:', len(summary))


if __name__ == '__main__':
    main()
