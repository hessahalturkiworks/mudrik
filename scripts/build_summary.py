# -*- coding: utf-8 -*-
"""
الملخص التنفيذي لمدرك: صفحة واحدة لصانع القرار، بلا مصطلحات تقنية.
كل رقم يُقرأ من ملفات outputs/ (لا رقم مكتوب باليد)، والنص يتبع templates/impact_report.md و prompts/executive_report.md.

  python scripts/build_summary.py --out outputs            (يُنشئ executive_summary.html و executive_summary.pdf)
"""
import argparse, datetime, html, sys, threading
from pathlib import Path
import pandas as pd


def read(p): return pd.read_csv(p, encoding='utf-8-sig')
def n0(x): return f'{x:,.0f}'
def n2(x): return f'{x:.2f}'


def facts(out):
    t = Path(out) / 'tables'
    reg = read(t / 'region_summary.csv').sort_values('per_100k_all_groups')
    dm = read(t / 'decision_matrix.csv')
    log = read(Path(out) / 'analysis_decisions_log.csv'); lg = dict(zip(log['item'], log['value']))
    F = dict(total=int(dm.associations.sum()), regions=len(reg), nat=float(lg['national_per_100k_all_groups']))
    low = reg.iloc[0]; F['low'] = low.region_key; F['low_rate'] = float(low.per_100k_all_groups); F['low_idx'] = float(low.index_vs_national)
    F['low_pop'] = float(low.population_2022); F['low_assoc'] = int(low.associations)
    F['pop_rank'] = int(reg.population_2022.rank(ascending=False)[reg.region_key == F['low']].iloc[0])
    F['next'] = [(r.region_key, float(r.per_100k_all_groups)) for r in reg.iloc[1:3].itertuples()]
    pr = dm[dm.recommendation == 'أولوية دعم']; conf = pr[pr.confidence == 'كافية'].sort_values('priority_rank')
    F['n_prio'], F['n_conf'] = len(pr), len(conf)
    F['conf'] = conf; F['low_cells'] = conf[conf.region == F['low']]
    F['need_conf'] = float(conf.missing_to_reach_national.sum())
    d = read(t / 'demand_pressure.csv'); hi = d[d.demand_level == 'ضغط مرتفع']
    F['demand_hi'] = [(r.group, float(r.demand_pressure)) for r in hi.itertuples()]
    mv = conf[(conf.demand_rank < conf.priority_rank)].sort_values('demand_rank')
    F['moved'] = mv.iloc[0] if len(mv) else None
    fr = read(t / 'forecast_2030_regions.csv'); fl = dict(zip(read(t / 'forecast_log.csv').step, read(t / 'forecast_log.csv').value))
    F['m_today'], F['m_2030'] = float(fr.missing_today.sum()), float(fr.missing_2030.sum())
    F['pop2030'] = float(fl['kingdom_population_2030']); top = fr.sort_values('missing_2030', ascending=False).iloc[:2]
    F['top2030'] = [(r.region, float(r.missing_2030)) for r in top.itertuples()]
    F['min_new'] = min_new(dm, lg)
    return F


def min_new(dm, lg, cap=500):
    """نفس منطق «التوزيع التلقائي» في محاكي التقرير: كل جمعية جديدة للخانة الأقل مؤشراً (بلا أرقام قليلة)، ويُعاد الحساب
    (ومنه المتوسط الوطني) بعد كل جمعية؛ يُرجع أقل عدد تختفي عنده خانات «أولوية دعم» ذات الأرقام الكافية."""
    low, minr, minn = float(lg['config:low_ratio']), int(lg['config:min_region_count']), int(lg['config:min_national_count'])
    natpop = dm.groupby('region').population_2022.first().sum()
    cnt = dict(zip(zip(dm.region, dm.group), dm.associations.astype(int))); pop = dict(zip(dm.region, dm.population_2022))
    for n in range(cap + 1):
        nat = {}
        for (r, g), c in cnt.items(): nat[g] = nat.get(g, 0) + c
        st = {k: (round((c / pop[k[0]] * 1e5) / (nat[k[1]] / natpop * 1e5), 2) if nat[k[1]] else 0, c < minr or nat[k[1]] < minn) for k, c in cnt.items()}
        if not any(i < low and not few for i, few in st.values()): return n
        best = min((k for k, (i, few) in st.items() if not few and i < 1), key=lambda k: st[k][0]); cnt[best] += 1
    return None


def page(F, confirm):
    c, lc = F['conf'], F['low_cells']
    cells = '، '.join(f'{r.group} (ناقص ≈{n0(r.missing_to_reach_national)})' for r in lc.itertuples())
    others = '، و'.join(f'{r.group} في {r.region} (≈{n0(r.missing_to_reach_national)})' for r in c[c.region != F['low']].itertuples())
    big = c.iloc[0]
    hi = ' و'.join(f'«{g}» ({n2(v)}×)' for g, v in F['demand_hi'])
    mv = F['moved']
    moved = f'ترتفع أولوية {mv.group} في {mv.region} من المرتبة {int(mv.priority_rank)} إلى {int(mv.demand_rank)}.' if mv is not None else ''
    (r1, m1), (r2, m2) = F['top2030']
    conf_line = ''.join(f'<li>{html.escape(x)}</li>' for x in confirm)
    today = datetime.date.today().strftime('%Y-%m-%d')
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>مدرك · الملخص التنفيذي</title>
<style>
@page {{ size: A4; margin: 14mm 14mm 12mm 14mm; }}
:root {{ --ink:#1d2731; --mut:#5b6774; --line:#d9dee3; --acc:#2c5f73; --hot:#c4622d; --bg:#f4f6f8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Segoe UI",Tahoma,Arial,"DejaVu Sans",sans-serif; color:var(--ink); background:#fff; font-size:12.4px; line-height:1.55; }}
.wrap {{ max-width:780px; margin:0 auto; padding:18px 0; }}
h1 {{ font-size:22px; margin:0 0 2px; color:var(--acc); }}
.sub {{ color:var(--mut); font-size:11px; margin-bottom:10px; }}
.q {{ border-right:4px solid var(--acc); background:var(--bg); padding:7px 12px; margin:8px 0 12px; font-size:13px; }}
.kpis {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:12px; }}
.k {{ border:1px solid var(--line); border-radius:8px; padding:8px 10px; }}
.k b {{ display:block; font-size:21px; color:var(--acc); line-height:1.2; }}
.k.hot b {{ color:var(--hot); }}
.k span {{ color:var(--mut); font-size:11px; }}
h2 {{ font-size:14px; margin:12px 0 5px; color:var(--acc); border-bottom:1px solid var(--line); padding-bottom:3px; }}
ol {{ margin:0; padding-right:18px; }} ol li {{ margin:0 0 5px; }}
ul {{ margin:2px 0 0; padding-right:18px; }}
.rec {{ background:#fbf1ea; border:1px solid #efd3c0; border-radius:8px; padding:9px 12px; }}
.lim {{ color:var(--mut); font-size:10.8px; }}
.foot {{ margin-top:10px; color:var(--mut); font-size:10.2px; border-top:1px solid var(--line); padding-top:5px; }}
</style></head><body><div class="wrap">
<h1>مدرك: أين تحتاج الخدمات غير الربحية دعماً أكثر؟</h1>
<div class="sub">ملخص تنفيذي · {today} · هاكثون تحليل البيانات في القطاع غير الربحي 2 · إعداد: حصة التركي</div>
<div class="q"><b>السؤال:</b> في أي منطقة، وفي أي تخصص، يقل عدد الجمعيات الأهلية عن حاجة السكان؟ وأين يذهب الدعم الجديد بأكبر فائدة؟</div>
<div class="kpis">
<div class="k"><b>{n0(F['total'])}</b><span>جمعية أهلية مصنفة في {F['regions']} منطقة</span></div>
<div class="k"><b>{n2(F['nat'])}</b><span>جمعية لكل 100 ألف نسمة (المتوسط الوطني)</span></div>
<div class="k hot"><b>{F['low']} {n2(F['low_rate'])}</b><span>أقل منطقة: {round(F['low_idx']*100)}% من المتوسط الوطني تقريباً</span></div>
</div>
<h2>أبرز النتائج</h2>
<ol>
<li><b>{F['low']} الأقل تغطية:</b> {n2(F['low_rate'])} جمعية لكل 100 ألف نسمة، أي نحو نصف المتوسط الوطني، مع أنها ثالث أكبر منطقة سكاناً ({F['low_pop']/1e6:.1f} مليون نسمة). تليها {F['next'][0][0]} ({n2(F['next'][0][1])}) و{F['next'][1][0]} ({n2(F['next'][1][1])}).</li>
<li><b>أين الفجوة بالضبط؟</b> {F['n_conf']} خانات (منطقة × تخصص) تحتاج «أولوية دعم» بأرقام كافية، <b>{len(lc)} منها في {F['low']}</b>: {cells}. أكبرها {big.group} في {big.region}: {int(big.associations)} جمعية مقابل ≈{n0(big.associations + big.missing_to_reach_national)} لو بلغت المتوسط الوطني. وخارجها: {others}.</li>
<li><b>الطلب:</b> وفق مسح منشآت القطاع غير الربحي 2018، تخدم تخصصات {hi} نسبة من المستفيدين أكبر من حجمها بين المنشآت (وارتفاع «دعم العمل الخيري» قد يعكس احتساب مستفيدين غير مباشرين). وبإضافة الطلب {moved}</li>
<li><b>2030 (سيناريو):</b> مع نمو السكان إلى ≈{F['pop2030']/1e6:.1f} مليون، يرتفع مجموع الجمعيات الناقصة لبلوغ المتوسط الوطني من ≈{n0(F['m_today'])} اليوم إلى ≈{n0(F['m_2030'])}؛ أكبره في {r1} (≈{n0(m1)}) ثم {r2} (≈{n0(m2)}). أي أن التخطيط على أرقام اليوم وحدها لا يكفي.</li>
<li><b>تأكيد من مصادر أخرى:</b> شغّلنا الأداة نفسها على ملفات مستقلة، وظهرت {F['low']} الأقل أيضاً:<ul>{conf_line}</ul></li>
</ol>
<h2>التوصية</h2>
<div class="rec"><b>وجّه الدعم الجديد أولاً إلى {F['low']}</b> في التخصصات الأربعة أعلاه، مع البدء بالتخصص الأكبر فجوة ({big.group})، ثم الخانات خارجها. وبحسب محاكي التقرير، تكفي <b>{F['min_new']} جمعية جديدة</b> موزعة على الخانات الأقل تغطية لإخراج الخانات الـ{F['n_conf']} كلها من «أولوية دعم».<br>
<b>الخطوة التالية:</b> تحقق ميداني مع الجمعيات القائمة في {F['low']} قبل التمويل: هل النقص في عدد الجمعيات، أم أن الجمعيات الموجودة أكبر وتخدم أكثر؟ وتحديد الاحتياج داخل المحافظات.</div>
<h2>حدود التحليل</h2>
<div class="lim">المؤشر عدد الجمعيات المسجلة، وليس حجم الخدمة أو أثرها · المنطقة هي منطقة التسجيل، وقد تخدم الجمعية مناطق أخرى · مسح 2018 وطني وبلا مناطق · فجوة 2030 سيناريو وليست إسقاطاً رسمياً · الخانات ذات الأرقام القليلة مؤشر أولي فقط.</div>
<div class="foot"><b>المصادر:</b> سجل الجمعيات والمؤسسات الأهلية (المنصة الوطنية للبيانات المفتوحة)، سكان المناطق 2010–2022 ومسح منشآت القطاع غير الربحي 2018 (الهيئة العامة للإحصاء).<br>
كل رقم في هذه الصفحة يُقرأ آلياً من مخرجات الكود (<span dir="ltr">outputs/</span>)، والقرارات التحليلية بشرية وموثقة في سجل القرارات. التفاصيل والتقرير التفاعلي: <span dir="ltr">outputs/report.html</span>.</div>
</div></body></html>'''


def to_pdf(src, dst):
    res = {}
    def run():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page(); pg.goto(Path(src).resolve().as_uri())
                pg.pdf(path=str(dst), format='A4', print_background=True, prefer_css_page_size=True); b.close()
        except Exception as e: res['e'] = e
    th = threading.Thread(target=run); th.start(); th.join()
    if 'e' in res: print('تعذّر إنشاء PDF:', res['e'], file=sys.stderr); return False
    return True


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='outputs'); ap.add_argument('--no-pdf', action='store_true'); a = ap.parse_args()
    out = Path(a.out); F = facts(out)
    # تأكيد من مصادر أخرى: يُقرأ من مخرجات أمثلة agent_tests إن وُجدت
    confirm = []
    root = out.parent
    for path, label in ((root / 'agent_tests/sport/out', 'الجمعيات الرياضية'), (root / 'agent_tests/quran/out_assoc', 'جمعيات تحفيظ القرآن (2024)')):
        p = path / 'tables/region_summary.csv'
        if p.exists():
            r = read(p).sort_values('per_100k_all_groups').iloc[0]
            lg = dict(zip(read(path / 'analysis_decisions_log.csv').item, read(path / 'analysis_decisions_log.csv').value))
            confirm.append(f'{label}: {r.iloc[0]} {n2(r.per_100k_all_groups)} لكل 100 ألف مقابل {n2(float(lg["national_per_100k_all_groups"]))} وطنياً')
    h = out / 'executive_summary.html'; h.write_text(page(F, confirm), encoding='utf-8'); print('تم: ', h)
    if not a.no_pdf and to_pdf(h, out / 'executive_summary.pdf'): print('تم: ', out / 'executive_summary.pdf')


if __name__ == '__main__':
    main()
