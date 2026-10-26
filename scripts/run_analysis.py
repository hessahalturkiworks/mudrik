# -*- coding: utf-8 -*-
"""
مدرك — تشغيل التحليل الكامل (فجوات الخدمات + مصفوفة القرار).
الدوال في mudrik_core.py، والإعدادات والقرارات في config.json (ضعيهم بجانب هذا الملف في scripts/).

  python run_analysis.py --assoc data_clean/Non_profit_Associations_clean.csv \
      --found data_clean/Non_profit_Foundations_clean.csv --pop data_clean/population_2022_gastat.csv --out outputs
  (--config مسار آخر لملف الإعدادات؛ الافتراضي config.json بجانب السكربت. --found اختياري)
المخرجات: outputs/tables/*.csv و outputs/figures/*.png|html و outputs/analysis_decisions_log.csv
"""
import argparse
from pathlib import Path
import mudrik_core as mc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--assoc', required=True); ap.add_argument('--pop', required=True)
    ap.add_argument('--found'); ap.add_argument('--demand', help='اختياري: survey2018_demand_clean.csv (عدسة الطلب)'); ap.add_argument('--out', default='outputs')
    ap.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    a = ap.parse_args()
    cfg = mc.load_config(a.config)
    R, L, G, S, M, log = mc.run_all(cfg, a.assoc, a.pop, a.out, a.found, a.demand)
    lb = cfg['labels']
    print(f'جمعيات محسوبة: {int(R["cnt"].values.sum())} | خلايا: {R["cnt"].size} | فجوات (< {cfg["thresholds"]["low_ratio"]}): {len(G)}')
    print('مصفوفة القرار:', ' | '.join(f'{lb[k]} {int((M.recommendation == lb[k]).sum())}' for k in ('priority', 'ok', 'high')))
    print('أقل 3 مناطق تغطية (لكل 100 ألف):', ' / '.join(f'{r} {v}' for r, v in S.per_100k_all_groups.sort_values().head(3).items()))


if __name__ == '__main__':
    main()
