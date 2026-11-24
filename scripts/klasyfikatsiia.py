#!/usr/bin/env python3
"""Класифікація позицій вищих рівнів (зразкові справи, ВП, ОП, палати) для аналізу й узагальнення.

Автор: В'ячеслав Плескач

Ознаки кожної позиції:
  yurysdyktsiia — юрисдикція справи (для ВП — за кодом провадження: цс, гс, апп, кс, сап …);
  typ           — тип питання: Ю юрисдикція, ПП процесуальне право, МП матеріальне право, СС статус суддів;
  pidtyp        — для процесуальних: підтип (заповнює перевірка);
  haluz         — 1–2 коди галузі права з data/taksonomiia.json;
  chynnist      — «чинна», «містить відступ», «від неї відступлено»;
  rezyume       — для позицій понад 200 слів: резюме до 200 слів (заповнює перевірка);
  dzherelo      — «авто» або «перевірено».

Автоматична розмітка — за рубриками lpd, назвою, кодом провадження. Ручна перевірка (Claude) лежить у
data/perevirka/*.jsonl (один JSON-рядок на позицію: id + виправлені поля) і має перевагу над автоматичною.

  python3 scripts/klasyfikatsiia.py            → data/klasyfikatsiia.jsonl, data/klasyfikatsiia_zvit.json
                                                 і автоматична розмітка колегій (scripts/klasyfikatsiia_kolehii.py)
  python3 scripts/klasyfikatsiia.py --paket 60 → cache/paketу/*.jsonl — пакети для перевірки (ще не перевірені позиції)
"""
import argparse, collections, glob, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

TAKSONOMIIA = {
    'Публічне право': [
        ('P01', 'Податки і мито'),
        ('P02', 'Пенсійне забезпечення і соціальний захист'),
        ('P03', 'Публічна служба (державна, військова служба, поліція, прокуратура)'),
        ('P04', 'Виборче право і референдум'),
        ('P05', 'Містобудування і будівництво'),
        ('P06', 'Земельні відносини (публічно-правові)'),
        ('P07', 'Конкуренція, АМКУ, регулювання господарської діяльності'),
        ('P08', 'Інше публічне право (органи влади, доступ до інформації, звернення, ліцензування тощо)'),
        ('P09', 'Адміністративні правопорушення (КУпАП)'),
    ],
    'Приватне право': [
        ('C01', "Договори і зобов'язання"),
        ('C02', 'Власність і речові права'),
        ('C03', 'Корпоративне право'),
        ('C04', 'Банкрутство'),
        ('C05', 'Банківське і кредитне право, іпотека, фінансові послуги'),
        ('C06', 'Трудове право'),
        ('C07', 'Сімейне право'),
        ('C08', 'Спадкове право'),
        ('C09', 'Відшкодування шкоди (у т. ч. державою)'),
        ('C10', 'Захист прав споживачів'),
        ('C11', 'Інтелектуальна власність'),
        ('C12', 'Енергетика і житлово-комунальні послуги'),
        ('C13', 'Земельне право (приватноправові спори)'),
        ('C14', 'Захист честі, гідності та ділової репутації'),
    ],
    'Кримінальне право': [
        ('K01', 'Кримінальне право (КК)'),
        ('K02', 'Кримінальний процес (КПК)'),
    ],
    'Інше': [
        ('S01', 'Судоустрій і статус суддів (ВРП, ВККС)'),
        ('V01', 'Виконання судових рішень'),
    ],
}
NAZVA = {k: v for g in TAKSONOMIIA.values() for k, v in g}
HRUPA = {k: g for g, lst in TAKSONOMIIA.items() for k, _ in lst}
TYPY = {'Ю': 'Юрисдикція', 'ПП': 'Процесуальне право', 'МП': 'Матеріальне право', 'СС': 'Статус суддів (ВРП, ВККС)'}
PIDTYPY = ['доступ до суду і строки', 'підсудність і склад суду', 'докази і доказування', 'судові витрати',
           'забезпечення позову', 'перегляд судових рішень', 'учасники і представництво', 'інше процесуальне']

PROV = {'цс': 'цивільна', 'зц': 'цивільна', 'звц': 'цивільна', 'гс': 'господарська', 'зг': 'господарська',
        'апп': 'адміністративна', 'заі': 'адміністративна', 'ас': 'адміністративна', 'за': 'адміністративна', 'ав': 'адміністративна',
        'кс': 'кримінальна', 'зво': 'кримінальна', 'сап': 'статус суддів (ВРП, ВККС)'}
SUD_YUR = {'КАС': 'адміністративна', 'КГС': 'господарська', 'ККС': 'кримінальна', 'КЦС': 'цивільна'}

# (код, шаблон) — перевіряються по шляхах рубрик, потім по назві; порядок важливий
RULES = [
    ('S01', r'ВРП|ВККС|Вищ\w+ рад\w+ правосуддя|кваліфікаційн\w+ комісі\w+ суддів|статус\w* судд|дисциплінарн\w+ відповідальн\w+ судд'),
    ('C04', r'[Бб]анкрутств|неплатоспроможн|ліквідатор|арбітражн\w+ керуюч'),
    ('P01', r'[Пп]одатк|[Мм]итн|акциз|ПДВ|ЄСВ|єдин\w+ внеск'),
    ('P02', r'[Пп]енсі|соціальн\w+ (?:страх|захист|допомог|виплат)|пільг|чорнобил|інвалідн'),
    ('P03', r'публічн\w+ служб|державн\w+ служб|військов\w+ служб|військовослужб|поліці|прокурор|прокуратур|служб\w+ в органах місцевого'),
    ('P04', r'[Вв]иборч|референдум'),
    ('P05', r'[Мм]істобуд|будівництв|архітектур|самочинн\w+ будів'),
    ('P07', r'антимонопольн|[Кк]онкурен|АМКУ|ліценз|регулюванн\w+ господарськ|організаці\w+ господарськ'),
    ('C03', r'[Кк]орпоратив|цінн\w+ папер|господарськ\w+ товариств|учасник\w* товариств|акціонер'),
    ('C05', r'\bбанк(?!рут)\w*|кредит|іпотек|фінансов\w+ послуг|позик|поручит|порук'),
    ('C06', r'[Тт]рудов|заробітн|звільненн\w+ з роботи|поновленн\w+ на роботі'),
    ('C07', r'[Сс]імейн|алімент|дитин|батьківськ|шлюб|опік'),
    ('C08', r'[Сс]падк|заповіт'),
    ('C11', r'інтелектуальн|торговельн\w+ марк|авторськ|патент|винахід'),
    ('C12', r'енергоресурс|електричн\w+ енерг|природн\w+ газ|теплов\w+ енерг|житлово-комунальн|ЖКП|водопостач'),
    ('C10', r'[Сс]поживач'),
    ('C14', r'ділов\w+ репутац|чест\w*,? гідн|недостовірн\w+ інформац|спростуванн\w+ (?:недостовірн|інформац)'),
    ('P09', r'КУпАП|адміністративн\w+ правопоруш|адміністративн\w+ стягненн'),
    ('C09', r'[Шш]код|деліктн'),
    ('V01', r'[Вв]иконанн\w+ судов\w+ рішень|[Вв]иконавч\w+ провадж|виконавц'),
    ('K02', r'КРИМІНАЛЬН\w+ ПРОЦЕСУАЛЬН|КПК|[Кк]римінальн\w+ процесуальн|слідч\w+ судд|запобіжн'),
    ('K01', r'КРИМІНАЛЬНИЙ КОДЕКС|Кримінальн\w+ кодекс|\bКК\b|кримінальн\w+ правопоруш|покаранн'),
    ('C13', r'[Зз]емел'),
    ('C02', r'власност|речов|віндикац|[Жж]итлов|реєстрац\w+ прав|нерухом'),
    ('C01', r'[Дд]оговір|[Дд]оговор|зобов.язан|правочин|оренд|лізинг|постачанн|поставк|підряд|перевезенн'),
]


def prov_codes(r):
    out = []
    for d in r['rishennia']:
        p = d.get('provadzhennia') or ''
        m = re.search(r'\d{2}\s?-\s?\d+\s?([а-яіґ]+)\s?\d{2}', p) or re.search(r'([а-яіґ]{2,4})\s?\d{2}\s*$', p)
        if m:
            out.append(m.group(1))
    return out


def yurysdyktsiia(r):
    if r['riven_nazva'] == 'Велика Палата' or (r['riven'] == 1 and r['sud'] == 'Велика Палата'):
        for c in prov_codes(r):
            if c in PROV:
                return PROV[c]
        rub = ' | '.join(r['rubryky'])
        for sud, y in SUD_YUR.items():
            if sud in rub:
                return y
        if re.search(r'990SCGC|990/|9901/', ' '.join(d.get('sprava') or '' for d in r['rishennia'])):
            return 'адміністративна' if not re.search(r'SCGC', ' '.join(d.get('sprava') or '' for d in r['rishennia'])) else 'статус суддів (ВРП, ВККС)'
        return 'не визначено'
    return SUD_YUR.get(r['sud'], 'не визначено')


def typ(r, haluz):
    rub = ' | '.join(r['rubryky'])
    if re.search(r'Оскарження рішень, дій/бездіяльності (ВРП|ВККС)', rub):
        return 'СС'
    if re.search(r'[Юю]рисдикці', rub) or re.search(r'юрисдикці|предметн\w+ юрисдикці|розгляд\w* в порядку \w+ судочинства', r['nazva'][:250]):
        return 'Ю'
    if re.search(r'процесуальн\w+ прав|Процесуальні питання|КОДЕКС АДМІНІСТРАТИВНОГО СУДОЧИНСТВА|ПРОЦЕСУАЛЬН|Справи окремого провадження|питань процесуального', rub) \
            or 'K02' in haluz:
        return 'ПП'
    return 'МП'


def haluz(r):
    rub = ' | '.join(x for x in r['rubryky'] if not re.search(r'^(Велика Палата|Касаційний \S+ суд)$', x))
    rub = re.sub(r'Постанови Об.єднаної Палати|ОБ.ЄДНАНА ПАЛАТА, ПАЛАТА|Зразкові, палатні рішення', '', rub)
    found = []
    for src in (rub, r['nazva'], r['tekst'][:400]):
        for code, p in RULES:
            if code not in found and re.search(p, src):
                found.append(code)
        if found:
            break
    # земля: публічна чи приватна
    if 'C13' in found and (r['sud'] == 'КАС' or re.search(r'органу місцевого самоврядування|землеустр|публічн', r['nazva'] + rub)):
        found[found.index('C13')] = 'P06'
    if not found and r['sud'] == 'КАС':
        found = ['P08']
    return found[:2]


def chynnist(r):
    p = r.get('poznachka') or ''
    if p.startswith('Змінено'):
        return 'від неї відступлено'
    if p.startswith('З відступом'):
        return 'містить відступ'
    return 'чинна'


def osnovne_rishennia(r):
    """Рішення, з якого виведено позицію відповідного рівня: ВП / ОП / палата; інакше — найновіше."""
    docs = sorted([d for d in r['rishennia'] if not d.get('vidstup')] or r['rishennia'], key=lambda d: d.get('data') or '', reverse=True)
    want = {2: 'ВП', 3: 'ОП', 4: 'палата'}.get(r['riven'])
    c = [d for d in docs if want and d.get('sklad') == want]
    return (c or docs or [{}])[0]


def load_perevirka():
    out = {}
    for fn in sorted(glob.glob(os.path.join(DATA, 'perevirka', '*.jsonl'))):
        for l in open(fn, encoding='utf-8'):
            l = l.strip()
            if l:
                d = json.loads(l)
                out.setdefault(d['id'], {}).update(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paket', type=int, default=0, help='розбити неперевірені позиції на пакети такого розміру')
    ap.add_argument('--bez-kolehii', action='store_true', help='не оновлювати автоматичну розмітку колегій (klasyfikatsiia_kolehii.py)')
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(os.path.join(DATA, 'pozytsii.jsonl'), encoding='utf-8')]
    top = [r for r in rows if r['riven'] <= 4]
    per = load_perevirka()
    out = []
    for r in top:
        h = haluz(r)
        od = osnovne_rishennia(r)
        rec = {'id': r['id'], 'data': od.get('data') or '', 'sprava': od.get('sprava') or '', 'yurysdyktsiia': yurysdyktsiia(r), 'typ': typ(r, h), 'pidtyp': '', 'haluz': h,
               'chynnist': chynnist(r), 'slova': len(r['tekst'].split()), 'rezyume': '', 'dzherelo': 'авто'}
        if r['id'] in per:
            p = per[r['id']]
            for k in ('yurysdyktsiia', 'typ', 'pidtyp', 'haluz', 'rezyume', 'prymitka'):
                if k in p and p[k] not in (None, ''):
                    rec[k] = p[k]
            rec['dzherelo'] = 'перевірено'
        rec['chynnist'] = chynnist(r)
        out.append(rec)
    with open(os.path.join(DATA, 'klasyfikatsiia.jsonl'), 'w', encoding='utf-8') as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')
    json.dump({'taksonomiia': TAKSONOMIIA, 'typy': TYPY, 'pidtypy': PIDTYPY}, open(os.path.join(DATA, 'taksonomiia.json'), 'w'), ensure_ascii=False, indent=1)
    zv = {'pozytsii': len(out), 'perevireno': sum(1 for x in out if x['dzherelo'] == 'перевірено'),
          'typ': dict(collections.Counter(TYPY[x['typ']] for x in out)),
          'yurysdyktsiia': dict(collections.Counter(x['yurysdyktsiia'] for x in out)),
          'haluz_osnovna': {f"{k} {NAZVA[k]}": v for k, v in collections.Counter(x['haluz'][0] for x in out if x['haluz']).most_common()},
          'bez_haluzi': sum(1 for x in out if not x['haluz']), 'dvi_haluzi': sum(1 for x in out if len(x['haluz']) > 1),
          'potribne_rezyume': sum(1 for x in out if x['slova'] > 200), 'rezyume_ie': sum(1 for x in out if x['rezyume']),
          'chynnist': dict(collections.Counter(x['chynnist'] for x in out))}
    json.dump(zv, open(os.path.join(DATA, 'klasyfikatsiia_zvit.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(zv, ensure_ascii=False, indent=1))
    if not a.bez_kolehii and not a.paket:
        try:
            import klasyfikatsiia_kolehii
            klasyfikatsiia_kolehii.main()
        except ImportError as e:  # немає scikit-learn
            print('колегії: розмітку не оновлено —', e, '(pip install --break-system-packages scikit-learn)')
    if a.paket:
        d = os.path.join(ROOT, 'cache', 'pakety')
        os.makedirs(d, exist_ok=True)
        for fn in glob.glob(os.path.join(d, '*.jsonl')):
            os.remove(fn)
        by = {r['id']: r for r in top}
        todo = [x for x in out if x['dzherelo'] != 'перевірено']
        todo.sort(key=lambda x: (by[x['id']]['riven'], x['id']))
        for k in range(0, len(todo), a.paket):
            with open(os.path.join(d, f'paket_{k // a.paket + 1:03d}.jsonl'), 'w', encoding='utf-8') as f:
                for x in todo[k:k + a.paket]:
                    r = by[x['id']]
                    f.write(json.dumps({'id': r['id'], 'riven': r['riven_nazva'], 'sud': r['sud'], 'rubryky': [x[-160:] for x in r['rubryky'][:2]],
                                        'sprava': (r['rishennia'][0]['sprava'] if r['rishennia'] else None),
                                        'nazva': r['nazva'], 'tekst': r['tekst'], 'avto': {k2: x[k2] for k2 in ('yurysdyktsiia', 'typ', 'haluz')},
                                        'potribne_rezyume': x['slova'] > 200}, ensure_ascii=False) + '\n')
        print('пакетів:', (len(todo) + a.paket - 1) // a.paket, 'позицій:', len(todo))


if __name__ == '__main__':
    main()
