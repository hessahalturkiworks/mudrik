# -*- coding: utf-8 -*-
"""
اختبار 8: إحصائية جمعيات تحفيظ القرآن 2024 (ملف مجمّع ومقلوب: المناطق أعمدة).
قرار صاحبة المشروع (23 أكتوبر): نسخة محوّلة خارج scripts/ بدل تعديل الكود. الأصل لا يتغير.

  python -I prepare_quran.py <xlsx> <population_2022_gastat.csv> <out_dir>

المخرجات:
  quran_by_region.csv        صف لكل منطقة، ونفس المؤشرات بنفس أسمائها (بلا أعمدة جديدة، بلا صف الإجمالي)
  population_2022_no_asir.csv  جدول السكان نفسه دون عسير (لتقرير الحلقات فقط، بقرار صاحبة المشروع)
  prepare_log.csv            كل خطوة وتحققها
"""
import sys
from pathlib import Path
import openpyxl
import pandas as pd

xlsx, pop_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
log = []
def note(step, value, detail=''): log.append(dict(step=step, value=value, detail=detail))

wb = openpyxl.load_workbook(xlsx, data_only=True)          # data_only: القيم المحفوظة لصيغ الإجمالي
ws = wb.worksheets[1]
rows = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
header = rows[0]
note('sheet', ws.title, f'{len(rows) - 1} مؤشرات × {len(header) - 1} أعمدة (13 منطقة + الإجمالي)')

regions_raw = [h for h in header[1:]]
total_idx = [i for i, h in enumerate(regions_raw) if str(h).strip() == 'الإجمالي']
assert len(total_idx) == 1, 'عمود الإجمالي غير موجود أو مكرر'
ti = total_idx[0]

data = {}
for r in rows[1:]:
    measure = str(r[0]).strip()
    vals = list(r[1:])
    region_vals = [v for i, v in enumerate(vals) if i != ti]
    s = sum(int(v) for v in region_vals)
    tot = vals[ti]
    assert tot is not None and int(tot) == s, f'{measure}: مجموع المناطق {s} لا يطابق الإجمالي {tot}'
    note(f'check_total:{measure}', s, 'مجموع المناطق = عمود الإجمالي في الملف')
    data[measure] = [int(v) for v in region_vals]

regions = [h for i, h in enumerate(regions_raw) if i != ti]      # الأسماء كما هي (التوحيد يتم في الذاكرة عبر region_normalize)
df = pd.DataFrame({'المنطقة': regions, **data})
note('dropped_total_column', 1, 'عمود «الإجمالي» ليس منطقة')
note('rows_out', len(df), 'صف لكل منطقة')
df.to_csv(out / 'quran_by_region.csv', index=False, encoding='utf-8-sig')

P = pd.read_csv(pop_path, encoding='utf-8-sig')
P2 = P[P.region_key != 'عسير'].copy()
assert len(P2) == len(P) - 1
note('population_no_asir', int(P2.population_2022.sum()), f'تقرير الحلقات فقط: عسير مستبعدة (سكانها {int(P.population_2022.sum() - P2.population_2022.sum()):,})')
P2.to_csv(out / 'population_2022_no_asir.csv', index=False, encoding='utf-8-sig')

pd.DataFrame(log).to_csv(out / 'prepare_log.csv', index=False, encoding='utf-8-sig')
for x in log: print(x['step'], '|', x['value'], '|', x['detail'])
