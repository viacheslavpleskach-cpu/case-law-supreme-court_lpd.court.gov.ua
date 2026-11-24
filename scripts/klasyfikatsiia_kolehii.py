#!/usr/bin/env python3
"""Автоматична розмітка позицій колегій суддів (рівень 5) — для пошуку практики.

Автор: В'ячеслав Плескач

Модель навчається на перевірених вручну позиціях вищих рівнів (data/klasyfikatsiia.jsonl,
dzherelo = «перевірено»): логістична регресія за рубриками lpd, назвою, початком тексту і судом.
Ознаки колегій: юрисдикція (за судом), тип питання, підтип (для ПП), галузь (1–2 коди), чинність,
ймовірність і надійність розмітки. Резюме не складаються.

Надійність: «висока» — ймовірність основної галузі ≥ 0,5; «середня» — 0,3–0,5; «низька» — < 0,3.
За низької надійності до галузей додається галузь за правилами (klasyfikatsiia.haluz), якщо вона інша, —
щоб пошук за галуззю не пропускав позицію.

  python3 scripts/klasyfikatsiia_kolehii.py             → data/klasyfikatsiia_kolehii.jsonl, data/klasyfikatsiia_kolehii_zvit.json
  python3 scripts/klasyfikatsiia_kolehii.py --otsinka   → також перехресна перевірка моделі на вищих рівнях (5 частин)
"""
import argparse, collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import klasyfikatsiia as K

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
RUCHNI = os.path.join(DATA, 'perevirka_kolehii')  # вибіркова ручна перевірка колегій (id + поля), має перевагу


def clean_rub(r):
    rub = ' | '.join(r['rubryky'])
    return re.sub(r'Постанови Об.єднаної Палати|ОБ.ЄДНАНА ПАЛАТА, ПАЛАТА|Зразкові, палатні рішення', '', rub)


def doc(r):
    return clean_rub(r) + ' || ' + (r['nazva'] or '') + ' || ' + (r['tekst'] or '')[:700]


class Model:
    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.v1 = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2, sublinear_tf=True, max_features=150000)
        self.v2 = TfidfVectorizer(token_pattern=r'(?u)\b\w\w+\b', ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        self.v3 = TfidfVectorizer(token_pattern=r'\S+')

    def fit_x(self, rows):
        from scipy.sparse import hstack
        X = [doc(r) for r in rows]
        S = [r['sud'] or '' for r in rows]
        return hstack([self.v1.fit_transform(X), self.v2.fit_transform(X), self.v3.fit_transform(S)]).tocsr()

    def x(self, rows):
        from scipy.sparse import hstack
        X = [doc(r) for r in rows]
        S = [r['sud'] or '' for r in rows]
        return hstack([self.v1.transform(X), self.v2.transform(X), self.v3.transform(S)]).tocsr()


def clf():
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=8, max_iter=3000, class_weight='balanced')


def load_ruchni():
    out = {}
    if os.path.isdir(RUCHNI):
        for fn in sorted(os.listdir(RUCHNI)):
            if fn.endswith('.jsonl'):
                for l in open(os.path.join(RUCHNI, fn), encoding='utf-8'):
                    if l.strip():
                        d = json.loads(l)
                        out.setdefault(d['id'], {}).update(d)
    return out


def main(otsinka=False, log=print):
    import numpy as np
    rows = {}
    for l in open(os.path.join(DATA, 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        rows[r['id']] = r
    klas = [json.loads(l) for l in open(os.path.join(DATA, 'klasyfikatsiia.jsonl'), encoding='utf-8')]
    rev = [k for k in klas if k['dzherelo'] == 'перевірено' and k['haluz'] and k['id'] in rows]
    tr = [rows[k['id']] for k in rev]
    m = Model()
    Xtr = m.fit_x(tr)

    def labels(vals):
        c = collections.Counter(vals)
        return [v if c[v] >= 5 else 'інше' for v in vals]

    yh = labels([k['haluz'][0] for k in rev])
    yt = [k['typ'] for k in rev]
    pp = [(i, k['pidtyp']) for i, k in enumerate(rev) if k['typ'] == 'ПП' and k.get('pidtyp')]
    zv = {'navchannia': {'pozytsii': len(rev), 'pp_z_pidtypom': len(pp)}}

    if otsinka:
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
        cv = StratifiedKFold(5, shuffle=True, random_state=1)
        pr = cross_val_predict(clf(), Xtr, yh, cv=cv, method='predict_proba')
        cls = sorted(set(yh))
        top = pr.argmax(1)
        conf = pr.max(1)
        ok = np.array([cls[t] == y for t, y in zip(top, yh)])
        ok2 = np.array([cls[t] in k['haluz'] for t, k in zip(top, rev)])
        o = {'haluz_tochno': round(float(ok.mean()), 3), 'haluz_sered_perevirenykh_dvokh': round(float(ok2.mean()), 3)}
        for nm, lo, hi in (('висока', .5, 2), ('середня', .3, .5), ('низька', 0, .3)):
            sel = (conf >= lo) & (conf < hi)
            o[f'частка_{nm}'] = round(float(sel.mean()), 3)
            o[f'точність_{nm}'] = round(float(ok[sel].mean()), 3) if sel.any() else None
        prt = cross_val_predict(clf(), Xtr, yt, cv=cv)
        o['typ_tochno'] = round(float(np.mean([a == b for a, b in zip(prt, yt)])), 3)
        rules = [(K.haluz(r) or ['-'])[0] for r in tr]
        o['pravyla_haluz_tochno'] = round(float(np.mean([a == b for a, b in zip(rules, [k['haluz'][0] for k in rev])])), 3)
        o['pravyla_typ_tochno'] = round(float(np.mean([K.typ(r, K.haluz(r)) == k['typ'] for r, k in zip(tr, rev)])), 3)
        zv['perekhresna_perevirka'] = o
        log('перехресна перевірка:', json.dumps(o, ensure_ascii=False))

    mh = clf().fit(Xtr, yh)
    mt = clf().fit(Xtr, yt)
    mp = clf().fit(Xtr[[i for i, _ in pp]], [p for _, p in pp]) if len(pp) >= 20 else None

    kol = [r for r in rows.values() if r['riven'] == 5]
    kol.sort(key=lambda r: r['id'])
    Xk = m.x(kol)
    ph = mh.predict_proba(Xk)
    pt = mt.predict(Xk)
    ppd = mp.predict(Xk) if mp is not None else [''] * len(kol)
    ch = list(mh.classes_)
    ruchni = load_ruchni()
    per = K.load_perevirka()  # позиції, що перейшли з вищих рівнів до колегій, зберігають ручну перевірку
    for i, p in per.items():
        if i not in ruchni:
            ruchni[i] = p
    out = []
    for i, r in enumerate(kol):
        order = ph[i].argsort()[::-1]
        p1, p2 = ph[i][order[0]], ph[i][order[1]]
        h = [ch[order[0]]]
        if p2 >= 0.25 and p2 >= 0.4 * p1:
            h.append(ch[order[1]])
        if p1 < 0.3:
            rh = (K.haluz(r) or [None])[0]
            if rh and rh not in h:
                h = (h + [rh])[:2]
        h = [x for x in h if x != 'інше'] or (K.haluz(r) or ['V01'])[:1]
        t = pt[i]
        if t == 'СС':  # статус суддів — лише ВП
            t = 'МП'
        if 'K02' in h and t == 'МП':
            t = 'ПП'
        nd = 'висока' if p1 >= 0.5 else ('середня' if p1 >= 0.3 else 'низька')
        od = K.osnovne_rishennia(r)
        rec = {'id': r['id'], 'data': od.get('data') or '', 'sprava': od.get('sprava') or '', 'sud': r['sud'] or '',
               'yurysdyktsiia': K.yurysdyktsiia(r), 'typ': t, 'pidtyp': ppd[i] if t == 'ПП' else '', 'haluz': h,
               'chynnist': K.chynnist(r), 'slova': len((r['tekst'] or '').split()), 'ymovirnist': round(float(p1), 2),
               'nadiinist': nd, 'dzherelo': 'авто (модель)'}
        if r['id'] in ruchni:
            for k2 in ('typ', 'pidtyp', 'haluz', 'prymitka'):
                if ruchni[r['id']].get(k2) not in (None, ''):
                    rec[k2] = ruchni[r['id']][k2]
            rec['dzherelo'], rec['nadiinist'] = 'перевірено', 'перевірено'
        out.append(rec)
    with open(os.path.join(DATA, 'klasyfikatsiia_kolehii.jsonl'), 'w', encoding='utf-8') as f:
        for x in out:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')
    zv.update({'pozytsii': len(out), 'nadiinist': dict(collections.Counter(x['nadiinist'] for x in out)),
               'typ': dict(collections.Counter(K.TYPY[x['typ']] for x in out)),
               'haluz_osnovna': {f"{k} {K.NAZVA.get(k, k)}": v for k, v in collections.Counter(x['haluz'][0] for x in out).most_common()},
               'dvi_haluzi': sum(1 for x in out if len(x['haluz']) > 1),
               'za_sudom': dict(collections.Counter(x['sud'] for x in out))})
    old = os.path.join(DATA, 'klasyfikatsiia_kolehii_zvit.json')
    if not otsinka and os.path.exists(old):
        prev = json.load(open(old, encoding='utf-8'))
        if 'perekhresna_perevirka' in prev:
            zv['perekhresna_perevirka'] = prev['perekhresna_perevirka']
        if 'vybirka' in prev:
            zv['vybirka'] = prev['vybirka']
    json.dump(zv, open(old, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f"колегії: розмічено {len(out)} позицій; надійність {zv['nadiinist']}")
    return zv


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--otsinka', action='store_true', help='перехресна перевірка моделі на перевірених позиціях вищих рівнів')
    a = ap.parse_args()
    main(a.otsinka)
