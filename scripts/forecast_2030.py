# -*- coding: utf-8 -*-
"""
فجوة 2030 (التنبؤ البسيط): كم جمعية تحتاج كل منطقة في 2030 لتبقى عند المتوسط الوطني الحالي لكل تخصص؟

1) نتوقع سكان كل منطقة في 2030 من سلسلة الهيئة 2010–2022 بطريقتين بسيطتين: اتجاه خطي، ونمو سنوي مركّب (CAGR).
2) نختار الطريقة آلياً باختبار رجعي بلا تسريب: نُدرّب على 2010–2018 فقط ونتوقع 2022 ونقارن بالتعداد الفعلي.
3) نحسب الجمعيات المطلوبة 2030 = المتوسط الوطني الحالي للتخصص × سكان 2030 ÷ 100 ألف، ثم الناقص مقارنة بالعدد الحالي.
افتراضات: المتوسط الوطني ثابت عند مستواه الحالي (معيار مقارنة وليس هدفاً)، والعدد الحالي للجمعيات لا يتغير. هذا سيناريو وليس إسقاطاً رسمياً.

الاستخدام:  python forecast_2030.py --series data_clean/population_series_clean.csv --tables outputs/tables [--year 2030]
المخرجات (في tables):  population_forecast.csv  و  forecast_2030_regions.csv  و  forecast_2030_cells.csv  و  forecast_log.csv
"""
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mudrik_core import save_table


def linear(g, last, target):
    t = g[g.year <= last]; b = np.polyfit(t.year, t.population, 1); return float(np.polyval(b, target))


def cagr(g, last, target):
    t = g[g.year <= last].sort_values('year'); a, z = t.iloc[0], t.iloc[-1]
    r = (z.population / a.population) ** (1 / (z.year - a.year)) - 1
    return float(z.population * (1 + r) ** (target - z.year))


METHODS = {'نمو سنوي مركّب (CAGR)': cagr, 'اتجاه خطي': linear}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--series', required=True); ap.add_argument('--tables', required=True)
    ap.add_argument('--year', type=int, default=2030); ap.add_argument('--test-cut', type=int, default=2018)
    a = ap.parse_args(); T = Path(a.tables)
    s = pd.read_csv(a.series, encoding='utf-8-sig'); last = int(s.year.max())
    log = []
    # اختبار رجعي بلا تسريب: تدريب حتى test_cut فقط، وتوقع آخر سنة فعلية
    back = {}
    for name, f in METHODS.items():
        ape = {k: abs(f(g, a.test_cut, last) - g[g.year == last].population.iloc[0]) / g[g.year == last].population.iloc[0] * 100 for k, g in s.groupby('region_key')}
        back[name] = ape
        log.append(dict(step=f'backtest:{name}', value=round(np.mean(list(ape.values())), 2), detail=f'تدريب {s.year.min()}–{a.test_cut} وتوقع {last}؛ متوسط الخطأ % (أقصى {max(ape.values()):.2f}%)'))
    best = min(back, key=lambda n: np.mean(list(back[n].values())))
    bias = np.mean([(METHODS[best](g, a.test_cut, last) / g[g.year == last].population.iloc[0] - 1) * 100 for _, g in s.groupby('region_key')])
    log.append(dict(step='backtest_bias', value=round(bias, 2), detail='موجب = الطريقة بالغت في الاختبار الرجعي، فأرقام 2030 أقرب إلى حد أعلى' if bias > 0 else 'سالب = الطريقة قلّلت في الاختبار الرجعي'))
    log.append(dict(step='method_chosen', value=best, detail='أقل متوسط خطأ في الاختبار الرجعي'))
    f = METHODS[best]
    P = pd.DataFrame([dict(region_key=k, pop_2022=int(g[g.year == last].population.iloc[0]), pop_2030=int(round(f(g, last, a.year))),
                           backtest_error_pct=round(back[best][k], 2)) for k, g in s.groupby('region_key')])
    P['growth_pct'] = ((P.pop_2030 / P.pop_2022 - 1) * 100).round(1); P['method'] = best
    save_table(P.sort_values('growth_pct', ascending=False), T / 'population_forecast')

    R = pd.read_csv(T / 'rate_per100k_region_group.csv', encoding='utf-8-sig')
    C = R.merge(P[['region_key', 'pop_2030']], left_on='region', right_on='region_key').drop(columns='region_key')
    C['needed_2030'] = (C.national_per_100k * C.pop_2030 / 1e5).round(1)
    C['missing_2030'] = (C.needed_2030 - C.associations).clip(lower=0).round(1)
    C = C[['region', 'group', 'associations', 'national_per_100k', 'missing_to_reach_national', 'pop_2030', 'needed_2030', 'missing_2030', 'low_confidence']]
    save_table(C.sort_values('missing_2030', ascending=False), T / 'forecast_2030_cells')
    G = C.groupby('region').agg(associations=('associations', 'sum'), missing_today=('missing_to_reach_national', 'sum'), missing_2030=('missing_2030', 'sum')).round(1)
    G = G.join(P.set_index('region_key')[['pop_2022', 'pop_2030', 'growth_pct']])
    G['extra_by_2030'] = (G.missing_2030 - G.missing_today).round(1)
    save_table(G.sort_values('missing_2030', ascending=False), T / 'forecast_2030_regions', index=True)
    log.append(dict(step='kingdom_population_2030', value=int(P.pop_2030.sum()), detail=f'من {int(P.pop_2022.sum()):,} في {last}'))
    log.append(dict(step='missing_total', value=f'{G.missing_today.sum():.0f} → {G.missing_2030.sum():.0f}', detail='مجموع الجمعيات الناقصة لبلوغ المتوسط الوطني: اليوم ← 2030'))
    save_table(pd.DataFrame(log), T / 'forecast_log')
    print(f'الطريقة: {best} | خطأ الاختبار الرجعي {np.mean(list(back[best].values())):.2f}% | الناقص: {G.missing_today.sum():.0f} اليوم ← {G.missing_2030.sum():.0f} في {a.year}')


if __name__ == '__main__':
    main()
