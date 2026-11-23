"""Розбір PDF дайджесту ВС: зміст (пункти + сторінки), процитовані справи, посилання на ЄДРСР.

Автор: В'ячеслав Плескач

Використання: python3 digest_parse.py файл.pdf [--raw]
"""
import re, subprocess, sys, json, collections

TOC_HDR = re.compile(r'^\s*(ЗМІСТ|Зміст|З\s?М\s?І\s?С\s?Т|Contents|CONTENTS|Table of Contents)\s*:?\s*$')
NUM_END = re.compile(r'^(?P<t>.*?\S)(?P<sep>\s*[.…·]{2,}\s*|\s{2,}|\s)(?P<p>\d{1,3})\s*$')
CASE = re.compile(r'справ[іиаі]?\s*№\s*([0-9]{3}[A-Z]{3,5}/[0-9]{1,5}/[0-9]{2}|[0-9]{1,4}[/\-][0-9]{1,7}[/\-][0-9]{2}(?:\s?[-‑–]\s?[а-яґєіїa-z]{1,3}\b)?)', re.I)
REV = re.compile(r'reyestr\.court\.gov\.ua/Review/(\d{5,10})')
SPLIT_ECHR = re.compile(r'(?:(?<=\s)|^)(?=(?:Стаття \d+(?:-\d)? (?:Конвенції|Протоколу|Першого)|Статті \d+|'
                        r"[A-ZÀ-ÖØ-ÞĂȘȚŞĘŁŃŚŹŻ][A-ZÀ-ÖØ-ÞĂȘȚŞĘŁŃŚŹŻ0-9 .,'’&()\-]{2,} (?:v\.|against|та інші проти|проти) |"
                        r'(?:Рішення|Постанова|Ухвала|Висновок) (?:Суду|Загального)|[IVXІХ]{1,5}\. ))')


def pdf_pages(path, raw=False):
    args = ['pdftotext'] + ([] if raw else ['-layout']) + [path, '-']
    t = subprocess.run(args, capture_output=True, text=True).stdout
    return t.split('\f')


def repeated_lines(pages):
    """Колонтитули: рядки, що трапляються на ≥25 % сторінок."""
    c = collections.Counter()
    for p in pages:
        for l in {re.sub(r'\d+', '#', x.strip()) for x in p.split('\n') if x.strip()}:
            c[l] += 1
    n = max(len(pages), 1)
    return {l for l, k in c.items() if n >= 4 and k / n >= 0.25}


def level(s):
    m = re.match(r'^(\d+(?:\.\d+)*)\.?\s', s)
    if m:
        return m.group(1).count('.') + 1
    if re.match(r'^(РОЗДІЛ|Розділ|ГЛАВА|Глава|[IVXІХ]{1,5}\.)\s', s):
        return 0
    return None


def find_toc_start(pages):
    for i, p in enumerate(pages[:12]):
        ls = p.split('\n')
        for j, l in enumerate(ls):
            if TOC_HDR.match(l):
                return i, j
    return None


def clean(t):
    t = re.sub(r'\s*[.…·]{3,}\s*', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip(' .…·')
    return t


def toc_numbered(pages, rep):
    st = find_toc_start(pages)
    if not st:
        return []
    lines = []
    for i in range(st[0], min(st[0] + 10, len(pages))):
        ls = pages[i].split('\n')
        if i == st[0]:
            ls = ls[st[1] + 1:]
        lines += [(i, l) for l in ls]
    entries, buf, first_p = [], [], None
    for i, l in lines:
        if first_p and i >= first_p - 1:      # дійшли до сторінки, де починається текст
            break
        s = l.strip()
        if not s or re.sub(r'\d+', '#', s) in rep or re.fullmatch(r'\d{1,3}', s):
            continue
        m = NUM_END.match(s)
        if m and len(clean(m.group('t'))) > 2:
            t = clean(' '.join(buf + [m.group('t')]))
            p = int(m.group('p'))
            weak = not re.search(r'[.…·]{2,}|\s{2,}', m.group('sep'))
            entries.append({'t': t, 'p': p, 'lvl': level(t), 'weak': weak})
            buf = []
            if first_p is None:
                first_p = p
        else:
            buf.append(s)
            if len(buf) > 12:          # надто довгий «хвіст» — кінець змісту
                break
    # «слабкий» номер (через один пробіл), що ламає зростання сторінок, — це частина тексту пункту
    i = 0
    while i < len(entries) - 1:
        e, n = entries[i], entries[i + 1]
        if e['weak'] and (e['p'] > n['p'] + 3 or e['p'] > len(pages) + 3) and n['lvl'] is None:
            n['t'] = clean(e['t'] + ' ' + str(e['p']) + ' ' + n['t']); n['lvl'] = e['lvl']
            entries.pop(i); continue
        i += 1
    entries = [e for e in entries if e['p'] <= len(pages) + 5]
    for e in entries:
        e.pop('weak', None)
    return lnds(entries)


def lnds(entries):
    """Найдовша неспадна послідовність номерів сторінок: відкидає збої верстки, а не все, що після них."""
    if not entries:
        return []
    import bisect
    tails, idx, prev = [], [], [None] * len(entries)
    for i, e in enumerate(entries):
        k = bisect.bisect_right([entries[j]['p'] for j in idx], e['p'])
        if k > 0:
            prev[i] = idx[k - 1]
        if k == len(idx):
            idx.append(i)
        else:
            idx[k] = i
    keep, i = [], idx[-1]
    while i is not None:
        keep.append(i)
        i = prev[i]
    keep = set(keep)
    return [e for i, e in enumerate(entries) if i in keep]


def toc_split(pages_raw, rep):
    """Для оглядів ЄСПЛ / Суду ЄС: зміст у дві колонки — ділимо текст за початками пунктів."""
    st = find_toc_start(pages_raw)
    if not st:
        return [], None
    chunks = []
    for i in range(st[0], min(st[0] + 6, len(pages_raw))):
        ls = pages_raw[i].split('\n')
        if i == st[0]:
            ls = ls[st[1] + 1:]
        ls = [x.strip() for x in ls if x.strip() and re.sub(r'\d+', '#', x.strip()) not in rep]
        if chunks and not any(re.search(r'\s\d{1,3}$|^\d{1,3}$', x) for x in ls):
            break
        chunks += ls
    pages_found = []
    keep = []
    for x in chunks:
        if re.fullmatch(r'\d{1,3}', x):
            pages_found.append(int(x)); continue
        m = re.search(r'\s(\d{1,3})$', x)
        if m and not re.search(r'(Стаття|Статті|Протоколу|№|року|ст\.)\s\d{1,3}$', x):
            pages_found.append(int(m.group(1))); x = x[:m.start()]
        keep.append(x)
    text = ' '.join(keep)
    pages_found = [p for p in pages_found if 2 < p <= len(pages_raw) + 3]
    parts = [clean(x) for x in SPLIT_ECHR.split(text)]
    parts = [x for x in parts if len(x) > 1]
    merged = []
    for x in parts:          # «DEREVYANKO» + «AND TARASOVA v. …» — склеюємо уламки назв
        if merged and not re.search(r'[a-zа-яґєії]', merged[-1]) and len(merged[-1]) < 80:
            merged[-1] = merged[-1] + ' ' + x
        else:
            merged.append(x)
    parts = [x for x in merged if len(x) > 3]
    first = min(pages_found) if pages_found else None
    return [{'t': x, 'p': None, 'lvl': level(x)} for x in parts], first


def outline(path):
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        res = []

        def walk(o, d):
            for x in o:
                if isinstance(x, list):
                    walk(x, d + 1)
                else:
                    try:
                        p = r.get_destination_page_number(x) + 1
                    except Exception:
                        p = None
                    res.append({'t': clean(x.title), 'p': p, 'lvl': d})
        walk(r.outline, 1)
        return res
    except Exception:
        return []


def cited(pages):
    flat = re.sub(r'\s+', ' ', '\n'.join(pages))
    cs = []
    for m in CASE.finditer(flat):
        c = re.sub(r'\s', '', m.group(1)).replace('‑', '-').replace('–', '-')
        if c not in cs:
            cs.append(c)
    revs = list(dict.fromkeys(REV.findall(re.sub(r'\s', '', flat))))
    return cs, revs


ECHR_CASE = re.compile(r"^([A-ZÀ-ÖØ-ÞĂȘȚŞĘŁŃŚŹŻ][A-Za-zÀ-ÿĂăȘșȚțŞşĘęŁłŃńŚśŹźŻż .,'’&()\-]{1,80}?\s(?:v\.|проти)\s[^:]{2,80}):\s*(.*)$")


def echr_cases(pages):
    out, seen = [], set()
    for k, p in enumerate(pages):
        ls = [x.strip() for x in p.split('\n')]
        for j, l in enumerate(ls):
            m = ECHR_CASE.match(l)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            t = l
            for x in ls[j + 1:j + 5]:
                if not x or ECHR_CASE.match(x) or len(t) > 400:
                    break
                t += ' ' + x
                if re.search(r'порушенн\w*\.?$', x):
                    break
            out.append({'t': clean(t), 'p': k + 1, 'lvl': None})
    return out


NAZVA = re.compile(r'^\s*Назва:\s+(CASE OF .+?)\s*$')


def echr_old(pages):
    out = []
    for k, p in enumerate(pages):
        for l in p.split('\n'):
            m = NAZVA.match(l)
            if m:
                out.append({'t': clean(m.group(1)), 'p': k + 1, 'lvl': None})
    return out


def headings(pages, rep):
    """Дайджести без змісту: заголовки — неабзацні блоки (без відступу), після яких іде абзац з відступом."""
    out = []
    for k, p in enumerate(pages[1:], 2):
        ls = p.split('\n')
        blocks, cur = [], []
        for l in ls + ['']:
            if l.strip() and re.sub(r'\d+', '#', l.strip()) not in rep and not re.fullmatch(r'\s*\d{1,3}\s*', l):
                cur.append(l)
            elif cur:
                blocks.append(cur); cur = []
        for b_i, b in enumerate(blocks[:-1]):
            ind = [len(x) - len(x.lstrip()) for x in b]
            nxt = blocks[b_i + 1][0]
            txt = clean(' '.join(x.strip() for x in b))
            if len(b) <= 6 and max(ind) <= 2 and (len(nxt) - len(nxt.lstrip())) >= 3 and 25 <= len(txt) <= 600 \
                    and not re.search(r'\s–\s{2,}|^(Перелік|ВП ВС|ЦК|ГПК|КАС|\(?https?:)|reyestr\.court', txt) and not txt.endswith((',', ':', '-')):
                out.append({'t': txt, 'p': k, 'lvl': None})
    return out


BODY_NUM = re.compile(r'^\s{0,3}(\d{1,2}(?:\.\d{1,3}){1,3})\.?\s+(\S.*)$')


def numbered_body(pages, rep):
    """Пронумеровані заголовки позицій у тексті («1.1.2. …»), яких немає у змісті."""
    out = []
    for k, p in enumerate(pages[1:], 2):
        ls = p.split('\n')
        for j, l in enumerate(ls):
            m = BODY_NUM.match(l)
            if not m or (j > 0 and ls[j - 1].strip() and not re.fullmatch(r'\s*\d{1,3}\s*', ls[j - 1])):
                continue
            t = [l.strip()]
            for x in ls[j + 1:j + 8]:
                if not x.strip() or len(x) - len(x.lstrip()) >= 5:
                    break
                t.append(x.strip())
            txt = clean(' '.join(t))
            if 20 <= len(txt) <= 900 and not re.search(r'[.…]{4,}', l):
                out.append({'t': txt, 'p': k, 'lvl': m.group(1).count('.') + 1, 'tekst': 1})
    return out


def toc_from_pages(pg, path, kind=''):
    rep = repeated_lines(pg)
    t, method = [], 'zmist'
    if kind.startswith(('ЄСПЛ', 'Суд ЄС')) and path:
        pr = pdf_pages(path, raw=True)
        t, _ = toc_split(pr, repeated_lines(pr))
        method = 'zmist-split'
    if len(t) < 3:
        t, method = toc_numbered(pg, rep), 'zmist'
    if len(t) < 2 and path:
        o = outline(path)
        if len(o) >= 2:
            t, method = o, 'zakladky'
    if len(t) < 2 and kind.startswith('ЄСПЛ'):
        c = echr_cases(pg)
        if len(c) < 2:
            c = echr_old(pg)
        if len(c) >= 1:
            t, method = c, 'spravy-yespl'
    if len(t) < 2 and not kind.startswith(('ЄСПЛ', 'Суд ЄС')):
        h = headings(pg, rep)
        if len(h) >= 2:
            t, method = h, 'zaholovky'
    if method in ('zmist', 'zakladky') and len(t) >= 1 and len(t) < len(pg) / 4:
        have = {re.match(r'^(\d+(?:\.\d+)*)', e['t']).group(1) for e in t if re.match(r'^\d+(?:\.\d+)*', e['t'])}
        body = [e for e in numbered_body(pg, rep) if re.match(r'^(\d+(?:\.\d+)*)', e['t']).group(1) not in have]
        if len(body) >= 3:
            t = sorted(t + body, key=lambda e: (e['p'] or 0, e.get('tekst', 0)))
            method += '+tekst'
    if len(t) < 2:
        method = 'nemaie'
    return t, method


def parse(path, kind=''):
    pg = pdf_pages(path)
    t, method = toc_from_pages(pg, path, kind)
    cs, revs = cited(pg)
    return {'pages': len(pg) - (1 if not pg[-1].strip() else 0), 'toc_method': method, 'toc': t,
            'cases': cs, 'edrsr_doc_ids': revs, 'text': '\f'.join(pg)}


if __name__ == '__main__':
    r = parse(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')
    print(r['pages'], 'pages;', r['toc_method'], len(r['toc']), 'cases', len(r['cases']), 'revs', len(r['edrsr_doc_ids']))
    for e in r['toc'][:30]:
        print(' ', e)
