# -*- coding: utf-8 -*-
"""
سكان المحافظات (تعداد 2022) بأسماء عربية وربطها بالمنطقة، للتحليل على مستوى المحافظة.
الاستخدام:  python prepare_governorates.py <census2022_governorate.csv> [out_dir] [--regions data_clean/population_2022_gastat.csv]
المدخل: ملف طويل (geo = «gov:<الاسم الإنجليزي>»، metric، value) كما نُشر في «نبض البيانات» نقلاً عن لوحة تعداد الهيئة.
جدول الربط: scripts/ref/governorates_ksa.csv (الاسم الإنجليزي ← العربي ← المنطقة).
التحقق: مجموع محافظات كل منطقة يجب أن يساوي سكان المنطقة في جدول الهيئة تماماً، وإلا يتوقف.
المخرج: population_2022_governorates.csv (region_key, governorate_ar, governorate_en, population_2022) و governorates_log.csv
"""
import argparse, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('out', nargs='?', default='.'); ap.add_argument('--regions')
a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); log = []
d = pd.read_csv(a.src, encoding='utf-8-sig')
p = d[(d.metric == 'population') & d.geo.str.startswith('gov:')].copy(); p['governorate_en'] = p.geo.str[4:].str.strip()
ref = pd.read_csv(HERE / 'ref/governorates_ksa.csv', encoding='utf-8-sig')
miss = set(p.governorate_en) - set(ref.governorate_en); assert not miss, f'محافظات بلا ربط في جدول الربط: {miss}'
assert not p.governorate_en.duplicated().any(), 'محافظة مكررة في الملف'
G = p.merge(ref, on='governorate_en')[['region_key', 'governorate_ar', 'governorate_en', 'value']].rename(columns={'value': 'population_2022'})
log.append(dict(step='governorates', value=len(G), detail=f'مجموع السكان {int(G.population_2022.sum()):,}'))
if a.regions and Path(a.regions).exists():
    R = pd.read_csv(a.regions, encoding='utf-8-sig').set_index('region_key').population_2022
    s = G.groupby('region_key').population_2022.sum()
    bad = {k: int(s.get(k, 0) - R[k]) for k in R.index if int(s.get(k, 0)) != int(R[k])}
    assert not bad, f'مجموع المحافظات لا يطابق سكان المنطقة: {bad}'
    log.append(dict(step='check_vs_regions', value=len(R), detail='مجموع محافظات كل منطقة = سكان المنطقة في جدول الهيئة (فرق صفر في كل المناطق)'))
G.sort_values(['region_key', 'population_2022'], ascending=[True, False]).to_csv(out / 'population_2022_governorates.csv', index=False, encoding='utf-8-sig')
pd.DataFrame(log).to_csv(out / 'governorates_log.csv', index=False, encoding='utf-8-sig')
print(f'تم: {len(G)} محافظة في {G.region_key.nunique()} منطقة | السكان {int(G.population_2022.sum()):,}' + (' | تطابق مجاميع المناطق ✓' if len(log) > 1 else ''))
