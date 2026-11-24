#!/usr/bin/env python3
"""Excel-таблиця практики ВС вищих рівнів: data/praktyka_VS_vyshchi_rivni.xlsx.

Автор: В'ячеслав Плескач

Рядок = позиція (від нових до старих). Текст позиції / резюме — у примітці до комірки «Позиція»
(з'являється при наведенні), тож рядки не розтягуються. Автофільтри на всіх колонках.

  python3 scripts/klasyfikatsiia.py && python3 scripts/excel_praktyka.py
"""
import json, os
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
R = {1: 'Зразкова справа', 2: 'Велика Палата', 3: "Об'єднана палата", 4: 'Палата'}


def main():
    pos = {}
    for l in open(os.path.join(DATA, 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if r['riven'] <= 4:
            pos[r['id']] = r
    tx = json.load(open(os.path.join(DATA, 'taksonomiia.json'), encoding='utf-8'))
    hn = {c: n for g in tx['taksonomiia'].values() for c, n in g}
    rows = []
    for l in open(os.path.join(DATA, 'klasyfikatsiia.jsonl'), encoding='utf-8'):
        k = json.loads(l)
        r = pos.get(k['id'])
        if r:
            rows.append((r, k))
    rows.sort(key=lambda x: (x[1].get('data') or x[0]['data_rishennia'] or '', x[0]['id']), reverse=True)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Позиції'
    head = ['Дата рішення', 'Рівень', 'Суд', 'Юрисдикція', 'Тип питання', 'Підтип', 'Галузь 1', 'Галузь 2', 'Чинність',
            'Позиція (наведіть — текст / резюме)', 'Справа №', 'Провадження №', 'lpd', 'ЄДРСР', 'Перевірено', 'id']
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F4E79')
        c.alignment = Alignment(vertical='center', wrap_text=True)
    for r, k in rows:
        d = next((x for x in r['rishennia'] if x.get('sprava') == k.get('sprava') and x.get('data') == k.get('data')), r['rishennia'][0] if r['rishennia'] else {})
        h = k['haluz'] + ['', '']
        ws.append([k.get('data') or r['data_rishennia'] or '', R[r['riven']], r['sud'], k['yurysdyktsiia'], tx['typy'].get(k['typ'], k['typ']), k.get('pidtyp') or '',
                   hn.get(h[0], h[0]), hn.get(h[1], h[1]), k['chynnist'], r['nazva'], d.get('sprava') or '', d.get('provadzhennia') or '',
                   r['link'], d.get('edrsr') or '', 'так' if k['dzherelo'] == 'перевірено' else '', r['id']])
        row = ws.max_row
        note = (('РЕЗЮМЕ: ' + k['rezyume'] + '\n\nТЕКСТ ПОЗИЦІЇ: ') if k.get('rezyume') else '') + r['tekst']
        cm = Comment(note[:30000], "В'ячеслав Плескач")
        cm.width, cm.height = 520, min(60 + len(note) // 2, 600)
        ws.cell(row, 10).comment = cm
        for col in (13, 14):
            v = ws.cell(row, col).value
            if v:
                ws.cell(row, col).hyperlink = v
                ws.cell(row, col).value = 'відкрити'
                ws.cell(row, col).font = Font(color='1F4E79', underline='single')
        ws.row_dimensions[row].height = 30
        for c in ws[row]:
            c.alignment = Alignment(vertical='top', wrap_text=(c.column == 10))
    widths = [11, 15, 12, 14, 16, 14, 26, 22, 16, 80, 16, 16, 9, 9, 10, 7]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = f'A1:{get_column_letter(len(head))}{ws.max_row}'
    # довідка
    ws2 = wb.create_sheet('Довідка')
    for line in ['Практика Верховного Суду: зразкові справи, Велика Палата, об\'єднані палати, палати',
                 'Укладач: В\'ячеслав Плескач. Джерело: lpd.court.gov.ua (неофіційна копія).',
                 'Текст позиції (і резюме — для позицій понад 200 слів) — у примітці до комірки «Позиція»: наведіть курсор.',
                 'Класифікація (юрисдикція, тип, галузь) — автоматична; «Перевірено: так» — після ручної перевірки.', '',
                 'Галузі:'] + [f'{c} — {n}' for g in tx['taksonomiia'].values() for c, n in g]:
        ws2.append([line])
    ws2.column_dimensions['A'].width = 110
    out = os.path.join(DATA, 'praktyka_VS_vyshchi_rivni.xlsx')
    wb.properties.creator = "В'ячеслав Плескач"
    wb.save(out)
    print(out, len(rows), 'рядків')


if __name__ == '__main__':
    main()
