# -*- coding: utf-8 -*-
"""
run_pipeline.py — يشغّل مدرك كاملاً بالترتيب: تنظيف ← تحليل ← تقرير.
هذا هو الأمر الذي يستدعيه الوكيل (انظر SKILL.md). يوقف قبل التحليل حتى يوافق الإنسان على القرارات.

  python scripts/run_pipeline.py                 # يُنظّف ثم يعرض القرارات ويتوقف (رمز الخروج 3)
  python scripts/run_pipeline.py --yes           # بعد موافقة الإنسان: تحليل + تقرير
  python scripts/run_pipeline.py --skip-clean --yes   # البيانات النظيفة جاهزة في data_clean
المجلدات الافتراضية: data_raw/ و data_clean/ و outputs/ (تُغيَّر بـ --raw --clean --out)
"""
import argparse, csv, json, os, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = []
OUT = Path('outputs')                     # يُحدَّث في main
# رسائل الشاشة بالإنجليزية لأن شاشة الأوامر في ويندوز تعرض العربية مقلوبة. التفاصيل العربية تُحفظ في outputs/pipeline_details.log


def say(msg=''):
    print(msg, flush=True)


def run(name, cmd):
    t = time.time(); print(f'  > {name:<58}', end='', flush=True)
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}   # ويندوز: يمنع خطأ ترميز عند تمرير النص عبر أنبوب
    r = subprocess.run([sys.executable] + [str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    ok, sec = r.returncode == 0, round(time.time() - t, 1)
    STEPS.append(dict(step=name, status='ok' if ok else 'FAILED', seconds=sec))
    with open(OUT / 'pipeline_details.log', 'a', encoding='utf-8') as f:
        f.write(f'\n===== {name} | {"ok" if ok else "FAILED"} | {sec}s =====\n{r.stdout}\n{r.stderr if not ok else ""}')
    print(f'OK  ({sec}s)' if ok else 'FAILED', flush=True)
    if not ok:
        say('\n  ERROR (details in Arabic in outputs/pipeline_details.log):')
        print(r.stderr.strip()[-1500:], file=sys.stderr); finish(1)
    return r


def find(folder, *patterns):
    for p in patterns:
        hits = sorted(Path(folder).glob(p))
        if hits: return hits[0]
    return None


def finish(code, out=None):
    out = Path(out or OUT)
    if out.exists():
        with open(out / 'pipeline_log.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=['step', 'status', 'seconds']); w.writeheader(); w.writerows(STEPS)
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', default='data_raw'); ap.add_argument('--clean', default='data_clean'); ap.add_argument('--out', default='outputs')
    ap.add_argument('--config', default=str(HERE / 'config.json'))
    ap.add_argument('--skip-clean', action='store_true', help='تخطي التنظيف (الملفات النظيفة موجودة في data_clean)')
    ap.add_argument('--yes', action='store_true', help='موافقة الإنسان على القرارات المعروضة: يسمح بتشغيل التحليل')
    a = ap.parse_args(); raw, clean, out = Path(a.raw), Path(a.clean), Path(a.out)
    clean.mkdir(exist_ok=True, parents=True); out.mkdir(exist_ok=True, parents=True)
    global OUT; OUT = out; (out / 'cleaning').mkdir(exist_ok=True)
    (out / 'pipeline_details.log').write_text(f'Mudrik pipeline · {time.strftime("%Y-%m-%d %H:%M")}\n', encoding='utf-8')
    say('\nMUDRIK pipeline  (Arabic details: outputs/pipeline_details.log)')
    say('\n[1/3] Cleaning raw data' if not a.skip_clean else '\n[1/3] Cleaning skipped (--skip-clean)')
    A, F, P = clean / 'Non_profit_Associations_clean.csv', clean / 'Non_profit_Foundations_clean.csv', clean / 'population_2022_gastat.csv'

    # ١) التنظيف (آلي، والأصل لا يتغير)
    if not a.skip_clean:
        ra, rf = find(raw, '*ssociations*.xlsx'), find(raw, '*oundations*.xlsx')     # المؤسسات اختيارية
        if ra:
            pairs = [(ra, A)] + ([(rf, F)] if rf else [])
            run('Clean associations' + (' + foundations' if rf else '') + ' (dq_check)', [HERE / 'dq_check.py'] + [s for s, _ in pairs] + ['--out', out / 'cleaning'])
            for src, dst in pairs:
                c = out / 'cleaning' / (src.stem + '_clean.csv')
                assert c.exists(), f'لم يُنتج التنظيف {c.name}'; shutil.copy(c, dst)
        elif not A.exists():
            print(f'ERROR: no entities file (*Associations*.xlsx) in {raw} and no clean copy in {clean}', file=sys.stderr); finish(2, out)
        rp = find(raw, '*أعداد مطلقة*.xlsx', '*opulation*.xlsx')
        if rp: run('Prepare population 2010-2022 (prepare_population)', [HERE / 'prepare_population.py', rp, clean]); shutil.move(str(clean / 'population_log.csv'), out / 'cleaning' / 'population_log.csv')
        rgv = find(raw, '*governorate*.csv')
        if rgv: run('Population by governorate (prepare_governorates)', [HERE / 'prepare_governorates.py', rgv, clean, '--regions', P]); shutil.move(str(clean / 'governorates_log.csv'), out / 'cleaning' / 'governorates_log.csv')
        rs = find(raw, '*survey*2018*.xlsx', '*survey*2018*.pdf')    # Excel الهيئة مفضّل، والـPDF احتياطي
        if rs: run('Extract 2018 establishments survey (extract_survey2018)', [HERE / 'extract_survey2018.py', rs, clean]); shutil.move(str(clean / 'survey2018_log.csv'), out / 'cleaning' / 'survey2018_log.csv')
    missing = [p.name for p in (A, P) if not p.exists()]     # الحد الأدنى: الكيانات + السكان، والباقي اختياري
    if missing: print('ERROR: missing required files in data_clean:', missing, '(put the GASTAT population table and the associations xlsx in data_raw)', file=sys.stderr); finish(2, out)

    # ٢) نقطة القرار البشري
    cfg = json.loads(Path(a.config).read_text(encoding='utf-8'))
    say('\n[2/3] Human decisions (scripts/config.json) - please review:')
    for k, v in {**cfg['decisions'], **cfg['thresholds']}.items(): say(f'      {k:<24} {v}')
    if not a.yes:
        say('\n  STOPPED for human review. If you approve these decisions, run again with:  --yes'); finish(3, out)
    say('      -> approved (--yes)')
    say('\n[3/3] Analysis and report')

    # ٣) التحليل والتقرير
    run('Gap analysis + decision matrix (run_analysis)', [HERE / 'run_analysis.py', '--assoc', A, '--pop', P, '--out', out, '--config', a.config] + (['--found', F] if F.exists() else []) + (['--demand', clean / 'survey2018_demand_clean.csv'] if (clean / 'survey2018_demand_clean.csv').exists() else []))
    PS = clean / 'population_series_clean.csv'
    if PS.exists(): run('2030 gap forecast (forecast_2030)', [HERE / 'forecast_2030.py', '--series', PS, '--tables', out / 'tables'])
    cmd = [HERE / 'build_report.py', '--tables', out / 'tables', '--log', out / 'analysis_decisions_log.csv', '--out', out]
    if (clean / 'survey2018_challenges_clean.csv').exists(): cmd += ['--challenges', clean / 'survey2018_challenges_clean.csv']
    run('Interactive report (build_report)', cmd)
    opt = {'Foundations (funders layer)': F, 'Survey 2018 (demand lens)': clean / 'survey2018_demand_clean.csv', 'Population series (2030 gap)': clean / 'population_series_clean.csv'}
    say('\nOptional inputs: ' + ' | '.join(f'{k}: {"yes" if v.exists() else "not provided"}' for k, v in opt.items()))
    import pandas as pd
    M = pd.read_csv(out / 'tables/decision_matrix.csv', encoding='utf-8-sig'); lb = cfg['labels']
    n = {k: int((M.recommendation == lb[k]).sum()) for k in ('priority', 'ok', 'high')}
    say(f'\nRESULT  cells: {len(M)} | priority support: {n["priority"]} | adequate: {n["ok"]} | high coverage: {n["high"]}')
    say(f'DONE    open: {out / "report.html"}'); finish(0, out)


if __name__ == '__main__':
    main()
