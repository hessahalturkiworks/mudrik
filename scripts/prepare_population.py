# -*- coding: utf-8 -*-
"""
تجهيز السكان من جدول الهيئة العامة للإحصاء «المنطقة - أعداد مطلقة» (السكان حسب المنطقة، 2010–2022).
الاستخدام:  python prepare_population.py <xlsx> [out_dir]
المخرجات:
  population_2022_gastat.csv    سكان 2022 (تعداد) لكل منطقة: region_ar, region_key, population_2022, source  ← يستخدمه التحليل
  population_series_clean.csv   السلسلة الطويلة: region_key, year, population                              ← لتوقع 2030
  population_log.csv            خطوات التحقق
يتوقف إذا لم يطابق مجموع المناطق صف «إجمالي» في أي سنة.
"""
import sys
from pathlib import Path
import pandas as pd

AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
SOURCE = 'الهيئة العامة للإحصاء (GASTAT)، تعداد 2022'
LOG = []


def main():
    src = Path(sys.argv[1]); out = Path(sys.argv[2] if len(sys.argv) > 2 else '.'); out.mkdir(parents=True, exist_ok=True)
    d = pd.read_excel(src, header=0)
    d = d.rename(columns={d.columns[0]: 'region_ar'})
    d.columns = ['region_ar'] + [int(str(c).translate(AR_DIGITS).split('.')[0]) for c in d.columns[1:]]   # «٢٠٢٢» ← 2022
    d['region_ar'] = d.region_ar.astype(str).str.strip()
    is_total = d.region_ar.str.contains('إجمالي|المملكة')
    total, d = d[is_total].iloc[0], d[~is_total & d.region_ar.ne('nan')].copy()
    years = [c for c in d.columns if isinstance(c, int)]
    for y in years:                                     # تحقق: مجموع المناطق = صف الإجمالي
        assert int(d[y].sum()) == int(total[y]), f'{y}: مجموع المناطق {int(d[y].sum()):,} ≠ الإجمالي {int(total[y]):,}'
    assert len(d) == 13, f'عدد المناطق {len(d)} وليس 13'
    LOG.append(dict(step='sum_check', value=f'{len(years)} سنة', detail=f'مجموع المناطق = صف الإجمالي في كل السنوات {min(years)}–{max(years)}'))
    d['region_key'] = d.region_ar.str.replace(r'^المنطقة\s+', '', regex=True)   # «المنطقة الشرقية» ← «الشرقية» (مفتاح الدمج مع ملف الجمعيات)
    LOG.append(dict(step='region_key', value=int((d.region_key != d.region_ar).sum()), detail='إزالة كلمة «المنطقة» من البداية لتطابق أسماء ملف الجمعيات'))
    p22 = d[['region_ar', 'region_key', 2022]].rename(columns={2022: 'population_2022'}); p22['source'] = SOURCE
    p22.to_csv(out / 'population_2022_gastat.csv', index=False, encoding='utf-8-sig')
    s = d.melt(id_vars=['region_key'], value_vars=years, var_name='year', value_name='population').sort_values(['region_key', 'year'])
    s.to_csv(out / 'population_series_clean.csv', index=False, encoding='utf-8-sig')
    LOG.append(dict(step='outputs', value=len(s), detail=f'سكان 2022: {int(p22.population_2022.sum()):,} | السلسلة: {len(d)} منطقة × {len(years)} سنة'))
    pd.DataFrame(LOG).to_csv(out / 'population_log.csv', index=False, encoding='utf-8-sig')
    print(f'تم: {len(d)} منطقة × {len(years)} سنة ({min(years)}–{max(years)}) | سكان 2022 = {int(p22.population_2022.sum()):,}')


if __name__ == '__main__':
    main()
