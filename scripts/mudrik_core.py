# -*- coding: utf-8 -*-
"""
mudrik_core.py — دوال مدرك العامة (بلا أي اسم عمود أو منطقة مكتوب داخلها؛ كلها من config.json).

أي جدول كيانات فيه (اسم، منطقة، تصنيف) + جدول سكان (منطقة، عدد) يمكن تحليله بنفس الدوال:
  load_config → load_entities / load_population → prepare → rates → tables → decision_matrix → heatmap / decision_figure
"""
import html, json, sys, threading
from pathlib import Path
import numpy as np
import pandas as pd


# ----------------------------------------------------------------- الإعدادات والسجل
def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8'))
    for k in ('decisions', 'thresholds', 'labels', 'entity_columns', 'population_columns', 'category_map'):
        assert k in cfg, f'config.json ينقصه القسم: {k}'
    return cfg


class Log(list):
    """سجل القرارات والأعداد (يُكتب في analysis_decisions_log.csv)."""
    def note(self, item, value, detail=''): self.append(dict(item=item, value=value, detail=detail))
    def to_frame(self): return pd.DataFrame(self)


def category_label(value, cfg):
    v = str(value).strip()
    for m in cfg['category_map']:
        if v.startswith(m['prefix']): return m['label']
    return None


# ----------------------------------------------------------------- التحميل
def load_entities(path, cfg, log=None):
    """يقرأ جدول الكيانات (CSV أو Excel) ويضيف في الذاكرة عمود group (الاسم المختصر للتصنيف؛ None إن لم يُعرف).
    خيارات config للبيانات المختلفة: entity_sheet (ورقة Excel)، category = null مع single_category_label (ملف بتخصص واحد)، entity_header_row (رقم صف العناوين إن لم يكن الأول)،
    region_normalize = {"strip": true, "remove_prefix": "المنطقة "} لتوحيد أسماء المناطق مع جدول السكان. الملف الأصلي لا يتغير."""
    c = cfg['entity_columns']; p = Path(path)
    if p.suffix.lower() in ('.xlsx', '.xls'):
        df = pd.read_excel(p, sheet_name=cfg.get('entity_sheet', 0), header=cfg.get('entity_header_row', 0), dtype=str).fillna('')
    else:
        df = pd.read_csv(p, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    df.columns = [str(x).strip() for x in df.columns]          # مسافات زائدة في عناوين الأعمدة (في الذاكرة فقط)
    missing = [v for v in c.values() if v and v not in df.columns]
    assert not missing, f'أعمدة غير موجودة في {p.name}: {missing} (الموجود: {list(df.columns)})'
    df = df.rename(columns={c['name']: 'name', c['region']: 'region', **({c['category']: 'category'} if c.get('category') else {})})
    if not c.get('category'):
        df['category'] = cfg.get('single_category_label', 'الكل')
        if log is not None: log.note('single_category', cfg.get('single_category_label', 'الكل'), 'الملف بلا عمود تصنيف: كل الكيانات تخصص واحد')
    rn = cfg.get('region_normalize')
    if rn:
        before = df.region.copy()
        if rn.get('strip', True): df['region'] = df.region.str.strip()
        for pre in ([rn['remove_prefix']] if isinstance(rn.get('remove_prefix'), str) else rn.get('remove_prefix') or []):
            df['region'] = df.region.str.replace('^' + pre.strip() + r'\s+', '', regex=True)
        if log is not None: log.note('region_normalized', int((before != df.region).sum()), f'توحيد أسماء المناطق في الذاكرة: {rn}')
    al = cfg.get('region_aliases') or {}          # أسماء بديلة وافق عليها الإنسان، مثل {"مهد الذهب": "المهد"}
    if al:
        n = int(df.region.isin(al).sum()); df['region'] = df.region.replace(al)
        if log is not None: log.note('region_aliases', n, '، '.join(f'{k} ← {v}' for k, v in al.items()))
    cc = cfg.get('count_columns')                 # ملف مجمّع: كل صف = عدد كيانات (مجموع هذه الأعمدة) بدل كيان واحد
    if cc:
        miss = [x for x in cc if x not in df.columns]; assert not miss, f'أعمدة العدد غير موجودة: {miss}'
        df['weight'] = df[cc].apply(pd.to_numeric, errors='raise').sum(axis=1)
        if log is not None: log.note('count_columns', int(df.weight.sum()), 'ملف مجمّع؛ العدد = ' + ' + '.join(cc))
    df['group'] = df.category.map(lambda v: category_label(v, cfg))
    if log is not None: log.note(f'rows:{p.name}', len(df))
    return df


def load_population(path, cfg, log=None):
    c = cfg['population_columns']
    P = pd.read_csv(path, encoding='utf-8-sig')
    for col, val in (cfg.get('population_filter') or {}).items():     # مثال: {"region_key": "الجوف"} لتحليل محافظات منطقة واحدة
        assert col in P.columns, f'عمود الفلترة غير موجود في ملف السكان: {col}'
        P = P[P[col] == val].copy()
        if log is not None: log.note('population_filter', f'{col} = {val}', f'{len(P)} وحدة')
    assert {c['region_key'], c['population']} <= set(P.columns), f'أعمدة السكان غير موجودة: {c}'
    P = P[[c['region_key'], c['population']]].rename(columns={c['region_key']: 'region_key', c['population']: 'population'})   # العمودان المطلوبان فقط
    exp = cfg.get('expected_population_total')
    if exp is not None:
        assert int(P.population.sum()) == int(exp), f'مجموع السكان {int(P.population.sum()):,} لا يطابق المتوقع {int(exp):,}'
    if log is not None: log.note('population_total', int(P.population.sum()), f'{len(P)} {cfg.get("unit_label", "منطقة")}')
    return P



# عناوين عربية لنسخة Excel فقط (ملفات CSV تبقى بأسماء إنجليزية ثابتة ليقرأها الكود والوكيل)
AR_HEADERS = {
    'region': 'المنطقة', 'region_key': 'المنطقة', 'group': 'التخصص', 'associations': 'عدد الجمعيات',
    'population_2022': 'السكان 2022', 'per_100k': 'لكل 100 ألف', 'national_per_100k': 'المتوسط الوطني لكل 100 ألف',
    'index_vs_national': 'المؤشر مقابل المتوسط الوطني', 'missing_to_reach_national': 'الجمعيات الناقصة لبلوغ المتوسط',
    'low_confidence': 'أرقام قليلة؟', 'recommendation': 'التوصية', 'confidence': 'مستوى الثقة', 'priority_rank': 'ترتيب الأولوية',
    'foundations': 'عدد المؤسسات', 'funders_group8': 'مؤسسات داعمة للعمل الخيري', 'share_funders': 'نسبة المؤسسات الداعمة',
    'demand_pressure': 'ضغط الطلب على التخصص', 'demand_level': 'مستوى ضغط الطلب', 'weighted_missing': 'الناقص مرجّحاً بالطلب',
    'demand_rank': 'الترتيب بعد عدسة الطلب', 'establishments_share_pct': 'حصة التخصص من المنشآت %', 'beneficiaries_share_pct': 'حصة التخصص من المستفيدين %',
    'item': 'البند', 'step': 'الخطوة', 'value': 'القيمة', 'detail': 'التفصيل',
    'per_100k_all_groups': 'لكل 100 ألف (كل التخصصات)', 'groups_below_half_national': 'عدد التخصصات تحت نصف المتوسط',
    'missing_today': 'الناقص اليوم', 'missing_2030': 'الناقص في 2030', 'needed_2030': 'المطلوب في 2030',
    'pop_2022': 'السكان 2022', 'pop_2030': 'السكان 2030 (متوقع)', 'growth_pct': 'نمو السكان %',
    'extra_by_2030': 'زيادة الناقص حتى 2030', 'backtest_error_pct': 'خطأ الاختبار الرجعي %', 'method': 'الطريقة'}


def save_table(df, path_no_ext, index=False):
    """يحفظ الجدول CSV (للكود) وXLSX (يُفتح بدبل كليك في Excel دون مشاكل الفاصل). إن لم تتوفر openpyxl يُكتفى بـ CSV."""
    p = Path(path_no_ext)
    df.to_csv(p.with_suffix('.csv'), index=index, encoding='utf-8-sig')
    try:
        with pd.ExcelWriter(p.with_suffix('.xlsx'), engine='openpyxl') as w:
            x = df.rename(columns=AR_HEADERS)
            if index: x.index.name = AR_HEADERS.get(df.index.name, df.index.name)
            x.to_excel(w, index=index, sheet_name='data')
            ws = w.sheets['data']; ws.sheet_view.rightToLeft = True; ws.freeze_panes = 'A2'
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 45)
    except ImportError:
        print('openpyxl غير مثبتة: حُفظ CSV فقط (pip install openpyxl لإخراج xlsx)', file=sys.stderr)


# ----------------------------------------------------------------- الحساب
def prepare(E, P, cfg, log):
    d, n0 = cfg['decisions'], len(E)
    national = E.region.str.startswith(cfg.get('national_region_prefix', '\0'))
    uncl = E.group.isna()
    log.note('excluded_national_entities', int(national.sum()), 'نطاق وطني لا يُنسب لمنطقة' if d['exclude_national'] else 'لم تُستبعد')
    log.note('excluded_unclassified', int(uncl.sum()), 'تصنيف غير معرّف في category_map' if d['exclude_unclassified'] else 'لم تُستبعد')
    keep = pd.Series(True, index=E.index)
    if d['exclude_national']: keep &= ~national
    if d['exclude_unclassified']: keep &= ~uncl
    D = E[keep].copy()
    assert len(D), f'لا توجد صفوف بعد الاستبعاد: {int(uncl.sum())} من {n0} تصنيفها غير معرّف في category_map (راجع أسماء التصنيفات في الملف)'
    assert D.region.nunique() >= 2, f'الملف فيه منطقة واحدة فقط ({", ".join(D.region.unique())}): المقارنة بالمتوسط الوطني تحتاج منطقتين على الأقل'
    unmatched = set(D.region) - set(P.region_key)
    if unmatched and cfg['decisions'].get('exclude_unmatched_units'):      # قرار بشري: استبعاد الوحدات التي لا سكان لها (يُسجَّل بأسمائها وعددها)
        cnt = D[D.region.isin(unmatched)].region.value_counts()
        log.note('excluded_unmatched_units', int(cnt.sum()), '، '.join(f'{k} ({v})' for k, v in cnt.items()))
        D = D[~D.region.isin(unmatched)].copy(); unmatched = set()
    assert not unmatched, f'مناطق بلا سكان: {unmatched}'
    D = D.merge(P[['region_key', 'population']], left_on='region', right_on='region_key', how='left')
    assert D.population.notna().all()
    log.note('rows_in_rate', len(D), f'من {n0}')
    return D


def rates(D, P, cfg):
    groups = [m['label'] for m in cfg['category_map']]
    cnt = (D.groupby(['region', 'group']).weight.sum() if 'weight' in D else D.groupby(['region', 'group']).size()).unstack(fill_value=0).reindex(index=P.region_key, columns=groups, fill_value=0)
    pop = P.set_index('region_key').population
    per100k = cnt.div(pop, axis=0) * 100000
    nat_cnt = cnt.sum(); nat_rate = nat_cnt / pop.sum() * 100000
    index = per100k.div(nat_rate, axis=1)
    assert int(cnt.values.sum()) == (int(D.weight.sum()) if 'weight' in D else len(D)), 'مجموع الخلايا لا يطابق عدد الكيانات المحسوبة'
    return dict(cnt=cnt, per100k=per100k, nat_cnt=nat_cnt, nat_rate=nat_rate, index=index, pop=pop)


def tables(R, cfg, out, log):
    t = cfg['thresholds']; cnt, per100k, nat_cnt, nat_rate, index, pop = (R[k] for k in ('cnt', 'per100k', 'nat_cnt', 'nat_rate', 'index', 'pop'))
    rows = []
    for r in cnt.index:
        for g in cnt.columns:
            rows.append(dict(region=r, group=g, associations=int(cnt.at[r, g]), population_2022=int(pop[r]),
                             per_100k=round(per100k.at[r, g], 2), national_per_100k=round(nat_rate[g], 2),
                             index_vs_national=round(index.at[r, g], 2),
                             missing_to_reach_national=round(max(nat_rate[g] * pop[r] / 1e5 - cnt.at[r, g], 0), 1),
                             low_confidence=bool(cnt.at[r, g] < t['min_region_count'] or nat_cnt[g] < t['min_national_count'])))
    L = pd.DataFrame(rows); save_table(L, out / 'tables/rate_per100k_region_group')
    G = L[(L.index_vs_national < t['low_ratio']) & (L.national_per_100k > 0)].sort_values('missing_to_reach_national', ascending=False)
    save_table(G, out / 'tables/gaps_ranked')
    S = pd.DataFrame({'population_2022': pop, 'associations': cnt.sum(axis=1)})
    S['per_100k_all_groups'] = (S.associations / S.population_2022 * 1e5).round(2)
    S['index_vs_national'] = (S.per_100k_all_groups / (nat_cnt.sum() / pop.sum() * 1e5)).round(2)
    S['groups_below_half_national'] = (index < t['low_ratio']).sum(axis=1)
    save_table(S.sort_values('per_100k_all_groups'), out / 'tables/region_summary', index=True)
    log.note('national_per_100k_all_groups', round(nat_cnt.sum() / pop.sum() * 1e5, 2), f'{int(nat_cnt.sum())} جمعية لكل {int(pop.sum()):,} نسمة')
    log.note('gaps_listed', len(G), f'خلايا أقل من {t["low_ratio"]} من المتوسط الوطني')
    return L, G, S


def foundations_layer(F, P, cfg, out, log):
    if not cfg['decisions']['foundations_as_support']: return None
    f = F[~F.region.str.startswith(cfg.get('national_region_prefix', '\0'))].copy()
    f['is_funder_group'] = f.group.eq(cfg.get('funder_category_label'))
    pop = P.set_index('region_key').population
    T = f.groupby('region').agg(foundations=('name', 'size'), funders_group8=('is_funder_group', 'sum')).reindex(P.region_key, fill_value=0)
    T['per_100k'] = (T.foundations / pop * 1e5).round(2)
    T['share_funders'] = (T.funders_group8 / T.foundations.replace(0, np.nan)).round(2)
    save_table(T, out / 'tables/foundations_support_layer', index=True)
    log.note('foundations_in_support_layer', int(T.foundations.sum()), 'طبقة داعمة، خارج معدل الجمعيات')
    return T


def recommend(idx, cfg):
    t, lb = cfg['thresholds'], cfg['labels']
    return lb['priority'] if idx < t['low_ratio'] else (lb['high'] if idx >= t['high_ratio'] else lb['ok'])


def demand_lens(demand_path, cfg, out, log):
    """عدسة الطلب: ضغط التخصص = حصته من المستفيدين ÷ حصته من المنشآت (مسح منشآت القطاع غير الربحي، وطني).
    أكبر من 1 = عليه طلب أكبر من حجمه. لا تُغيّر التوصية؛ تضيف بعداً للترتيب داخل «أولوية دعم»."""
    dc = cfg.get('demand', {'high': 1.2, 'low': 0.8, 'labels': {'high': 'ضغط مرتفع', 'mid': 'متوازن', 'low': 'ضغط منخفض'}})
    d = pd.read_csv(demand_path, encoding='utf-8-sig')
    groups = [m['label'] for m in cfg['category_map']]
    assert set(d.group) == set(groups), f'تصنيفات ملف الطلب لا تطابق category_map: {set(d.group) ^ set(groups)}'
    d['demand_pressure'] = (d.beneficiaries_share_pct / d.establishments_share_pct).round(2)
    lab = dc['labels']
    d['demand_level'] = np.where(d.demand_pressure >= dc['high'], lab['high'], np.where(d.demand_pressure < dc['low'], lab['low'], lab['mid']))
    d = d.sort_values('demand_pressure', ascending=False)
    save_table(d[['group', 'establishments_share_pct', 'beneficiaries_share_pct', 'demand_pressure', 'demand_level']], out / 'tables/demand_pressure')
    for k, v in (('high', dc['high']), ('low', dc['low'])): log.note(f'config:demand_{k}', v)
    log.note('demand_high_groups', int((d.demand_level == lab['high']).sum()), '، '.join(d[d.demand_level == lab['high']].group))
    return d


def decision_matrix(L, cfg, out, log, demand=None):
    lb = cfg['labels']; M = L.copy()
    M['recommendation'] = M.index_vs_national.map(lambda v: recommend(v, cfg))
    M['confidence'] = np.where(M.low_confidence, lb['few'], 'كافية')
    M['priority_rank'] = np.nan
    pr = M[(M.recommendation == lb['priority']) & (~M.low_confidence)].sort_values('missing_to_reach_national', ascending=False)
    M.loc[pr.index, 'priority_rank'] = range(1, len(pr) + 1)
    order = {lb['priority']: 0, lb['ok']: 1, lb['high']: 2}
    M = M.sort_values(['recommendation', 'priority_rank', 'region'], key=lambda c: c.map(order) if c.name == 'recommendation' else c)
    if demand is not None:          # أعمدة إضافية في النهاية؛ الأعمدة الأصلية لا تتغير
        M = M.merge(demand[['group', 'demand_pressure', 'demand_level']], on='group', how='left')
        M['weighted_missing'] = (M.missing_to_reach_national * M.demand_pressure).round(1)
        M['demand_rank'] = np.nan
        dr = M[(M.recommendation == lb['priority']) & (~M.low_confidence)].sort_values('weighted_missing', ascending=False)
        M.loc[dr.index, 'demand_rank'] = range(1, len(dr) + 1)
    save_table(M.drop(columns='low_confidence'), out / 'tables/decision_matrix')
    for k in ('priority', 'ok', 'high'):
        sub = M[M.recommendation == lb[k]]
        log.note(f'decision:{lb[k]}', len(sub), f'منها {int(sub.low_confidence.sum())} بأرقام قليلة')
    return M


# ----------------------------------------------------------------- الرسم
def render_png(html_path, png_path, width=1400):
    """HTML → PNG عبر Chromium (يعرض العربية صحيحاً). إن تعذّر يبقى ملف HTML."""
    res = {}
    def run():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page(viewport={'width': width, 'height': 700}, device_scale_factor=2)
                pg.goto(Path(html_path).resolve().as_uri()); pg.screenshot(path=str(png_path), full_page=True); b.close()
        except Exception as e: res['e'] = e
    t = threading.Thread(target=run); t.start(); t.join()
    if 'e' in res: print('تعذّر PNG، استخدمي ملف HTML:', res['e'], file=sys.stderr)


def color(ratio):
    """مقياس متباعد: برتقالي (فجوة) ← محايد ← أزرق (تركّز)، على لوغاريتم النسبة."""
    t = 0.0 if ratio <= 0 else float(np.clip(np.log2(ratio), -2, 2)) / 2
    lo, mid, hi = (217, 95, 2), (247, 247, 247), (33, 102, 172)
    a, b = (lo, mid) if t < 0 else (mid, hi)
    w = abs(t) if t < 0 else t
    w = 1 - w if t < 0 else w
    c = [round(a[i] + (b[i] - a[i]) * w) for i in range(3)]
    return f'rgb({c[0]},{c[1]},{c[2]})', ('#fff' if (t < -0.55 or t > 0.55) else '#1d2b33')


_FONT = 'font-family:"Segoe UI",Tahoma,Arial,"DejaVu Sans",sans-serif'


def decision_figure(M, R, cfg, out):
    lb, t = cfg['labels'], cfg['thresholds']; cols = list(R['per100k'].columns)
    order = list(M.groupby('region').associations.sum().div(M.groupby('region').population_2022.first()).sort_values().index)
    style = {lb['priority']: ('#D95F02', '#fff'), lb['ok']: ('#ECEFF1', '#37474F'), lb['high']: ('#2166AC', '#fff')}
    h = ['<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>',
         f'body{{{_FONT};margin:16px;color:#1d2b33;background:#fff}}',
         'h1{font-size:18px;margin:0 0 4px}.s{color:#55656d;font-size:12px;margin-bottom:10px}',
         'table{border-collapse:separate;border-spacing:2px;font-size:11.5px}th{background:#1F4E5F;color:#fff;padding:6px 8px;font-weight:600;max-width:96px}',
         'td{padding:8px 6px;text-align:center;min-width:78px;border:2px solid transparent;border-radius:3px}td.r{background:#eef4f6;text-align:right;font-weight:600;color:#1d2b33}',
         'td.few{border:2px dashed #111}.lg{display:flex;gap:14px;margin:10px 0;font-size:12px;flex-wrap:wrap}.lg span.b{display:inline-block;width:14px;height:14px;vertical-align:middle;margin-left:5px;border-radius:2px}',
         '.k{margin-top:8px;font-size:11px;color:#55656d}</style></head><body>',
         '<h1>مصفوفة القرار: أين الأولوية للدعم؟</h1>',
         f'<div class="s">كل خانة = توصية لمنطقة وتخصص. «{lb["priority"]}»: المعدل أقل من {t["low_ratio"]} من المتوسط الوطني. «{lb["high"]}»: أعلى من {t["high_ratio"]} مرة. الإطار المنقط = {lb["few"]} (مؤشر أولي).</div>',
         '<div class="lg">' + ''.join(f'<div><span class="b" style="background:{style[k][0]}"></span>{k}</div>' for k in style) +
         f'<div><span class="b" style="border:2px dashed #111"></span>{lb["few"]}</div></div>',
         '<table><tr><th>المنطقة</th>' + ''.join(f'<th>{html.escape(c)}</th>' for c in cols) + '</tr>']
    idx = M.set_index(['region', 'group'])
    for r in order:
        h.append(f'<tr><td class="r">{html.escape(r)}</td>')
        for g in cols:
            row = idx.loc[(r, g)]; bg, fg = style[row.recommendation]
            h.append(f'<td class="{"few" if row.low_confidence else ""}" style="background:{bg};color:{fg}">{row.recommendation}</td>')
        h.append('</tr>')
    h.append('</table><div class="k">المصدر: ملف الجمعيات الأهلية (بعد التنظيف) والسكان 2022 (الهيئة العامة للإحصاء). التوصية مؤشر للمراجعة، وليست حكماً نهائياً: الرقم يعني عدد الجمعيات المسجلة، وليس حجم الخدمة المقدمة.</div></body></html>')
    hp = out / 'figures/decision_matrix.html'; hp.write_text('\n'.join(h), encoding='utf-8')
    render_png(hp, out / 'figures/decision_matrix.png')


def heatmap(R, out):
    cnt, per100k, nat_rate, index, pop = (R[k] for k in ('cnt', 'per100k', 'nat_rate', 'index', 'pop'))
    order = (cnt.sum(axis=1) / pop).sort_values().index; cols = list(per100k.columns)
    h = ['<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>',
         f'body{{{_FONT};margin:16px;color:#1d2b33;background:#fff}}',
         'h1{font-size:18px;margin:0 0 4px}.s{color:#55656d;font-size:12px;margin-bottom:10px}',
         'table{border-collapse:collapse;font-size:12px}th{background:#1F4E5F;color:#fff;padding:6px 8px;font-weight:600;max-width:96px}',
         'td{padding:6px 8px;text-align:center;border:1px solid #fff;min-width:64px}td.r{background:#eef4f6;text-align:right;font-weight:600}',
         '.n{font-size:10px;opacity:.75;display:block}.k{margin-top:8px;font-size:11px;color:#55656d}</style></head><body>',
         '<h1>الجمعيات الأهلية لكل 100 ألف نسمة حسب المنطقة والتخصص</h1>',
         '<div class="s">اللون = نسبة المعدل إلى المتوسط الوطني للتخصص (برتقالي: أقل من المتوسط، أزرق: أعلى). الرقم الكبير = لكل 100 ألف، والصغير = عدد الجمعيات. المناطق مرتبة من الأقل تغطية إلى الأعلى.</div>',
         '<table><tr><th>المنطقة</th>' + ''.join(f'<th>{html.escape(c)}</th>' for c in cols) + '</tr>']
    for r in order:
        h.append(f'<tr><td class="r">{html.escape(r)}</td>')
        for g in cols:
            bg, fg = color(index.at[r, g])
            h.append(f'<td style="background:{bg};color:{fg}">{per100k.at[r, g]:.1f}<span class="n">{int(cnt.at[r, g])}</span></td>')
        h.append('</tr>')
    h.append('<tr><td class="r">المتوسط الوطني</td>' + ''.join(f'<td class="r" style="text-align:center">{nat_rate[g]:.1f}</td>' for g in cols) + '</tr></table>')
    h.append('<div class="k">المصدر: ملف الجمعيات الأهلية (بعد التنظيف) والسكان 2022 من الهيئة العامة للإحصاء. تُستبعد الجمعيات غير المصنفة والكيانان الوطنيان. الخلايا ذات العدد القليل مؤشر أولي.</div></body></html>')
    hp = out / 'figures/heatmap_per100k.html'; hp.write_text('\n'.join(h), encoding='utf-8')
    render_png(hp, out / 'figures/heatmap_per100k.png')


# ----------------------------------------------------------------- التشغيل الكامل
def run_all(cfg, assoc_path, pop_path, out, found_path=None, demand_path=None):
    """يشغّل الخط كاملاً ويعيد (R, L, G, S, M, log). هذه هي الدالة التي يستدعيها الوكيل."""
    out = Path(out); (out / 'tables').mkdir(parents=True, exist_ok=True); (out / 'figures').mkdir(parents=True, exist_ok=True)
    log = Log()
    for sec in ('decisions', 'thresholds', 'labels'):
        for k, v in cfg[sec].items(): log.note(f'config:{k}', v)
    for k in ('comparison_label', 'unit_label', 'unit_plural', 'entity_singular', 'entity_plural', 'extra_limit'):
        if cfg.get(k): log.note(f'config:{k}', cfg[k])
    E = load_entities(assoc_path, cfg, log); P = load_population(pop_path, cfg, log)
    D = prepare(E, P, cfg, log); R = rates(D, P, cfg)
    L, G, S = tables(R, cfg, out, log)
    if found_path: foundations_layer(load_entities(found_path, cfg, log), P, cfg, out, log)
    demand = demand_lens(demand_path, cfg, out, log) if demand_path else None
    heatmap(R, out); M = decision_matrix(L, cfg, out, log, demand); decision_figure(M, R, cfg, out)
    save_table(log.to_frame(), out / 'analysis_decisions_log')     # CSV للكود + xlsx بعناوين عربية للقراءة
    return R, L, G, S, M, log
