#!/usr/bin/env python3
"""Інтерактивна сторінка практики ВС вищих рівнів (GitHub Pages): docs/index.html + docs/dani.json.

Автор: В'ячеслав Плескач

  python3 scripts/klasyfikatsiia.py && python3 scripts/storinka.py
"""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DOCS = os.path.join(ROOT, 'docs')


def main():
    pos = {}
    for l in open(os.path.join(DATA, 'pozytsii.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        if r['riven'] <= 4:
            pos[r['id']] = r
    tx = json.load(open(os.path.join(DATA, 'taksonomiia.json'), encoding='utf-8'))
    out = []
    for l in open(os.path.join(DATA, 'klasyfikatsiia.jsonl'), encoding='utf-8'):
        k = json.loads(l)
        r = pos.get(k['id'])
        if not r:
            continue
        out.append({
            'i': r['id'], 'd': k.get('data') or r['data_rishennia'] or '', 'ms': k.get('sprava') or '', 'r': r['riven'], 's': r['sud'] or '', 'y': k['yurysdyktsiia'],
            't': k['typ'], 'pt': k.get('pidtyp') or '', 'h': k['haluz'], 'c': k['chynnist'], 'n': r['nazva'], 'x': r['tekst'],
            'z': k.get('rezyume') or '', 'p': r['poznachka'] or '', 'v': k['dzherelo'] == 'перевірено',
            'rb': r['rubryky'][:3],
            'ds': [[d.get('sprava') or '', d.get('data') or '', d.get('provadzhennia') or '', d.get('sklad') or '', d.get('doc_id') or ''] for d in r['rishennia']],
            'vu': [[x.get('sprava') or '', x.get('data') or '', x.get('sklad') or '', x.get('sud') or '', x.get('doc_id') or '',
                    x.get('nadiinist') or '', (x.get('pozytsii') or [''])[0]] for x in (r.get('vidstupleno_u') or [])[:2]],
        })
    out.sort(key=lambda x: (x['d'], x['i']), reverse=True)
    os.makedirs(DOCS, exist_ok=True)
    meta = {'onovleno': dt.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y'), 'taksonomiia': tx['taksonomiia'], 'typy': tx['typy']}
    json.dump({'meta': meta, 'p': out}, open(os.path.join(DOCS, 'dani.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    open(os.path.join(DOCS, 'index.html'), 'w', encoding='utf-8').write(HTML)
    open(os.path.join(DOCS, '.nojekyll'), 'w').write('')
    print('позицій на сторінці:', len(out))
    import indeksy_haluzi
    indeksy_haluzi.main()


HTML = r'''<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Практика Верховного Суду: зразкові справи, Велика Палата, об'єднані палати, палати</title>
<meta name="author" content="В'ячеслав Плескач">
<style>
:root{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1b;--mute:#6b6a66;--line:#e4e2dc;--acc:#1f4e79;--acc2:#e8eef5;
--r1:#7a1f1f;--r2:#1f4e79;--r3:#3d6b35;--r4:#7a5a12;--warn:#a33;--ok:#3d6b35}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:20px 24px 8px;max-width:1200px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px;font-weight:650}
.sub{color:var(--mute);font-size:13px}
.wrap{max-width:1200px;margin:0 auto;padding:0 24px 40px}
.filters{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:grid;grid-template-columns:2fr repeat(5,1fr);gap:8px}
.filters input,.filters select{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;font:inherit;font-size:14px}
.chips{grid-column:1/-1;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:3px 11px;font-size:13px;cursor:pointer;user-select:none}
.chip.on{background:var(--acc);border-color:var(--acc);color:#fff}
.count{margin-left:auto;color:var(--mute);font-size:13px}
.list{margin-top:10px}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:6px 0}
details[open]{box-shadow:0 1px 6px rgba(0,0,0,.06)}
summary{list-style:none;cursor:pointer;padding:10px 14px;display:grid;grid-template-columns:86px 1fr;gap:4px 12px}
summary::-webkit-details-marker{display:none}
.date{color:var(--mute);font-size:13px;font-variant-numeric:tabular-nums}
.title{font-weight:560;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
details[open] .title{-webkit-line-clamp:unset}
.meta{grid-column:2;display:flex;gap:6px;flex-wrap:wrap;font-size:12px}
.b{padding:1px 8px;border-radius:4px;background:var(--acc2);color:var(--acc)}
.b.r1{background:#f6e7e7;color:var(--r1)}.b.r2{background:#e8eef5;color:var(--r2)}.b.r3{background:#e9f1e6;color:var(--r3)}.b.r4{background:#f5efe1;color:var(--r4)}
.b.c1{background:#fbe9e9;color:var(--warn)}.b.c2{background:#fdf3e1;color:#8a5a00}
.b.g{background:#f0efeb;color:#4a4945}
.body{padding:0 14px 14px 112px;border-top:1px solid var(--line)}
.body h4{margin:12px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);font-weight:600}
.body p{margin:4px 0;white-space:pre-line}
.docs a{color:var(--acc)}
.docs div{font-size:13px;margin:2px 0}
.more{display:block;margin:14px auto;padding:8px 18px;border:1px solid var(--acc);background:#fff;color:var(--acc);border-radius:6px;cursor:pointer;font:inherit}
mark{background:#fff2a8;padding:0 1px}
.note{font-size:12px;color:var(--mute)}
@media(max-width:800px){.filters{grid-template-columns:1fr 1fr}.body{padding-left:14px}summary{grid-template-columns:1fr}.meta{grid-column:1}}
</style>
</head>
<body>
<header>
<h1>Практика Верховного Суду: зразкові справи, Велика Палата, об'єднані палати, палати</h1>
<div class="sub" id="sub">Завантаження…</div>
</header>
<div class="wrap">
<div class="filters">
 <input id="q" type="search" placeholder="Пошук у назві й тексті позиції (кілька слів — усі мають бути; * — будь-яке закінчення)">
 <select id="sud"><option value="">Усі суди</option></select>
 <select id="yur"><option value="">Усі юрисдикції</option></select>
 <select id="typ"><option value="">Усі типи питань</option></select>
 <select id="hal"><option value="">Усі галузі</option></select>
 <select id="ch"><option value="">Будь-яка чинність</option><option>чинна</option><option>містить відступ</option><option>від неї відступлено</option></select>
 <div class="chips" id="rv"></div>
</div>
<div class="list" id="list"></div>
<button class="more" id="more" hidden>Показати ще</button>
<p class="note">Джерело — База правових позицій Верховного Суду (lpd.court.gov.ua). Класифікацію (юрисдикція, тип питання, галузь) виконано автоматично й перевірено вибірково; позначка «перевірено» — після ручної перевірки. Резюме — для позицій понад 200 слів; для коротших показано текст позиції. Укладач: В'ячеслав Плескач. Неофіційна копія; чинний текст — на lpd.court.gov.ua і в ЄДРСР.</p>
</div>
<script>
const R={1:'Зразкова справа',2:'Велика Палата',3:"Об'єднана палата",4:'Палата'};
let D=[],M={},HN={},shown=0,cur=[];const PAGE=60;
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fd=d=>d?d.slice(8,10)+'.'+d.slice(5,7)+'.'+d.slice(0,4):'';
let rv=new Set([1,2,3,4]);
function pats(q){return q.trim().split(/\s+/).filter(Boolean).map(t=>{const st=t.endsWith('*');t=t.replace(/\*$/,'').replace(/[.*+?^${}()|[\]\\]/g,'\\$&');return new RegExp((st?t+'[\\p{L}\\d]*':t),'iu')})}
function hl(s,ps){s=esc(s);for(const p of ps){s=s.replace(new RegExp(p.source,'giu'),m=>'<mark>'+m+'</mark>')}return s}
function apply(){
 const ps=pats($('q').value),sud=$('sud').value,yur=$('yur').value,typ=$('typ').value,hal=$('hal').value,ch=$('ch').value;
 cur=D.filter(x=>rv.has(x.r)&&(!sud||x.s===sud)&&(!yur||x.y===yur)&&(!typ||x.t===typ)&&(!hal||x.h.includes(hal))&&(!ch||x.c===ch)
  &&ps.every(p=>p.test(x.n)||p.test(x.x)||p.test(x.z)));
 $('list').innerHTML='';shown=0;more();
 $('cnt').textContent='Знайдено: '+cur.length;
}
function card(x,ps){
 const hs=x.h.map(h=>`<span class="b g" title="${esc(HN[h]||h)}">${esc((HN[h]||h).replace(/ \(.*\)$/,''))}</span>`).join('');
 const vu=(x.vu||[]).map(v=>`<div>${esc(v[2]==='палата'?'палата':v[2])}${v[3]&&v[3]!=='Велика Палата'&&v[2]!=='ВП'?' '+esc(v[3]):''} · ${esc(fd(v[1]))} · справа № ${esc(v[0])}${v[4]?` · <a href="https://reyestr.court.gov.ua/Review/${v[4]}" target="_blank" rel="noopener">ЄДРСР</a>`:''}${v[6]?` · <a href="https://lpd.court.gov.ua/legal-position/${v[6]}" target="_blank" rel="noopener">позиція #${v[6]}</a>`:''}${v[5]==='ймовірно'?' <span class="note">(ймовірно: справу згадано в постанові з відступом)</span>':''}</div>`).join('');
 const vub=x.c==='від неї відступлено'?`<h4>Відступлено в постанові</h4><div class="docs">${vu||'<div class="note">Постанову не встановлено — див. lpd.court.gov.ua</div>'}</div>`:'';
 const cb=x.c==='від неї відступлено'?`<span class="b c1">від неї відступлено${x.vu&&x.vu[0]?' · '+esc(fd(x.vu[0][1]))+' № '+esc(x.vu[0][0]):''}</span>`:x.c==='містить відступ'?'<span class="b c2">містить відступ</span>':'';
 const docs=x.ds.sort((a,b)=>(b[0]===x.ms&&b[1]===x.d)-(a[0]===x.ms&&a[1]===x.d)).map(d=>`<div${d[0]===x.ms&&d[1]===x.d?' style="font-weight:600"':''}>${esc(fd(d[1]))} · справа № ${esc(d[0])}${d[2]?' · провадження № '+esc(d[2]):''}${d[3]?' · '+esc(d[3]):''}${d[4]?` · <a href="https://reyestr.court.gov.ua/Review/${d[4]}" target="_blank" rel="noopener">ЄДРСР</a>`:''}</div>`).join('');
 const res=x.z?`<h4>Резюме</h4><p>${hl(x.z,ps)}</p><h4>Повний текст позиції</h4><p>${hl(x.x,ps)}</p>`:`<h4>Позиція</h4><p>${hl(x.x,ps)}</p>`;
 return `<details><summary><span class="date">${fd(x.d)}</span><span class="title">${hl(x.n,ps)}</span>
 <span class="meta"><span class="b r${x.r}">${R[x.r]}</span>${x.s!==R[x.r]?`<span class="b">${esc(x.s)}</span>`:`<span class="b">${esc(x.y)}</span>`}<span class="b">${esc(M.typy[x.t]||x.t)}${x.pt?': '+esc(x.pt):''}</span>${hs}${cb}${x.v?'<span class="b g">перевірено</span>':''}</span></summary>
 <div class="body">${res}${vub}<h4>Рішення</h4><div class="docs">${docs}</div><h4>Юрисдикція · рубрики lpd</h4><p class="note">${esc(x.y)} · ${esc(x.rb.join('; '))}</p>
 <p class="docs"><a href="https://lpd.court.gov.ua/legal-position/${x.i}" target="_blank" rel="noopener">Позиція на lpd.court.gov.ua (#${x.i})</a></p></div></details>`;
}
function more(){const ps=pats($('q').value);const part=cur.slice(shown,shown+PAGE);$('list').insertAdjacentHTML('beforeend',part.map(x=>card(x,ps)).join(''));shown+=part.length;$('more').hidden=shown>=cur.length}
function opt(sel,vals){for(const [v,t] of vals){const o=document.createElement('option');o.value=v;o.textContent=t;$(sel).appendChild(o)}}
fetch('dani.json').then(r=>r.json()).then(j=>{
 D=j.p;M=j.meta;
 $('sub').innerHTML=`${D.length} позицій · оновлено ${esc(M.onovleno)} · від нових до старих`;
 opt('sud',[...new Set(D.map(x=>x.s))].sort().map(v=>[v,v]));
 opt('yur',[...new Set(D.map(x=>x.y))].sort().map(v=>[v,v]));
 opt('typ',Object.entries(M.typy));
 for(const [g,l] of Object.entries(M.taksonomiia)){const og=document.createElement('optgroup');og.label=g;for(const [c,n] of l){HN[c]=n;const o=document.createElement('option');o.value=c;o.textContent=n+' ('+D.filter(x=>x.h.includes(c)).length+')';og.appendChild(o)}$('hal').appendChild(og)}
 $('rv').innerHTML=[1,2,3,4].map(k=>`<span class="chip on" data-k="${k}">${R[k]} (${D.filter(x=>x.r===k).length})</span>`).join('')+'<span class="count" id="cnt"></span>';
 $('rv').querySelectorAll('.chip').forEach(c=>c.onclick=()=>{const k=+c.dataset.k;rv.has(k)?rv.delete(k):rv.add(k);c.classList.toggle('on');apply()});
 ['sud','yur','typ','hal','ch'].forEach(id=>$(id).onchange=apply);
 let t;$('q').oninput=()=>{clearTimeout(t);t=setTimeout(apply,250)};
 $('more').onclick=more;apply();
}).catch(e=>{$('sub').textContent='Не вдалося завантажити дані: '+e});
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
