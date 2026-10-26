# -*- coding: utf-8 -*-
"""
build_report.py — يبني تقرير مدرك التفاعلي (صفحة HTML واحدة بلا اعتماد على الإنترنت) ونسخة PDF.

كل رقم في التقرير يُقرأ من جداول التحليل؛ لا شيء يُكتب باليد.
  python build_report.py --tables outputs/tables --log outputs/analysis_decisions_log.csv --out outputs
المخرجات: outputs/report.html  و  outputs/report.pdf   (--no-pdf لتخطي الـPDF)
"""
import argparse, datetime, json, re, sys, threading
from html import escape as html_escape
from pathlib import Path
import pandas as pd


def read(p): return pd.read_csv(p, encoding='utf-8-sig')


def collect(tables, log_path, challenges_path=None):
    t = Path(tables)
    rate, gaps, dm = read(t / 'rate_per100k_region_group.csv'), read(t / 'gaps_ranked.csv'), read(t / 'decision_matrix.csv')
    reg = read(t / 'region_summary.csv')
    log = read(log_path) if log_path and Path(log_path).exists() else pd.DataFrame(columns=['item', 'value', 'detail'])
    demand = read(t / 'demand_pressure.csv') if (t / 'demand_pressure.csv').exists() else None   # اختياري: عدسة الطلب
    fc = {k: read(t / f'{k}.csv') for k in ('forecast_2030_regions', 'forecast_2030_cells', 'forecast_log') if (t / f'{k}.csv').exists()}   # اختياري: فجوة 2030
    chal = read(challenges_path) if challenges_path and Path(challenges_path).exists() else None
    return rate, gaps, dm, reg, log, demand, chal, fc


def build_data(rate, gaps, dm, reg, log, demand=None, chal=None, fc=None):
    reg = reg.rename(columns={reg.columns[0]: 'region'})
    nat_total = int(reg.associations.sum()); nat_pop = int(reg.population_2022.sum())
    nat_rate = nat_total / nat_pop * 1e5
    regions = reg.sort_values('per_100k_all_groups').to_dict('records')
    groups = list(dict.fromkeys(rate.group))
    cells = dm.astype(object).where(dm.notna(), None).to_dict('records')     # NaN ← None (null في JS)
    prio = dm[(dm.recommendation == 'أولوية دعم')]
    conf = prio[prio.confidence == 'كافية'].sort_values('missing_to_reach_national', ascending=False)
    shortfall = (rate.groupby('region').missing_to_reach_national.sum().round(1))
    short = []
    for r in reg.sort_values('per_100k_all_groups').region:
        top = rate[rate.region == r].sort_values('missing_to_reach_national', ascending=False).head(3)
        short.append(dict(region=r, missing=float(shortfall[r]),
                          top=[dict(group=x.group, missing=float(x.missing_to_reach_national)) for x in top.itertuples() if x.missing_to_reach_national > 0]))
    D = dict(nat_total=nat_total, nat_pop=nat_pop, nat_rate=round(nat_rate, 2), regions=regions, groups=groups, cells=cells, shortfall=short,
             n_prio=int(len(prio)), n_prio_conf=int(len(conf)), n_ok=int((dm.recommendation == 'تغطية مناسبة').sum()), n_high=int((dm.recommendation == 'تغطية عالية').sum()),
             conf_top=conf.head(5).to_dict('records'), gaps=gaps.to_dict('records'),
             decisions=log.fillna('').to_dict('records'))
    D['demand'] = demand.to_dict('records') if demand is not None else None
    D['challenges'] = chal.to_dict('records') if chal is not None else None
    D['fc'] = None
    if fc and len(fc) == 3:
        fr = fc['forecast_2030_regions'].rename(columns={fc['forecast_2030_regions'].columns[0]: 'region'})
        lg = dict(zip(fc['forecast_log'].step, fc['forecast_log'].value))
        cells = fc['forecast_2030_cells']; cells = cells[~cells.low_confidence.astype(str).str.lower().eq('true')]
        D['fc'] = dict(regions=fr.to_dict('records'), cells=cells.head(10).to_dict('records'), method=str(lg.get('method_chosen', '')),
                       err=float([v for k, v in lg.items() if k.startswith('backtest:') and str(lg.get('method_chosen')) in k][0]),
                       bias=float(lg.get('backtest_bias', 0)), pop2030=int(float(lg.get('kingdom_population_2030', 0))),
                       miss_today=float(fr.missing_today.sum()), miss_2030=float(fr.missing_2030.sum()))
    return D


def exec_summary(D):
    reg = D['regions']; lo = reg[0]; nat = D['nat_rate']
    items = [f'<b>الصورة العامة:</b> {D["nat_total"]:,} جمعية أهلية مصنفة موزعة على {len(reg)} منطقة، بمتوسط وطني {nat} جمعية لكل 100 ألف نسمة.',
             f'<b>أقل المناطق تغطية:</b> {lo["region"]} ({lo["per_100k_all_groups"]} لكل 100 ألف)، ثم {reg[1]["region"]} ({reg[1]["per_100k_all_groups"]}) و{reg[2]["region"]} ({reg[2]["per_100k_all_groups"]}).',
             (f'<b>مصفوفة القرار:</b> {D["n_prio"]} خانة (منطقة × تخصص) بتوصية «أولوية دعم»، {f'منها {D["n_prio_conf"]} بأرقام كافية، والباقي «أرقام قليلة» يُعدّ مؤشراً أولياً.' if D["n_prio_conf"] < D["n_prio"] else ('كلها' if D["n_prio"] > 1 else 'وهي') + ' بأرقام كافية.'} و{D["n_ok"]} «تغطية مناسبة» و{D["n_high"]} «تغطية عالية».' if D["n_prio"] else
              f'<b>مصفوفة القرار:</b> لا توجد خانة (منطقة × تخصص) بتوصية «أولوية دعم»؛ {D["n_ok"]} «تغطية مناسبة» و{D["n_high"]} «تغطية عالية».')]
    if D['conf_top']:
        tp = D['conf_top'][0]
        items.append(f'<b>أكبر فجوة بأرقام كافية:</b> {tp["group"]} في {tp["region"]}: {tp["associations"]} جمعية مقابل ≈{tp["associations"] + tp["missing_to_reach_national"]:.0f} لو بلغت المتوسط الوطني (الناقص ≈{tp["missing_to_reach_national"]:.0f}).')
    if D['demand']:
        hi = [d['group'] for d in D['demand'] if d['demand_level'] == 'ضغط مرتفع']
        moved = [c for c in D['cells'] if c.get('demand_rank') == c.get('demand_rank') and c.get('demand_rank') and c.get('priority_rank') == c.get('priority_rank') and c.get('priority_rank') and c['priority_rank'] - c['demand_rank'] >= 2]
        txt = f'<b>عدسة الطلب (مسح 2018):</b> تخصصات عليها طلب أكبر من حجمها: {"، ".join(hi)}.'
        if moved:
            m = max(moved, key=lambda c: c['priority_rank'] - c['demand_rank'])
            txt += f' وبإضافة الطلب ترتفع أولوية {m["group"]} في {m["region"]} من المرتبة {int(m["priority_rank"])} إلى {int(m["demand_rank"])}.'
        items.append(txt)
    if D['fc']:
        F = D['fc']; top = sorted(F['regions'], key=lambda r: -r['missing_2030'])[:2]
        items.append(f'<b>فجوة 2030 (سيناريو):</b> مع نمو السكان إلى ≈{F["pop2030"] / 1e6:.1f} مليون، يرتفع مجموع الجمعيات الناقصة لبلوغ المتوسط الوطني من ≈{F["miss_today"]:,.0f} اليوم إلى ≈{F["miss_2030"]:,.0f}، أكبرها في {top[0]["region"]} (≈{top[0]["missing_2030"]:,.0f}) و{top[1]["region"]} (≈{top[1]["missing_2030"]:,.0f}).')
    return '\n'.join(f'<li>{i}</li>' for i in items)


CSS = r'''
:root{--bg:#fff;--fg:#1d2b33;--mut:#55656d;--line:#dfe6e9;--teal:#1F4E5F;--or:#D95F02;--bl:#2166AC;--gr:#ECEFF1;--card:#f6f9fa}
@media (prefers-color-scheme:dark){:root:not([data-print]){--bg:#14191c;--fg:#e6ecef;--mut:#9fb0b8;--line:#2b363b;--gr:#2a3338;--card:#1b2226}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font-family:"Segoe UI",Tahoma,Arial,"DejaVu Sans",sans-serif;line-height:1.7}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 60px}
header{border-bottom:3px solid var(--teal);padding-bottom:10px;margin-bottom:18px}
h1{font-size:26px;margin:0}h2{font-size:19px;margin:34px 0 4px;color:var(--teal)}h3{font-size:15px;margin:18px 0 4px}
.sub{color:var(--mut);font-size:13px}.note{color:var(--mut);font-size:12.5px;margin:4px 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.sum li{margin:6px 0}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}.kpi b{display:block;font-size:24px;color:var(--teal)}.kpi span{font-size:12.5px;color:var(--mut)}
.row{display:flex;align-items:center;gap:10px;margin:5px 0;font-size:13px}.row .l{width:150px;flex:none;font-weight:600}
.track{position:relative;flex:1;height:18px;background:var(--gr);border-radius:4px}.fill{height:100%;border-radius:4px}.mark{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--fg)}
.row .v{width:70px;flex:none;text-align:left;direction:ltr;font-variant-numeric:tabular-nums}
.cols{display:flex;align-items:flex-end;gap:6px;height:230px;margin:14px 0 0;padding-bottom:0;border-bottom:1px solid var(--line)}
.col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}.col .b{width:100%;background:var(--teal);border-radius:4px 4px 0 0;min-height:2px}.col small{font-size:10px;color:var(--mut);margin-bottom:2px}
.xl{display:flex;gap:6px}.xl div{flex:1;font-size:11px;text-align:center;color:var(--mut);padding-top:4px}
table.m{border-collapse:separate;border-spacing:2px;font-size:11.5px;width:100%}table.m th{background:var(--teal);color:#fff;padding:6px 4px;font-weight:600;font-size:11px}
table.m td{text-align:center;padding:9px 3px;border:2px solid transparent;border-radius:3px;cursor:default}table.m td.r{background:var(--card);font-weight:600;text-align:right;padding-right:8px;white-space:nowrap}
td.few{border:2px dashed var(--fg)!important}td.p{background:var(--or);color:#fff}td.o{background:var(--gr);color:var(--fg)}td.h{background:var(--bl);color:#fff}
.dim td.p,.dim td.o,.dim td.h{opacity:.15}.dim.fp td.p,.dim.fo td.o,.dim.fh td.h{opacity:1}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.chip{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:4px 12px;border-radius:999px;font-size:12.5px;cursor:pointer;font-family:inherit}
.chip.on{background:var(--teal);color:#fff;border-color:var(--teal)}.sw{display:inline-block;width:12px;height:12px;border-radius:2px;margin-left:5px;vertical-align:-1px}
table.t{border-collapse:collapse;width:100%;font-size:13px}table.t th{background:var(--teal);color:#fff;text-align:right;padding:6px 8px}table.t td{padding:6px 8px;border-bottom:1px solid var(--line)}
select,button.dl{font-family:inherit;font-size:13px;padding:4px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg)}button.dl{cursor:pointer}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:760px){.grid2{grid-template-columns:1fr}.row .l{width:110px}}
#tip{position:fixed;pointer-events:none;background:#12212a;color:#fff;padding:8px 10px;border-radius:6px;font-size:12px;line-height:1.6;max-width:280px;z-index:9;display:none;box-shadow:0 4px 14px #0004}
svg text{font-family:inherit}.lim li{margin:5px 0}footer{margin-top:40px;color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:10px}
#sim .ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}#sim input[type=number]{width:80px;font-family:inherit;font-size:13px;padding:4px 6px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
.btn{font-family:inherit;font-size:13px;padding:5px 12px;border-radius:6px;border:1px solid var(--teal);background:var(--teal);color:#fff;cursor:pointer}.btn.g{background:var(--card);color:var(--fg);border-color:var(--line)}
td.add{outline:3px solid #0b7a5a;outline-offset:-3px}td .chg{font-size:10px;display:block;opacity:.9}.alloc span{display:inline-block;background:var(--card);border:1px solid var(--line);border-radius:999px;padding:2px 10px;margin:3px;font-size:12.5px}.alloc b{cursor:pointer;color:var(--or);margin-right:6px}
.delta{font-size:12px;color:var(--mut)}
@media print{#s-sim{display:none!important}.wrap{max-width:none;padding:0}.chips,select,button.dl,.noprint{display:none!important}.card,.kpi,tr,.row{break-inside:avoid}h2{break-after:avoid}body{font-size:12.5px}.cols{height:170px}}
'''

JS = r'''
const D = __DATA__;
const $ = (s, r=document) => r.querySelector(s);
const tip = $('#tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.display='block'; const w=tip.offsetWidth, x=Math.min(Math.max(8,e.clientX-w/2), innerWidth-w-8); tip.style.left=x+'px'; tip.style.top=(e.clientY+16)+'px'; }
function hideTip(){ tip.style.display='none'; }
function hover(el, fn){ el.addEventListener('mousemove', e=>showTip(e, fn())); el.addEventListener('mouseleave', hideTip); }
function h(tag, cls, html){ const e=document.createElement(tag); if(cls) e.className=cls; if(html!==undefined) e.innerHTML=html; return e; }
const f1 = x => (+x).toLocaleString('en',{maximumFractionDigits:1}), f2 = x => (+x).toLocaleString('en',{maximumFractionDigits:2});
const LAB = {p:'أولوية دعم', o:'تغطية مناسبة', h:'تغطية عالية'}; const CLS = {'أولوية دعم':'p','تغطية مناسبة':'o','تغطية عالية':'h'};

// ---- KPIs
$('#kpis').innerHTML = [[D.nat_total.toLocaleString('en'),'جمعية مصنفة محسوبة'],[D.nat_rate,'جمعية لكل 100 ألف (وطنياً)'],[D.n_prio,'خانة «أولوية دعم» ('+D.n_prio_conf+' بأرقام كافية)']].map(k=>`<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span></div>`).join('');

function unavailable(id, what){ const s=document.getElementById(id); const h2=s.querySelector('h2').outerHTML; s.innerHTML=h2+`<div class="card note">غير متوفر لهذه البيانات: لم يُزوَّد ${what}. القسم يظهر تلقائياً عند إضافته.</div>`; }

// ---- 1) تغطية المناطق (أشرطة أفقية)
(function(){ const box=$('#c-regions'), mx=Math.max(...D.regions.map(r=>r.per_100k_all_groups), D.nat_rate)*1.05;
  D.regions.forEach(r=>{ const row=h('div','row'); const below=r.per_100k_all_groups<D.nat_rate;
    row.innerHTML=`<div class="l">${r.region}</div><div class="track"><div class="fill" style="width:${r.per_100k_all_groups/mx*100}%;background:${below?'var(--or)':'var(--bl)'}"></div><div class="mark" style="right:${D.nat_rate/mx*100}%"></div></div><div class="v">${f2(r.per_100k_all_groups)}</div>`;
    hover(row,()=>`<b>${r.region}</b><br>${r.associations.toLocaleString('en')} جمعية · ${r.population_2022.toLocaleString('en')} نسمة<br>${f2(r.per_100k_all_groups)} لكل 100 ألف (${f2(r.index_vs_national)}× المتوسط الوطني)<br>تخصصات تحت نصف المتوسط: ${r.groups_below_half_national}`);
    box.appendChild(row); });
})();

// ---- 2) مصفوفة القرار
(function(){ const regs=D.regions.map(r=>r.region), idx={}; D.cells.forEach(c=>idx[c.region+'|'+c.group]=c);
  const DL={}; (D.demand||[]).forEach(d=>DL[d.group]=d);
  let html='<tr><th>المنطقة</th>'+D.groups.map(g=>`<th data-g="${g}">${g}${DL[g]&&DL[g].demand_level==='ضغط مرتفع'?' ▲':''}</th>`).join('')+'</tr>';
  regs.forEach(r=>{ html+=`<tr><td class="r">${r}</td>`+D.groups.map(g=>{ const c=idx[r+'|'+g]; return `<td class="${CLS[c.recommendation]}${c.confidence!=='كافية'?' few':''}" data-k="${r}|${g}">${c.recommendation}</td>`;}).join('')+'</tr>'; });
  const t=$('#matrix'); t.innerHTML=html;
  t.querySelectorAll('td[data-k]').forEach(td=>{ const c=idx[td.dataset.k]; hover(td,()=>`<b>${c.region} · ${c.group}</b><br>${c.associations} جمعية = ${f2(c.per_100k)} لكل 100 ألف<br>المتوسط الوطني للتخصص: ${f2(c.national_per_100k)} (المؤشر ${f2(c.index_vs_national)})<br>الناقص لبلوغ المتوسط: ≈${f1(c.missing_to_reach_national)}<br>الثقة: ${c.confidence}`+(c.demand_pressure!=null?`<br>ضغط الطلب على التخصص: ${f2(c.demand_pressure)} (${c.demand_level})`:'')); });
  t.querySelectorAll('th[data-g]').forEach(th=>{ const d=DL[th.dataset.g]; if(d) hover(th,()=>`<b>${d.group}</b><br>${f2(d.beneficiaries_share_pct)}% من المستفيدين مقابل ${f2(d.establishments_share_pct)}% من المنشآت<br>ضغط الطلب: ${f2(d.demand_pressure)} (${d.demand_level})`); });
  document.querySelectorAll('.chip[data-f]').forEach(b=>b.onclick=()=>{ document.querySelectorAll('.chip[data-f]').forEach(x=>x.classList.remove('on')); b.classList.add('on'); const f=b.dataset.f; t.className='m'; if(f!=='all') t.classList.add('dim','f'+f); });
})();

// ---- 3) أعمدة: الناقص لكل منطقة
(function(){ const box=$('#c-short'), mx=Math.max(...D.shortfall.map(s=>s.missing))*1.1||1, cols=h('div','cols'), xl=h('div','xl');
  D.shortfall.forEach(s=>{ const c=h('div','col'); c.innerHTML=`<small>${Math.round(s.missing)}</small><div class="b" style="height:${s.missing/mx*100}%"></div>`;
    hover(c,()=>`<b>${s.region}</b><br>مجموع الناقص لبلوغ المتوسط الوطني: ≈${f1(s.missing)} جمعية`+s.top.map(t=>`<br>· ${t.group}: ≈${f1(t.missing)}`).join(''));
    cols.appendChild(c); xl.appendChild(h('div','',s.region)); }); box.appendChild(cols); box.appendChild(xl); })();

// ---- 4) جدول أولويات
(function(){ const rows=D.cells.filter(c=>c.recommendation==='أولوية دعم').sort((a,b)=>(a.confidence==='كافية'?0:1)-(b.confidence==='كافية'?0:1)||b.missing_to_reach_national-a.missing_to_reach_national);
  $('#t-prio').innerHTML='<tr><th>المنطقة</th><th>التخصص</th><th>الجمعيات</th><th>لكل 100 ألف</th><th>المتوسط الوطني</th><th>الناقص ≈</th><th>الثقة</th></tr>'+rows.map(c=>`<tr><td>${c.region}</td><td>${c.group}</td><td>${c.associations}</td><td>${f2(c.per_100k)}</td><td>${f2(c.national_per_100k)}</td><td>${f1(c.missing_to_reach_national)}</td><td>${c.confidence}</td></tr>`).join(''); })();

// ---- عدسة الطلب
(function(){ if(!D.demand){ unavailable('s-demand','مسح منشآت القطاع غير الربحي (المستفيدون حسب التخصص)'); return; }
  const box=$('#c-demand'), mx=Math.max(...D.demand.map(d=>d.demand_pressure),1)*1.05, col={'ضغط مرتفع':'var(--or)','متوازن':'#9db8c2','ضغط منخفض':'var(--bl)'};
  D.demand.forEach(d=>{ const row=h('div','row'); row.innerHTML=`<div class="l" style="width:230px">${d.group}</div><div class="track"><div class="fill" style="width:${d.demand_pressure/mx*100}%;background:${col[d.demand_level]}"></div><div class="mark" style="right:${1/mx*100}%"></div></div><div class="v">${f2(d.demand_pressure)}×</div>`;
    hover(row,()=>`<b>${d.group}</b><br>${f2(d.beneficiaries_share_pct)}% من المستفيدين ÷ ${f2(d.establishments_share_pct)}% من المنشآت<br>${d.demand_level}`); box.appendChild(row); });
  const pr=D.cells.filter(c=>c.demand_rank!=null).sort((a,b)=>a.demand_rank-b.demand_rank);
  $('#t-demand').innerHTML='<tr><th>الترتيب بعد الطلب</th><th>قبل</th><th>المنطقة</th><th>التخصص</th><th>الناقص ≈</th><th>ضغط الطلب</th><th>الناقص مرجّحاً</th></tr>'+pr.map(c=>{const d=c.priority_rank-c.demand_rank, ar=d>0?`<span style="color:var(--or)">▲${d}</span>`:d<0?`<span style="color:var(--bl)">▼${-d}</span>`:'—'; return `<tr><td><b>${c.demand_rank}</b> ${ar}</td><td>${c.priority_rank}</td><td>${c.region}</td><td>${c.group}</td><td>${f1(c.missing_to_reach_national)}</td><td>${f2(c.demand_pressure)}</td><td>${f1(c.weighted_missing)}</td></tr>`;}).join('');
  if(D.challenges){ const cb=$('#c-chal'); [...D.challenges].sort((a,b)=>b.share_pct-a.share_pct).forEach((c,i)=>{ const row=h('div','row'); row.innerHTML=`<div class="l" style="width:250px">${c.challenge}</div><div class="track"><div class="fill" style="width:${c.share_pct/35*100}%;background:${i===0?'var(--or)':'var(--teal)'}"></div></div><div class="v">${f1(c.share_pct)}%</div>`; cb.appendChild(row); }); }
  else $('#chal-wrap').style.display='none';
})();

// ---- فجوة 2030
(function(){ if(!D.fc){ unavailable('s-2030','سلسلة السكان عبر السنوات'); return; } const F=D.fc;
  $('#fc-note').innerHTML=`الطريقة: <b>${F.method}</b>، اختيرت آلياً لأنها الأقل خطأً في <b>اختبار رجعي بلا تسريب</b> (تدريب على 2010–2018 وتوقع 2022 ثم المقارنة بالتعداد): متوسط الخطأ ${f2(F.err)}%. `+(F.bias>0?'الطريقة بالغت قليلاً في الاختبار، فأرقام 2030 أقرب إلى <b>حد أعلى</b>. ':'')+'المعيار: المتوسط الوطني الحالي لكل تخصص، والعدد الحالي للجمعيات ثابت. سيناريو للتخطيط وليس إسقاطاً رسمياً.';
  const R=[...F.regions].sort((a,b)=>b.missing_2030-a.missing_2030), mx=Math.max(...R.map(r=>r.missing_2030))*1.1||1, cols=h('div','cols'), xl=h('div','xl');
  R.forEach(r=>{ const c=h('div','col'); c.style.flexDirection='row'; c.style.alignItems='flex-end'; c.style.gap='2px';
    c.innerHTML=`<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%;align-items:center"><small>${Math.round(r.missing_today)}</small><div class="b" style="height:${r.missing_today/mx*100}%;background:#9db8c2"></div></div><div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%;align-items:center"><small>${Math.round(r.missing_2030)}</small><div class="b" style="height:${r.missing_2030/mx*100}%;background:var(--or)"></div></div>`;
    hover(c,()=>`<b>${r.region}</b><br>السكان: ${(+r.pop_2022).toLocaleString('en')} ← ${(+r.pop_2030).toLocaleString('en')} (+${r.growth_pct}%)<br>الناقص اليوم ≈${f1(r.missing_today)} ← 2030 ≈${f1(r.missing_2030)}<br>إضافي بسبب النمو ≈${f1(r.extra_by_2030)}`);
    cols.appendChild(c); xl.appendChild(h('div','',r.region)); }); $('#c-2030').append(cols, xl);
  $('#t-2030').innerHTML='<tr><th>المنطقة</th><th>التخصص</th><th>الجمعيات اليوم</th><th>المطلوب 2030</th><th>الناقص اليوم</th><th>الناقص 2030</th></tr>'+F.cells.map(c=>`<tr><td>${c.region}</td><td>${c.group}</td><td>${c.associations}</td><td>${f1(c.needed_2030)}</td><td>${f1(c.missing_to_reach_national)}</td><td><b>${f1(c.missing_2030)}</b></td></tr>`).join('');
})();

// ---- محاكي «ماذا لو؟»
(function(){
  const cfgv=k=>{const d=D.decisions.find(x=>x.item==='config:'+k); return d?+d.value:null;};
  const LOW=cfgv('low_ratio')??0.5, HIGH=cfgv('high_ratio')??1.5, MINR=cfgv('min_region_count')??3, MINN=cfgv('min_national_count')??30;
  const regs=D.regions.map(r=>r.region), POP={}; D.regions.forEach(r=>POP[r.region]=r.population_2022);
  const natPop=regs.reduce((a,r)=>a+POP[r],0), base={}; D.cells.forEach(c=>base[c.region+'|'+c.group]=c);
  const PRESS={}; (D.demand||[]).forEach(d=>PRESS[d.group]=d.demand_pressure);
  let adds={};
  function compute(A){ const natCnt={}; D.groups.forEach(g=>natCnt[g]=regs.reduce((a,r)=>a+base[r+'|'+g].associations+(A[r+'|'+g]||0),0));
    const out={}; regs.forEach(r=>D.groups.forEach(g=>{ const k=r+'|'+g, cnt=base[k].associations+(A[k]||0), nr=natCnt[g]/natPop*1e5, rate=cnt/POP[r]*1e5, idx=nr>0?Math.round(rate/nr*100)/100:0;   // نفس تقريب جدول التحليل (منزلتان) لتطابق التوصيات الأصلية
      out[k]={cnt,rate,idx,nr,rec:idx<LOW?'أولوية دعم':idx>=HIGH?'تغطية عالية':'تغطية مناسبة',few:cnt<MINR||natCnt[g]<MINN,miss:Math.max(nr*POP[r]/1e5-cnt,0)}; })); return out; }
  const B=compute({});
  const sumStats=S=>{ const v=Object.values(S); return {prio:v.filter(x=>x.rec==='أولوية دعم'&&!x.few).length, prioAll:v.filter(x=>x.rec==='أولوية دعم').length, miss:v.reduce((a,x)=>a+x.miss,0)}; };
  const rs=$('#sim-r'), gs=$('#sim-g'); rs.innerHTML=regs.map(r=>`<option>${r}</option>`).join(''); gs.innerHTML=D.groups.map(g=>`<option>${g}</option>`).join('');
  const first=D.cells.find(c=>c.recommendation==='أولوية دعم'&&c.confidence==='كافية'); if(first){ rs.value=first.region; gs.value=first.group; }
  function render(){ const S=compute(adds), b=sumStats(B), a=sumStats(S), n=Object.values(adds).reduce((x,y)=>x+y,0);
    $('#sim-kpi').innerHTML=[[n,'جمعية جديدة في السيناريو',''],[a.prio,'خانة «أولوية دعم» بأرقام كافية',`قبل: ${b.prio}`],[a.prioAll,'خانة «أولوية دعم» (الكل)',`قبل: ${b.prioAll}`],[Math.round(a.miss).toLocaleString('en'),'مجموع الناقص لبلوغ المتوسط',`قبل: ${Math.round(b.miss).toLocaleString('en')}`]].map(k=>`<div class="kpi"><b>${k[0]}</b><span>${k[1]}</span><div class="delta">${k[2]}</div></div>`).join('');
    $('#sim-alloc').innerHTML=n?Object.entries(adds).map(([k,v])=>`<span>${k.replace('|',' · ')}: +${v}<b data-k="${k}" title="حذف">✕</b></span>`).join(''):'<span>لا توجد إضافات بعد</span>';
    $('#sim-alloc').querySelectorAll('b[data-k]').forEach(x=>x.onclick=()=>{ delete adds[x.dataset.k]; render(); });
    let html='<tr><th>المنطقة</th>'+D.groups.map(g=>`<th>${g}</th>`).join('')+'</tr>';
    regs.forEach(r=>{ html+=`<tr><td class="r">${r}</td>`+D.groups.map(g=>{ const k=r+'|'+g, x=S[k], y=B[k], ch=x.rec!==y.rec; return `<td data-k="${k}" class="${CLS[x.rec]}${x.few?' few':''}${adds[k]?' add':''}">${x.rec}${ch?`<span class="chg">كانت: ${y.rec}</span>`:''}</td>`;}).join('')+'</tr>'; });
    const t=$('#sim-m'); t.innerHTML=html;
    t.querySelectorAll('td[data-k]').forEach(td=>{ const k=td.dataset.k, x=S[k], y=B[k]; hover(td,()=>`<b>${k.replace('|',' · ')}</b><br>الجمعيات: ${y.cnt} ← <b>${x.cnt}</b><br>لكل 100 ألف: ${f2(y.rate)} ← <b>${f2(x.rate)}</b><br>المؤشر: ${f2(y.idx)} ← <b>${f2(x.idx)}</b><br>الناقص: ≈${f1(y.miss)} ← <b>≈${f1(x.miss)}</b>`);
      td.onclick=()=>{ const [r,g]=k.split('|'); rs.value=r; gs.value=g; }; }); }
  $('#sim-add').onclick=()=>{ const k=rs.value+'|'+gs.value, n=Math.max(0,Math.round(+$('#sim-n').value||0)); if(n){ adds[k]=(adds[k]||0)+n; render(); } };
  $('#sim-reset').onclick=()=>{ adds={}; render(); };
  $('#sim-auto').onclick=()=>{ const N=Math.max(0,Math.round(+$('#sim-total').value||0)); adds={};
    for(let i=0;i<N;i++){ const S=compute(adds); let best=null,bv=Infinity; for(const k in S){ const x=S[k]; if(x.few||x.idx>=1) continue; const pw=$('#sim-dw').checked?Math.min(Math.max(PRESS[k.split('|')[1]]??1,0.5),2):1, v=x.idx/pw; if(best===null||v<bv){bv=v;best=k;} } if(!best) break; adds[best]=(adds[best]||0)+1; }
    render(); };
  render();
})();

// ---- 7) قرارات التحليل
const DEC={'config:exclude_national':'استبعاد الكيانات الوطنية من المناطق','config:exclude_unclassified':'استبعاد غير المصنف / المنشأة بأمر ملكي','config:foundations_as_support':'المؤسسات طبقة داعمة خارج المعدل','config:low_ratio':'حد «أولوية دعم» (نسبة إلى المتوسط الوطني)','config:high_ratio':'حد «تغطية عالية» (نسبة إلى المتوسط الوطني)','config:min_national_count':'أدنى عدد وطني للتخصص ليُعتمد','config:min_region_count':'أدنى عدد جمعيات في الخانة ليُعتمد','rows:Non_profit_Associations_clean.csv':'عدد الجمعيات بعد التنظيف','rows:Non_profit_Foundations_clean.csv':'عدد المؤسسات بعد التنظيف','population_total':'إجمالي السكان (تعداد 2022)','excluded_national_entities':'كيانات وطنية مستبعدة','excluded_unclassified':'جمعيات غير مصنفة مستبعدة','rows_in_rate':'جمعيات داخل الحساب','national_per_100k_all_groups':'المتوسط الوطني لكل 100 ألف','gaps_listed':'خانات أقل من نصف المتوسط','foundations_in_support_layer':'مؤسسات في الطبقة الداعمة'};
const yn=v=>v==='True'?'نعم':v==='False'?'لا':v;
$('#t-dec').innerHTML='<tr><th>البند</th><th>القيمة</th><th>التفصيل</th></tr>'+D.decisions.filter(d=>DEC[d.item]||d.item.startsWith('decision:')).map(d=>`<tr><td>${DEC[d.item]||('توصية: '+d.item.split(':')[1])}</td><td>${yn(String(d.value))}</td><td>${d.detail}</td></tr>`).join('');

// ---- تحميل CSV
function csv(rows){ const cols=Object.keys(rows[0]); return '﻿'+cols.join(',')+'\n'+rows.map(r=>cols.map(c=>{let v=r[c]; v=(v===null||v===undefined)?'':String(v); return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;}).join(',')).join('\n'); }
document.querySelectorAll('button.dl').forEach(b=>b.onclick=()=>{ const rows=D[b.dataset.k]; const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([csv(rows)],{type:'text/csv;charset=utf-8'})); a.download=b.dataset.n+'.csv'; a.click(); });
'''

HTML = '''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>مدرك — تقرير فجوات الخدمات</title><style>__CSS__</style></head><body><div class="wrap">
<header><h1>مدرك: أين تحتاج الخدمات غير الربحية دعماً أكثر؟</h1>
<div class="sub">تقرير آلي من بيانات مفتوحة (__SOURCES__) · أُنشئ في __DATE__</div></header>

<section><h2>الملخص التنفيذي</h2><div class="card"><ul class="sum" style="margin:0;padding-right:20px">__SUMMARY__</ul></div><div class="kpis" id="kpis"></div></section>

<section><h2>١. أين التغطية أقل؟</h2><div class="note">عدد الجمعيات المصنفة لكل 100 ألف نسمة حسب المنطقة. <span class="sw" style="background:var(--or)"></span>أقل من المتوسط الوطني <span class="sw" style="background:var(--bl)"></span>أعلى منه. الخط الأسود = المتوسط الوطني (__NAT__). مرّر الماوس على أي صف.</div><div class="card" id="c-regions"></div></section>

<section><h2>٢. مصفوفة القرار: منطقة × تخصص</h2>
<div class="note">كل خانة توصية مبنية على نسبة المعدل المحلي إلى المتوسط الوطني للتخصص. <b>أولوية دعم</b>: أقل من نصف المتوسط. <b>تغطية عالية</b>: أكثر من مرة ونصف، أي أن الدعم الجديد الأفضل في مكان آخر وليس أن المنطقة لا تحتاج. الإطار المنقط = <b>أرقام قليلة</b> (مؤشر أولي).</div>
<div class="chips"><button class="chip on" data-f="all">الكل</button><button class="chip" data-f="p"><span class="sw" style="background:var(--or)"></span>أولوية دعم</button><button class="chip" data-f="o"><span class="sw" style="background:var(--gr);border:1px solid var(--line)"></span>تغطية مناسبة</button><button class="chip" data-f="h"><span class="sw" style="background:var(--bl)"></span>تغطية عالية</button></div>
<div class="card" style="overflow-x:auto"><table class="m" id="matrix"></table></div></section>

<section><h2>٣. كم جمعية ناقصة؟</h2><div class="note">مجموع الجمعيات التي تنقص كل منطقة لتبلغ المتوسط الوطني في التخصصات التي تقل عنه. مؤشر تقريبي لحجم الفجوة، وليس هدفاً ملزماً.</div><div class="card" id="c-short"></div>
<h3>خانات «أولوية دعم» بالتفصيل</h3><div class="card" style="overflow-x:auto"><table class="t" id="t-prio"></table></div>
<p class="noprint"><button class="dl" data-k="cells" data-n="decision_matrix">تحميل مصفوفة القرار CSV</button> <button class="dl" data-k="gaps" data-n="gaps_ranked">تحميل الفجوات CSV</button></p></section>

<section id="s-demand"><h2>٤. عدسة الطلب: هل حجم التخصص يناسب طلبه؟</h2>
<div class="note"><b>ضغط الطلب</b> = حصة التخصص من المستفيدين ÷ حصته من المنشآت (مسح منشآت القطاع غير الربحي 2018، الهيئة العامة للإحصاء). أكبر من 1 = طلب أكبر من حجمه. الخط الأسود = 1 (توازن). المسح وطني وقديم نسبياً وبلا مناطق، فالعدسة <b>تعيد ترتيب</b> خانات «أولوية دعم» ولا تغيّر التوصية. ارتفاع «دعم العمل الخيري» قد يعكس احتساباً واسعاً للمستفيدين غير المباشرين. التخصصات المرتفعة معلّمة ▲ في المصفوفة.</div>
<div class="card" id="c-demand"></div>
<h3>ترتيب خانات «أولوية دعم» (بأرقام كافية) قبل وبعد عدسة الطلب</h3><div class="note">الناقص مرجّحاً = الجمعيات الناقصة × ضغط الطلب.</div><div class="card" style="overflow-x:auto"><table class="t" id="t-demand"></table></div>
<div id="chal-wrap"><h3>ماذا تقول المنشآت؟ أبرز التحديات (مسح 2018)</h3><div class="card" id="c-chal"></div></div></section>

<section id="s-2030"><h2>٥. فجوة 2030: كم جمعية تحتاج كل منطقة مع نمو السكان؟</h2>
<div class="note" id="fc-note"></div>
<div class="note"><span class="sw" style="background:#9db8c2"></span>الناقص اليوم <span class="sw" style="background:var(--or)"></span>الناقص في 2030 (مجموع التخصصات التي تقل عن المتوسط الوطني). مرّر الماوس على أي منطقة.</div>
<div class="card" id="c-2030"></div>
<h3>أكبر 10 خانات ناقصة في 2030 (بأرقام كافية)</h3><div class="card" style="overflow-x:auto"><table class="t" id="t-2030"></table></div></section>

<section id="s-sim"><h2>٦. جرّب بنفسك: محاكي «ماذا لو؟»</h2>
<div class="note">أضف جمعيات جديدة لمنطقة وتخصص، وشاهد كيف تتغير التوصيات والمؤشرات فوراً (يُعاد حساب المتوسط الوطني أيضاً). أو اطلب <b>توزيعاً مقترحاً</b>: كل جمعية تذهب للخانة الأقل تغطية نسبةً للمتوسط الوطني (ويمكن ترجيحها بضغط الطلب)، ثم يُعاد الحساب، مع تجاهل خانات «أرقام قليلة». أداة للتفكير وليست قراراً: العدد لا يعني جودة الخدمة.</div>
<div class="card" id="sim">
<div class="ctl"><label>المنطقة <select id="sim-r"></select></label><label>التخصص <select id="sim-g"></select></label><label>عدد الجمعيات <input id="sim-n" type="number" min="1" value="10"></label><button class="btn" id="sim-add">أضف للسيناريو</button><button class="btn g" id="sim-reset">إعادة ضبط</button></div>
<div class="ctl"><label>أو وزّع تلقائياً <input id="sim-total" type="number" min="1" value="50"> جمعية</label><label><input type="checkbox" id="sim-dw"> رجّح بضغط الطلب (محصور بين 0.5× و2×)</label><button class="btn" id="sim-auto">اقترح توزيعاً</button><span class="delta">اضغط أي خانة في الجدول لاختيارها.</span></div>
<div class="alloc" id="sim-alloc"></div><div class="kpis" id="sim-kpi"></div>
<div style="overflow-x:auto"><table class="m" id="sim-m"></table></div></div></section>

<section><h2>حدود التحليل</h2><div class="card"><ul class="lim" style="margin:0;padding-right:20px">
<li>المؤشر هو <b>عدد الجمعيات المسجلة</b>، وليس حجم الخدمة المقدمة أو أثرها. لا يقيس مدرك الأثر النهائي لعدم توفر بيانات النتائج.</li>
<li>المنطقة هي منطقة <b>التسجيل</b>، وقد تخدم الجمعية مناطق أخرى.</li>
<li>الخانات ذات العدد القليل (أقل من 3 جمعيات) أو التخصصات الصغيرة وطنياً (أقل من 30) تُعلَّم «أرقام قليلة» وتُعدّ مؤشراً أولياً.</li>
<li>التوصيات للمراجعة البشرية، وليست قراراً نهائياً. القرارات الثلاثة (استبعاد الوطني، استبعاد غير المصنف، المؤسسات كطبقة داعمة) إعدادات موثّقة بشرياً أدناه.</li></ul></div>
<h3>القرارات والأعداد المستبعدة</h3><div class="card" style="overflow-x:auto"><table class="t" id="t-dec"></table></div></section>

<footer>أُعدّ بالكامل بكود بايثون قابل لإعادة التشغيل من الملفات الخام (المصادر وروابطها في README). القرارات الإدارية بشرية، والمقترحات الآلية تُراجع قبل الاعتماد.</footer>
</div><div id="tip"></div><script>__JS__</script></body></html>'''


def to_pdf(html_path, pdf_path):
    res = {}
    def run():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1052, 'height': 900})
                pg.goto(Path(html_path).resolve().as_uri()); pg.evaluate("document.documentElement.setAttribute('data-print','1')")
                pg.emulate_media(media='print'); pg.pdf(path=str(pdf_path), width='1100px', height='1556px', print_background=True,
                                                         margin=dict(top='24px', bottom='24px', left='24px', right='24px')); b.close()
        except Exception as e: res['e'] = e
    t = threading.Thread(target=run); t.start(); t.join()
    if 'e' in res: print('تعذّر إنشاء PDF:', res['e'], file=sys.stderr); return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', required=True); ap.add_argument('--log'); ap.add_argument('--challenges'); ap.add_argument('--out', default='outputs')
    ap.add_argument('--no-pdf', action='store_true'); a = ap.parse_args()
    D = build_data(*collect(a.tables, a.log, a.challenges))
    # ملاحظة extra_limit تظهر في «حدود التحليل» بنصها كما كتبه الإنسان، فلا تتكرر في جدول القرارات (ولا يمسها استبدال الكلمات)
    xl = next((str(d['value']) for d in D['decisions'] if d['item'] == 'config:extra_limit'), None)
    D['decisions'] = [d for d in D['decisions'] if d['item'] != 'config:extra_limit']
    data = json.dumps(D, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, 'item') else str(o)).replace('</', '<\\/')
    src = ['سجل الكيانات غير الربحية', 'تعداد السكان'] + (['مسح منشآت القطاع غير الربحي 2018'] if D['demand'] else [])
    page = (HTML.replace('__CSS__', CSS).replace('__SOURCES__', '، '.join(src)).replace('__SUMMARY__', exec_summary(D)).replace('__NAT__', str(D['nat_rate']))
            .replace('__DATE__', datetime.date.today().strftime('%Y-%m-%d')).replace('__JS__', JS.replace('__DATA__', data)))
    lab = {d['item']: str(d['value']) for d in D['decisions']}
    cl, ul = lab.get('config:comparison_label'), lab.get('config:unit_label')
    if cl:      # تحليل داخل منطقة (محافظات): «المتوسط الوطني» يصبح متوسط المنطقة
        page = page.replace('بمتوسط وطني', 'ب' + cl).replace('المتوسط الوطني', cl).replace('(وطنياً)', '(' + cl + ')').replace('وطنياً', 'على مستوى ' + cl.replace('متوسط ', ''))
    if ul:
        pl = lab.get('config:unit_plural', 'المحافظات')
        page = page.replace('أقل المناطق', 'أقل ' + pl).replace(' منطقة، ب', ' ' + pl.removeprefix('ال') + '، ب').replace('<th>المنطقة</th>', f'<th>{ul}</th>').replace('حسب المنطقة', f'حسب {ul}').replace('لكل منطقة', f'لكل {ul}').replace('منطقة × تخصص', f'{ul} × تخصص')
    es, ep = lab.get('config:entity_singular'), lab.get('config:entity_plural')
    if es and ep:   # كيانات غير الجمعيات (مثل المساجد): تُستبدل الكلمات في نص التقرير فقط
        rep = {'جمعية مصنفة محسوبة': es + ' في الحساب', 'سجل الكيانات غير الربحية': 'ملف ال' + ep, 'جمعية أهلية مصنفة موزعة': 'من ال' + ep + ' موزعة',
               'الجمعيات الأهلية المصنفة': 'ال' + ep, 'الجمعيات الأهلية': 'ال' + ep, 'جمعية أهلية مصنفة': es, 'الجمعيات': 'ال' + ep, 'جمعيات': ep, 'جمعية': es}
        rep.update({ep: ep, es: es, 'ال' + ep: 'ال' + ep})   # ما هو مكتوب أصلاً بالكلمة الجديدة يبقى كما هو
        # مرور واحد (الأطول أولاً): الكلمة الجديدة لا يُعاد استبدالها، فلا يظهر «جمعيات تحفيظ تحفيظ» إذا احتوت الكلمة الجديدة على «جمعيات»
        pat = re.compile('|'.join(re.escape(k) for k in sorted(rep, key=len, reverse=True)))
        page = pat.sub(lambda m: rep[m.group(0)], page)
    if xl:          # حد خاص بنوع البيانات يكتبه الإنسان في config (مثل: عدد المساجد لا يعكس سعتها)
        page = page.replace('</ul></div>\n<h3>القرارات', f'<li><b>خاص بهذه البيانات:</b> {html_escape(xl)}</li></ul></div>\n<h3>القرارات', 1)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'report.html').write_text(page, encoding='utf-8'); print('تم: ', out / 'report.html')
    if not a.no_pdf and to_pdf(out / 'report.html', out / 'report.pdf'): print('تم: ', out / 'report.pdf')


if __name__ == '__main__':
    main()
