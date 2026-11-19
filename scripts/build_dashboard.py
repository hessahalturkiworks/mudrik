"""داشبورد مُدرك: يقرأ جداول التحليل من outputs/tables ويبني صفحة HTML واحدة تعمل بدون إنترنت.

الاستخدام:  python scripts/build_dashboard.py [--out outputs]   (يستدعيه run_pipeline.py تلقائياً)
المخرجات:   outputs/dashboard.html
            outputs/gap_cards.csv  و  outputs/gap_cards.json  (بطاقات الفجوة)

لا يعدّل أي ملف في data_raw ولا في outputs/tables؛ يقرأ فقط.
الخريطة: Natural Earth (ملكية عامة). الخط: Tajawal (رخصة OFL).
"""
import argparse, base64, json, re, sys
from datetime import date
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / 'assets'
OUT = ROOT / 'outputs'          # يُغيَّر بـ --out
TAB = OUT / 'tables'

LOW, HIGH, EDGE = 0.5, 1.5, 0.55          # نفس حدود config.json + حد «على الحافة»
STATUS = {'priority': 'تحتاج دعم', 'ok': 'قريبة من المعدل', 'high': 'مكتفية'}
NEED = {'ضغط مرتفع': 'عالية', 'متوازن': 'متوسطة', 'ضغط منخفض': 'أقل'}


def status_of(idx):
    idx = round(idx, 2)
    return 'priority' if idx < LOW else ('high' if idx >= HIGH else 'ok')


def read(name):
    return pd.read_csv(TAB / f'{name}.csv', encoding='utf-8-sig')


def main():
    global OUT, TAB
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default=str(OUT))
    OUT = Path(ap.parse_args().out); TAB = OUT / 'tables'
    R = read('rate_per100k_region_group')
    M = read('decision_matrix')
    F30 = read('forecast_2030_cells')
    FR = read('forecast_2030_regions')
    PF = read('population_forecast')
    FL = read('forecast_log').set_index('step')
    DP = read('demand_pressure').set_index('group')

    # السكان لكل سنة (2025 تُشتق من نفس معدل النمو المركّب المستخدم في توقع 2030)
    PF['g'] = (PF.pop_2030 / PF.pop_2022) ** (1 / 8) - 1
    pops = {r.region_key: {'2022': int(r.pop_2022), '2025': int(round(r.pop_2022 * (1 + r.g) ** 3)),
                           '2030': int(r.pop_2030)} for r in PF.itertuples()}

    groups = list(DP.sort_values('demand_pressure', ascending=False).index)
    regions = list(read('region_summary').region_key)

    m = M.set_index(['region', 'group'])
    f30 = F30.set_index(['region', 'group'])
    nat = R.groupby('group').apply(lambda d: d.associations.sum() / d.population_2022.sum() * 1e5)

    cells, cards = [], []
    for r in R.itertuples():
        idx = (r.associations / r.population_2022 * 1e5) / nat[r.group]
        st = status_of(idx)
        assert STATUS[st] == {'أولوية دعم': 'تحتاج دعم', 'تغطية مناسبة': 'قريبة من المعدل',
                              'تغطية عالية': 'مكتفية'}[m.loc[(r.region, r.group), 'recommendation']], 'تصنيف غير مطابق للمصفوفة'
        need = DP.at[r.group, 'demand_level']
        start = st == 'priority' and not r.low_confidence and need in ('ضغط مرتفع', 'متوازن')
        edge = st == 'ok' and idx < EDGE
        miss30 = float(f30.loc[(r.region, r.group), 'missing_2030'])
        cells.append(dict(r=r.region, g=r.group, a=int(r.associations), few=bool(r.low_confidence),
                          start=bool(start), edge=bool(edge), m30=round(miss30, 1)))
        if st == 'priority' or edge:
            cards.append({'المنطقة': r.region, 'التخصص': r.group, 'عدد الجمعيات': int(r.associations),
                          'جمعيات لكل 100 ألف شخص': round(r.associations / r.population_2022 * 1e5, 2),
                          'معدل المملكة للتخصص': round(nat[r.group], 2),
                          'التغطية من معدل المملكة %': round(idx * 100),
                          'جمعيات ناقصة اليوم': round(max(0, nat[r.group] * r.population_2022 / 1e5 - r.associations), 1),
                          'جمعيات ناقصة 2030': round(miss30, 1),
                          'الحالة': STATUS[st] if not edge else 'على الحافة',
                          'التوصية': 'نعم' if start else 'لا',
                          'البيانات': 'غير كافية' if r.low_confidence else 'كافية',
                          'الحاجة للتخصص': NEED[need],
                          'تاريخ التحديث': date.today().isoformat(),
                          'المصدر': 'مُدرك: منصة البيانات المفتوحة + الهيئة العامة للإحصاء'})

    cards.sort(key=lambda c: (c['التوصية'] != 'نعم', c['الحالة'] != 'تحتاج دعم', -c['جمعيات ناقصة اليوم']))
    pd.DataFrame(cards).to_csv(OUT / 'gap_cards.csv', index=False, encoding='utf-8-sig')
    (OUT / 'gap_cards.json').write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding='utf-8')

    # سجل التنظيف (من سجل التشغيل التفصيلي)
    log = (OUT / 'pipeline_details.log').read_text(encoding='utf-8')
    head = re.search(r'\[Non profit Associations\.xlsx\] السجلات: (\d+) ← (\d+) \| الخلايا المعدّلة: (\d+) \| للمراجعة: (\d+)', log)
    block = log[head.end():].split('\n\n')[0]
    kinds = [(k.strip(), int(v)) for k, v in re.findall(r'-\s*([^:\n]+):\s*(\d+)', block)]
    clean = dict(before=int(head.group(1)), after=int(head.group(2)), cells=int(head.group(3)),
                 review=int(head.group(4)), kinds=kinds)

    # قواعد الحساب من سجل القرارات (لا أرقام مكتوبة يدوياً)
    LG = pd.read_csv(OUT / 'analysis_decisions_log.csv', encoding='utf-8-sig').set_index('item')['value']
    rules = {k: float(LG[k]) for k in ['rows_in_rate', 'excluded_national_entities', 'excluded_unclassified', 'population_total',
             'national_per_100k_all_groups', 'config:low_ratio', 'config:high_ratio', 'config:min_region_count',
             'config:min_national_count', 'config:demand_high', 'config:demand_low', 'rows:Non_profit_Foundations_clean.csv']}

    bt = {k.split(':', 1)[1]: float(FL.at[k, 'value']) for k in FL.index if k.startswith('backtest:')}
    data = dict(
        regions=regions, groups=groups, pops=pops, cells=cells,
        need={g: NEED[DP.at[g, 'demand_level']] for g in groups},
        needRatio={g: float(DP.at[g, 'demand_pressure']) for g in groups},
        f30=[dict(r=x.region, today=float(x.missing_today), y30=float(x.missing_2030)) for x in FR.itertuples()],
        backtest=bt, kpop30=int(FL.at['kingdom_population_2030', 'value']), clean=clean,
        registered=clean['after'], cards=cards, rules=rules, built=date.today().isoformat(),
        map=json.loads((ASSETS / 'sa_map.json').read_text(encoding='utf-8')))

    fonts = ''.join(
        f"@font-face{{font-family:T;font-weight:{w};src:url(data:font/ttf;base64,"
        f"{base64.b64encode((ASSETS / f'Tajawal-{n}.ttf').read_bytes()).decode()}) format('truetype')}}"
        for n, w in (('Regular', 400), ('Medium', 500), ('Bold', 700), ('ExtraBold', 800)))
    html = (Path(__file__).resolve().parent / 'dashboard_template.html').read_text(encoding='utf-8')
    html = html.replace('/*FONTS*/', fonts).replace('/*DATA*/null', json.dumps(data, ensure_ascii=False))
    (OUT / 'dashboard.html').write_text(html, encoding='utf-8')
    print(f'dashboard.html ✓ | خلايا {len(cells)} | بطاقات فجوة {len(cards)} | ابدأ هنا {sum(c["start"] for c in cells)}')


if __name__ == '__main__':
    sys.exit(main())
