# -*- coding: utf-8 -*-
"""
فحص وتنظيف جودة البيانات — الجمعيات والمؤسسات الأهلية
======================================================
يفحص الملف من أربع نواحٍ: القيم المفقودة، المكررة، الشاذة، المسافات —
ثم ينظّفه دون إضافة أي عمود ودون تخمين التصنيف الفرعي الأول (ويحذف فقط الصفوف المطابقة تماماً)، ويُخرج لكل ملف:
  1) <name>_cleaned.xlsx : ملخص الجودة + البيانات المنظفة (نفس الأعمدة السبعة) + سجل التعديلات + للمراجعة اليدوية
  2) <name>_quality_report.pdf : تقرير PDF بالنتائج قبل/بعد
  3) <name>_quality_report.html : نفس التقرير بصيغة HTML (احتياطي)

التشغيل (جهازك):
    pip install pandas openpyxl playwright
    playwright install chromium
    python dq_check.py Non_profit_Associations.xlsx Non_profit_Foundations.xlsx --out results
    (تمرير الملفين معاً: يحدد الملفان معاً قائمة التصنيفات الفرعية المعتمدة؛ ويخرج لكل ملف xlsx + csv + pdf)

التشغيل (Google Colab):
    !pip install -q playwright && playwright install --with-deps chromium
    !apt-get -qq install -y fonts-noto-core      # خطوط عربية
    !python dq_check.py Non_profit_Associations.xlsx Non_profit_Foundations.xlsx --out results

ملاحظة: يُستخدم متصفح Chromium (عبر Playwright) لتحويل التقرير إلى PDF لأنه يعرض
الحروف العربية واتجاه النص من اليمين لليسار بشكل صحيح. إن لم يكن متاحاً، يُحفظ
التقرير بصيغة HTML ويمكن طباعته إلى PDF من المتصفح (Ctrl+P).
"""
import argparse, html, re, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

UNK = 'غير محدد'                      # وسم صريح للقيمة المفقودة التي لا يمكن استنتاجها
THRESHOLD, MIN_SUPPORT = 0.60, 3       # شرط الاستنتاج: 60% فأكثر من 3 سجلات مماثلة على الأقل

# أحرف مخفية: رموز الاتجاه (LRM/RLM…)، المسافة الصلبة، BOM، الجدولة والأسطر
INVISIBLE = r'[​-‏‪-‮ ﻿\t\r\n]'
DIRECTION = r'[​-‏‪-‮﻿]'
TASHKEEL = r'[ً-ْ]'

# ---- قاموس التوحيد الإملائي (خاص بهذه البيانات؛ الصيغة المعتمدة = الأكثر تكراراً/الرسمية) ----
SPELLING = {
    'التصنيف الفرعي الاول': {
        'الصحة النفسية والتدخل في الازمات': 'الصحة النفسية والتدخل في الأزمات',
        'التعليم العالي': 'التعليم العالي (المراحل الجامعية)',
        'التنمية الاجتماعية و الاقتصادية': 'التنمية الاجتماعية والاقتصادية والمجتمعية',
        'خدمات الفئات الاجتماعية خدمات تعزيز الاعتماد على الذات': 'خدمات الفئات الاجتماعية',
        'البيئة خدمات الحد من التلوث ومكافحته': 'البيئة'},
    'التصنيف الفرعي الثاني': {
        'رعاية الموهبة والموهبين': 'رعاية الموهبة والموهوبين',
        'منظمات الاستشارات المحسابىة': 'منظمات الاستشارات المحاسبية'},
    'جهة الإشراف': {
        'وزارةالحجوالعمرة': 'وزارة الحج و العمرة',
        'الهيئة العامة للترفية': 'الهيئة العامة للترفيه'},
}
# قيم في التصنيف الفرعي الأول ليست تصنيفاً صالحاً (اسم عمود، وصف عام، أو قيمة من مستوى آخر)
INVALID_SUB1 = {'التصنيف النوعي', 'توعوي', 'الاسري'}
KEEP_AS_SUB1 = {'الخدمات القانونية', 'المسؤولية الاجتماعية', 'المسؤولية الاجتماعية في قطاع النقل'}  # معتمدة رغم ندرتها
VALID_MIN = 4          # التصنيف الفرعي الأول يُعدّ معتمداً إذا تكرر 4 مرات فأكثر في البيانات المرجعية
ROYAL = 'منشأة بأمر ملكي'
# أخطاء كتابية واضحة في الأسماء (أنماط regex)
NAME_FIX = [
    (r'(?<=\S) ين (?=\S)', ' بن '),          # "عبدالله ين ناصر" ← "عبدالله بن ناصر"
    (r'وأولادة(?=\s|$)', 'وأولاده'),
    (r'^مؤسسه(?=\s)', 'مؤسسة'),
    (r'(?<=\s)الخيريه$', 'الخيرية'),
]


# =============================================================================
# 1) القراءة
# =============================================================================
def load(path):
    """يقرأ الملف كنصوص، ويكتشف صف العناوين تلقائياً (أول صف ممتلئ بالكامل)."""
    probe = pd.read_excel(path, header=None, dtype=str, keep_default_na=False, nrows=20)
    hdr = next(i for i, r in probe.iterrows() if (r.str.strip() != '').all())
    df = pd.read_excel(path, header=hdr, dtype=str, keep_default_na=False)
    df.index = df.index + hdr + 2          # رقم الصف كما يظهر في Excel
    return df, hdr


def clean_ws(v):
    return re.sub(r'\s+', ' ', re.sub(INVISIBLE, ' ', v)).strip()


# =============================================================================
# 2) القياس (يُستخدم قبل التنظيف وبعده)
# =============================================================================
def profile(df):
    out = []
    for c in df.columns:
        s = df[c]
        out.append(dict(
            col=c,
            missing=int((s.str.strip() == '').sum()),
            unk=int((s == UNK).sum()),
            ws=int((s != s.map(clean_ws)).sum()),
            invisible=int(s.str.contains(DIRECTION).sum()),
            unique=int(s.nunique()),
        ))
    norm_names = df.iloc[:, 0].map(normalise_name)
    return dict(cols=out, rows=len(df),
                dup_rows=int(df.duplicated().sum()),
                dup_rows_trim=int(df.apply(lambda c: c.map(clean_ws)).duplicated().sum()),
                dup_names=int(df.iloc[:, 0].map(clean_ws).duplicated().sum()),
                near_dup=int(norm_names.duplicated(keep=False).sum()))


def normalise_name(s):
    s = clean_ws(s)
    s = re.sub(TASHKEEL + '|ـ', '', s); s = re.sub('[أإآ]', 'ا', s)
    s = s.replace('ة', 'ه').replace('ى', 'ي'); s = re.sub(r'^(ال)?جمعيه\s+', '', s)
    return s.strip()


# =============================================================================
# 3) التنظيف
# =============================================================================
def clean(raw, ref=None, basic_only=False):
    """ref: بيانات مرجعية (كل الملفات المدخلة بعد التنظيف الأساسي) يُستنتج منها التسلسل الهرمي."""
    df = raw.copy()
    C = list(df.columns); N, R, G, S1, S2, T, M = C
    log, review = [], []

    def setv(i, col, new, kind, how):
        old = df.at[i, col]
        if old != new:
            log.append(dict(row=i, entity=clean_ws(df.at[i, N]), col=col, old=old, new=new, kind=kind, how=how))
            df.at[i, col] = new

    def flag(i, col, val, issue, action):
        review.append(dict(row=i, entity=df.at[i, N] if i != '—' else '—', col=col, val=val, issue=issue, action=action))

    # --- (أ) المسافات والأحرف المخفية ---
    for c in C:
        for i, v in df[c].items():
            nv = clean_ws(v)
            if nv != v:
                k = []
                if re.search(DIRECTION, v): k.append('رمز اتجاه/حرف مخفي')
                if ' ' in v: k.append('مسافة صلبة (NBSP)')
                if v != v.strip(): k.append('مسافة بداية/نهاية')
                if re.search(r'\S\s{2,}\S', v): k.append('مسافة مزدوجة')
                setv(i, c, nv, 'مسافات', ' + '.join(k) or 'تنظيف مسافات')

    # --- (ب) الصفوف المكررة تماماً: تُحذف النسخ الزائدة ويبقى الأول ---
    dup = df.duplicated(keep='first')
    for i in df.index[dup]:
        first = df.index[(df == df.loc[i]).all(axis=1)][0]
        log.append(dict(row=i, entity=df.at[i, N], col='(الصف كاملاً)', old='صف مطابق تماماً للصف ' + str(first),
                        new='— حُذف —', kind='صف مكرر (حُذف)', how=f'نسخة مطابقة في كل الأعمدة للصف {first}؛ أُبقي الأول'))
    df = df[~dup].copy()

    # --- (ج) التوحيد الإملائي ---
    for col, mp in SPELLING.items():
        for i in df.index[df[col].isin(mp)]:
            setv(i, col, mp[df.at[i, col]], 'توحيد/إملاء', 'توحيد مع الصيغة المعتمدة')
    for i, v in df[N].items():
        nv = v
        for pat, rep in NAME_FIX: nv = re.sub(pat, rep, nv)
        if nv != v: setv(i, N, nv, 'توحيد/إملاء', 'تصحيح خطأ كتابي واضح في الاسم')

    # --- (د) القيم الشاذة ---
    g5 = [g for g in df[G].unique() if g.startswith('المجموعة الخامسة') and '(' in g and 'البيئ' in g.split('(')[1]]
    if g5:
        for i in df.index[df[G].str.startswith('المجموعة الخامسة') & (df[G] != g5[0])]:
            setv(i, G, g5[0], 'قيمة شاذة (وصف خاطئ)', 'وصف المجموعة الخامسة منسوخ من المجموعة الرابعة؛ استُبدل بوصف البيئة الصحيح')
    for i, v in df[N].items():
        nv = re.sub(r'(' + TASHKEEL + r')\1+', r'\1', v)
        if nv != v: setv(i, N, nv, 'قيمة شاذة (تشكيل مكرر)', 'حذف حركة مكررة')
    if basic_only:
        return df, log, review

    REF = df if ref is None else ref
    counts = REF[S1].value_counts()
    valid_s1 = ({v for v, n in counts.items() if n >= VALID_MIN} | KEEP_AS_SUB1) - INVALID_SUB1 - {'', ROYAL, UNK}

    def mode_map(keys, target):
        m = {}
        sub = REF[(REF[target] != '') & (REF[target] != ROYAL) & REF[keys].ne('').all(axis=1)]
        if target == S1: sub = sub[sub[S1].isin(valid_s1)]
        for k, g in sub.groupby(keys)[target]:
            top, n = Counter(g).most_common(1)[0]
            k = k if isinstance(k, tuple) else (k,)      # مفاتيح موحّدة عبر إصدارات pandas
            m[k] = (top, n / len(g), len(g))
        return m

    # قيم في الفرعي الأول ليست تصنيفاً معتمداً (اسم عمود، كلمة عامة، قيمة من مستوى آخر، أو "منشأة بأمر ملكي" تحت مجموعة فعلية)
    bad = df.index[(df[S1] != '') & ~df[S1].isin(valid_s1) & ~((df[S1] == ROYAL) & (df[G] == ROYAL))]
    for i in bad:
        ov = df.at[i, S1]
        setv(i, S1, UNK, 'قيمة شاذة (مستوى خاطئ)',
             f'"{ov}" ليست تصنيفاً فرعياً أول معتمداً؛ وُسمت "{UNK}" دون تخمين')

    # --- (هـ) القيم المفقودة: استنتاج من التسلسل الهرمي ثم وسم الباقي ---
    def impute(target, keys, idx):
        mm = mode_map(keys, target)
        for i in idx:
            k = tuple(df.loc[i, keys])
            if k in mm and mm[k][1] >= THRESHOLD and mm[k][2] >= MIN_SUPPORT:
                top, share, n = mm[k]
                setv(i, target, top, 'قيمة مفقودة (مُستنتجة)',
                     f'استنتاج من التسلسل الهرمي ({" + ".join(keys)}) — {share:.0%} من {n} سجل مماثل')
            else:
                flag(i, target, '', 'قيمة مفقودة — تعذّر الاستنتاج بثقة', f'وُسمت "{UNK}" — للمراجعة اليدوية')

    impute(G, [S1, S2], df.index[(df[G] == '') & (df[S1] != '') & (df[S2] != '')])
    impute(G, [S2], df.index[(df[G] == '') & (df[S1] == '') & (df[S2] != '')])
    impute(M, [G, S2], df.index[(df[M] == '') & (df[S2] != '') & (df[G] != ROYAL)])
    for c in C:
        for i in df.index[df[c] == '']:
            setv(i, c, UNK, 'قيمة مفقودة (غير محدد)', f'لا توجد معلومات كافية؛ وُسمت "{UNK}" بدلاً من التخمين')

    # --- (و) حالات تُرصد ولا تُعدّل آلياً ---
    for i in df.index[df[G] == ROYAL]:
        flag(i, f'{G} / {S1} / {S2}', ROYAL, 'قيمة شاذة: وصف لطريقة التأسيس في أعمدة التصنيف',
             'أُبقيت (لا يوجد عمود مناسب) — يُنصح بتصنيفها يدوياً')
    for i in df.index[df[R].str.startswith('كافة')]:
        flag(i, R, df.at[i, R], 'قيمة نادرة: نطاق وطني وليس منطقة إدارية', 'أُبقيت — تُعامل كفئة مستقلة في التحليل الجغرافي')
    ct = df[(df[G] != UNK) & (df[S1] != UNK)].groupby([S1, G]).size()
    tot = ct.groupby(level=0).sum()
    for (s1, g), n in ct.items():
        if n / tot[s1] < 0.03 and n <= 3:
            for i in df.index[(df[S1] == s1) & (df[G] == g)]:
                flag(i, f'{G} ↔ {S1}', f'{g[:40]}… ↔ {s1}',
                     f'عدم اتساق هرمي: هذا التصنيف الفرعي يقع في مجموعة أخرى في {tot[s1]-n} من {tot[s1]} سجل', 'للمراجعة')
    for i in df.index[(df[M] == 'وزارة الحج و العمرة') & ~df[S1].str.contains('ضيوف')]:
        flag(i, f'{M} ↔ {S1}', f'{df.at[i, M]} ↔ {df.at[i, S1]}', 'عدم اتساق بين جهة الإشراف والتصنيف', 'للمراجعة')
    key = df[N].map(normalise_name)
    for _, g in df[key.duplicated(keep=False)].groupby(key):
        rows = list(g.index)
        for i in rows:
            extra = ''
            if 'طريف' in df.at[i, N] and df.at[i, R] != 'الحدود الشمالية':
                extra = f' — طريف تتبع الحدود الشمالية والمسجّل "{df.at[i, R]}": يُرجّح أنه تكرار بمنطقة خاطئة'
            flag(i, N, df.at[i, R], f'تكرار محتمل (اسم متطابق بعد التطبيع) مع الصف {", ".join(map(str, (r for r in rows if r != i)))}{extra}',
                 'لم يُحذف — يحتاج تحقق من رقم الترخيص')
    for c in C:
        if df[c].nunique() == 1:
            flag('—', c, df[c].iloc[0], f'عمود ثابت: قيمة واحدة لكل السجلات ({len(df)})', 'لا يضيف قيمة تحليلية — يُستبعد من التحليل دون حذفه')
    return df, log, review


# =============================================================================
# 4) تصدير Excel
# =============================================================================
def export_excel(path, raw, df, log, review, before, after, hdr):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter as L
    F = 'Arial'; HF = Font(name=F, bold=True, color='FFFFFF'); HFILL = PatternFill('solid', fgColor='1F4E5F')
    CH = PatternFill('solid', fgColor='FFF2CC'); UF = PatternFill('solid', fgColor='F4CCCC')
    wb = Workbook(); wb.remove(wb.active)

    def sheet(title, headers, rows, widths):
        ws = wb.create_sheet(title); ws.sheet_view.rightToLeft = True; ws.append(headers)
        for c in ws[1]: c.font, c.fill, c.alignment = HF, HFILL, Alignment(horizontal='center', wrap_text=True)
        for r in rows: ws.append(r)
        for row in ws.iter_rows(min_row=2):
            for c in row: c.font = Font(name=F); c.alignment = Alignment(vertical='top', wrap_text=True)
        for i, w in enumerate(widths, 1): ws.column_dimensions[L(i)].width = w
        ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
        return ws

    summ = [[b['col'], b['missing'], a['missing'], a['unk'], b['ws'], a['ws'], b['unique'], a['unique']]
            for b, a in zip(before['cols'], after['cols'])]
    summ += [[], ['عدد السجلات', before['rows'], after['rows']], ['صفوف مكررة تماماً', before['dup_rows'], after['dup_rows']],
             ['أسماء مكررة حرفياً', before['dup_names'], after['dup_names']],
             ['سجلات بأسماء متشابهة بعد التطبيع', before['near_dup'], after['near_dup']], []]
    summ += [[k, v] for k, v in Counter(l['kind'] for l in log).items()]
    summ += [['إجمالي الخلايا المعدّلة', len(log)], [],
             ['خلية صفراء = عُدّلت، خلية حمراء = وُسمت "غير محدد". لم يُضف أي عمود.'],
             ['أرقام الصفوف في "سجل التعديلات" و"للمراجعة اليدوية" تشير إلى الملف الأصلي.']]
    sheet('ملخص الجودة', ['البند', 'مفقود قبل', 'مفقود بعد', '"غير محدد" بعد', 'مسافات قبل', 'مسافات بعد', 'فريدة قبل', 'فريدة بعد'],
          summ, [40, 12, 12, 14, 12, 12, 12, 12])
    ws = sheet('البيانات المنظفة', list(df.columns), df.values.tolist(), [34, 16, 48, 34, 38, 12, 34])
    pos = {i: k + 2 for k, i in enumerate(df.index)}
    for l in log:
        if l['row'] in pos and l['col'] in df.columns:
            ws.cell(pos[l['row']], list(df.columns).index(l['col']) + 1).fill = UF if l['new'] == UNK else CH
    sheet('سجل التعديلات', ['رقم الصف الأصلي', 'اسم الكيان', 'العمود', 'قبل', 'بعد', 'نوع المشكلة', 'طريقة المعالجة'],
          [[l['row'], l['entity'], l['col'], repr(l['old']) if l['kind'] == 'مسافات' else l['old'], l['new'], l['kind'], l['how']] for l in log],
          [12, 30, 20, 40, 40, 22, 55])
    sheet('للمراجعة اليدوية', ['رقم الصف الأصلي', 'اسم الكيان', 'العمود', 'القيمة', 'الملاحظة', 'الإجراء'],
          [[r['row'], r['entity'], r['col'], r['val'], r['issue'], r['action']] for r in review], [12, 32, 24, 36, 60, 36])
    wb.save(path)


# =============================================================================
# 5) تقرير PDF
# =============================================================================
def e(x): return html.escape(str(x))


def build_html(src_name, raw, df, log, review, before, after):
    rows, ncols = before['rows'], len(raw.columns)
    cells = rows * ncols
    miss_b = sum(c['missing'] for c in before['cols']); miss_a = sum(c['missing'] for c in after['cols'])
    unk_a = sum(c['unk'] for c in after['cols'])
    ws_b = sum(c['ws'] for c in before['cols']); ws_a = sum(c['ws'] for c in after['cols'])
    inferred = sum(1 for l in log if l['kind'] == 'قيمة مفقودة (مُستنتجة)')
    kinds = Counter(l['kind'] for l in log)
    complete_b = 100 * (1 - miss_b / cells)
    complete_a = 100 * (1 - (miss_a + unk_a) / (after['rows'] * ncols))
    removed = before['rows'] - after['rows']
    del_txt = 'ولم يُحذف أي سجل' if removed == 0 else f'وحُذف {removed} صف مكرر تماماً فقط (بقيت نسخته الأولى)'

    # مخطط: المفقود لكل عمود قبل/بعد
    mx = max(c['missing'] for c in before['cols']) or 1
    bars = ''
    for b, a in zip(before['cols'], after['cols']):
        bars += f'''<div class="bar-row"><div class="lbl">{e(b['col'])}</div><div class="bars">
          <div class="bar before" style="width:{b['missing']/mx*85:.1f}%"></div><span class="v">{b['missing']}</span><br>
          <div class="bar after" style="width:{a['unk']/mx*85:.1f}%"></div><span class="v">{a['unk']}</span></div></div>'''
    kx = max(kinds.values())
    kbars = ''.join(f'<div class="bar-row"><div class="lbl">{e(k)}</div><div class="bars"><div class="bar kind" '
                    f'style="width:{v/kx*85:.1f}%"></div><span class="v">{v}</span></div></div>' for k, v in kinds.most_common())

    col_rows = ''.join(f"<tr><td>{e(b['col'])}</td><td>{b['missing']}</td><td>{a['unk']}</td><td>{b['ws']}</td>"
                       f"<td>{a['ws']}</td><td>{b['invisible']}</td><td>{b['unique']}</td><td>{a['unique']}</td></tr>"
                       for b, a in zip(before['cols'], after['cols']))

    # أمثلة لكل نوع مشكلة
    examples = ''
    for k, _ in kinds.most_common():
        ex = [l for l in log if l['kind'] == k][:4]
        examples += f'<h3>{e(k)} <span class="muted">({kinds[k]})</span></h3><table class="small"><tr><th>الصف</th><th>العمود</th><th>قبل</th><th>بعد</th><th>المعالجة</th></tr>'
        for l in ex:
            old = repr(l['old']) if k == 'مسافات' else (l['old'] or '— فارغ —')
            examples += f"<tr><td>{l['row']}</td><td>{e(l['col'])}</td><td>{e(old[:70])}</td><td>{e(l['new'][:70])}</td><td>{e(l['how'])}</td></tr>"
        examples += '</table>'

    rev = ''.join(f"<tr><td>{e(r['row'])}</td><td>{e(r['entity'])}</td><td>{e(r['col'])}</td><td>{e(r['issue'])}</td><td>{e(r['action'])}</td></tr>"
                  for r in review)
    rev_kinds = Counter(re.split(r' —|:| \(', r['issue'])[0] for r in review)

    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>تقرير جودة البيانات</title>
<style>
 @page {{ size: A4; margin: 16mm 14mm; }}
 body {{ font-family: "Segoe UI","Tahoma","Arial","Noto Naskh Arabic","Noto Sans Arabic","KacstOne","DejaVu Sans",sans-serif; color:#1d2b33; font-size:10.5pt; line-height:1.55; }}
 h1 {{ font-size:22pt; margin:0 0 4px; color:#1F4E5F; }} h2 {{ font-size:14pt; color:#1F4E5F; border-bottom:2px solid #1F4E5F; padding-bottom:3px; margin-top:22px; }}
 h3 {{ font-size:11pt; margin:14px 0 4px; }} .muted {{ color:#6b7a82; font-weight:normal; }}
 .kpis {{ display:flex; gap:8px; margin:14px 0; }} .kpi {{ flex:1; border:1px solid #d5dde1; border-radius:6px; padding:8px 10px; }}
 .kpi b {{ display:block; font-size:17pt; color:#1F4E5F; }} .kpi span {{ font-size:9pt; color:#55656d; }}
 table {{ width:100%; border-collapse:collapse; margin:6px 0; font-size:9.5pt; }} th {{ background:#1F4E5F; color:#fff; padding:5px; }}
 td {{ border-bottom:1px solid #e3e8eb; padding:4px 5px; vertical-align:top; }} tr:nth-child(even) td {{ background:#f6f8f9; }}
 table.small {{ font-size:8.5pt; }} .bar-row {{ display:flex; align-items:center; margin:5px 0; }}
 .lbl {{ width:34%; font-size:9pt; }} .bars {{ flex:1; }} .bar {{ display:inline-block; height:11px; border-radius:2px; vertical-align:middle; min-width:1px; }}
 .before {{ background:#C0504D; }} .after {{ background:#E8A33D; }} .kind {{ background:#1F4E5F; }} .v {{ font-size:8.5pt; margin-right:5px; }}
 .legend span {{ display:inline-block; width:10px; height:10px; margin:0 4px 0 2px; vertical-align:middle; }}
 .box {{ background:#eef4f6; border-right:4px solid #1F4E5F; padding:8px 12px; margin:10px 0; }} .pb {{ page-break-before:always; }}
 ul {{ margin:4px 0; padding-right:18px; }}
</style></head><body>
<h1>تقرير فحص جودة البيانات</h1>
<div class="muted">الملف: {e(src_name)} · {rows:,} سجل × {ncols} أعمدة · تاريخ التوليد: {datetime.now():%Y-%m-%d %H:%M}</div>

<div class="kpis">
 <div class="kpi"><b>{len(log):,}</b><span>خلية عُدّلت (من {cells:,})</span></div>
 <div class="kpi"><b>{miss_b} ← {miss_a}</b><span>خلايا فارغة قبل → بعد</span></div>
 <div class="kpi"><b>{inferred}</b><span>قيمة مفقودة استُنتجت بثقة</span></div>
 <div class="kpi"><b>{ws_b} ← {ws_a}</b><span>مشكلات مسافات</span></div>
 <div class="kpi"><b>{before['dup_rows']}</b><span>صفوف مكررة تماماً</span></div>
</div>
<div class="box"><b>الخلاصة:</b> لم يُضف أي عمود {del_txt}. الاكتمال الفعلي ارتفع من {complete_b:.1f}% (فراغات) إلى
{complete_a:.1f}% بعد استبعاد الخلايا الموسومة "{UNK}"، و{unk_a} خلية بقيت بلا معلومة كافية فوُسمت صراحة بدلاً من التخمين.
أكبر مخاطر البيانات: السجلات غير المصنفة وعدم الاتساق الهرمي في التصنيفات، لا التكرار.</div>

<h2>١. ملخص الأعمدة قبل وبعد</h2>
<table><tr><th>العمود</th><th>مفقود قبل</th><th>"غير محدد" بعد</th><th>مسافات قبل</th><th>مسافات بعد</th><th>أحرف مخفية</th><th>فريدة قبل</th><th>فريدة بعد</th></tr>{col_rows}</table>
<p class="muted">انخفاض "القيم الفريدة" بعد التنظيف ناتج عن دمج الكتابات المختلفة للقيمة نفسها.</p>

<h2>٢. القيم المفقودة</h2>
<div class="legend"><span style="background:#C0504D"></span>مفقود قبل <span style="background:#E8A33D"></span>بقي "غير محدد" بعد الاستنتاج</div>
{bars}
<ul><li>الاستنتاج من التسلسل الهرمي (المجموعة + التصنيف الفرعي الثاني) فقط إذا اتفق {THRESHOLD:.0%} فأكثر من {MIN_SUPPORT} سجلات مماثلة على الأقل؛ نسبة الثقة مسجّلة لكل خلية.</li>
<li>السجلات الخالية من كل أعمدة التصنيف وجهة الإشراف وُسمت "{UNK}" ولم تُخمَّن.</li></ul>

<h2>٣. التكرار</h2>
<table><tr><th>المؤشر</th><th>قبل</th><th>بعد</th></tr>
<tr><td>عدد السجلات</td><td>{before['rows']}</td><td>{after['rows']}</td></tr>
<tr><td>صفوف مكررة تماماً</td><td>{before['dup_rows']}</td><td>{after['dup_rows']}</td></tr>
<tr><td>صفوف مكررة بعد توحيد المسافات</td><td>{before['dup_rows_trim']}</td><td>{after['dup_rows_trim']}</td></tr>
<tr><td>أسماء مكررة حرفياً</td><td>{before['dup_names']}</td><td>{after['dup_names']}</td></tr>
<tr><td>سجلات بأسماء متشابهة بعد التطبيع (همزات، تاء مربوطة، كلمة "جمعية")</td><td>{before['near_dup']}</td><td>{after['near_dup']}</td></tr></table>
<p>التشابه في الأسماء لا يعني تكراراً مؤكداً (قد تكون كيانات مختلفة في مناطق مختلفة)، لذلك لم تُحذف وأُدرجت في قائمة المراجعة. الصفوف المطابقة في كل الأعمدة فقط هي التي تُحذف.</p>

<h2>٤. توزيع التعديلات حسب نوع المشكلة</h2>{kbars}

<h2 class="pb">٥. أمثلة من سجل التعديلات</h2>{examples}

<h2 class="pb">٦. حالات للمراجعة اليدوية ({len(review)})</h2>
<p>{'، '.join(f'{e(k)}: {v}' for k, v in rev_kinds.most_common())}</p>
<table class="small"><tr><th>الصف</th><th>الكيان</th><th>العمود</th><th>الملاحظة</th><th>الإجراء</th></tr>{rev}</table>

<h2>٧. المنهجية</h2>
<ul>
<li><b>المسافات:</b> إزالة المسافات في البداية والنهاية، دمج المسافات المزدوجة، حذف رموز الاتجاه المخفية (LRM/RLM) والمسافة الصلبة.</li>
<li><b>الشاذة:</b> قيم في غير مستواها الهرمي، وصف مجموعة منسوخ خطأً، أخطاء إملائية، تشكيل مكرر، قيم نادرة أو غير منطقية.</li>
<li><b>المكررة:</b> مطابقة تامة للصفوف، ثم مطابقة الأسماء بعد التطبيع.</li>
<li><b>المفقودة:</b> استنتاج مشروط بنسبة ثقة، وإلا وسم صريح "{UNK}".</li>
<li>كل تعديل موثّق برقم الصف الأصلي والقيمة قبل/بعد في ملف Excel المرافق (ورقة "سجل التعديلات").</li>
</ul></body></html>'''


def export_pdf(html_text, html_path, pdf_path):
    html_path.write_text(html_text, encoding='utf-8')
    # يُشغَّل في خيط مستقل لأن Playwright (sync) لا يعمل داخل حلقة asyncio الخاصة بـ Jupyter/Colab
    import threading
    result = {}
    t = threading.Thread(target=_render_pdf, args=(html_path, pdf_path, result)); t.start(); t.join()
    if 'error' in result:
        print(f"تعذّر إنشاء PDF ({result['error']}).\nافتح {html_path} في المتصفح واطبعه إلى PDF.", file=sys.stderr)
        return False
    return True


def _render_pdf(html_path, pdf_path, result):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page()
            pg.goto(html_path.resolve().as_uri()); pg.wait_for_load_state('networkidle')
            pg.pdf(path=str(pdf_path), format='A4', print_background=True,
                   display_header_footer=True, header_template='<span></span>',
                   footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#888">'
                                   '<span class="pageNumber"></span> / <span class="totalPages"></span></div>',
                   margin=dict(top='14mm', bottom='16mm', left='12mm', right='12mm'))
            b.close()
    except Exception as ex:
        result['error'] = ex


# =============================================================================
def run(input_paths, out_dir='dq_output'):
    """يمكن استدعاؤها من Colab/Jupyter:  run(['Non_profit_Associations.xlsx', 'Non_profit_Foundations.xlsx'], 'results')
    عند تمرير أكثر من ملف بنفس الأعمدة، يُستنتج التسلسل الهرمي من الملفات مجتمعة (مرجع أقوى)."""
    if isinstance(input_paths, (str, Path)): input_paths = [input_paths]
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    loaded = [(Path(p), *load(p)) for p in input_paths]
    same = len({tuple(r.columns) for _, r, _ in loaded}) == 1
    # المرجع المشترك يُستخدم فقط لتحديد قائمة التصنيفات الفرعية المعتمدة (تكرارها ≥ 4)، ولا يُخمَّن به أي تصنيف فرعي
    ref = pd.concat([clean(r, basic_only=True)[0] for _, r, _ in loaded], ignore_index=True) if same else None

    for src, raw, hdr in loaded:
        before = profile(raw)
        df, log, review = clean(raw, ref=ref)
        after = profile(df)
        removed = sum(1 for l in log if l['kind'] == 'صف مكرر (حُذف)')
        assert list(df.columns) == list(raw.columns), 'تغيّرت الأعمدة!'
        assert len(df) == len(raw) - removed, 'تغيّر عدد السجلات بغير حذف المكرر!'

        stem = src.stem
        export_excel(out / f'{stem}_cleaned.xlsx', raw, df, log, review, before, after, hdr)
        df.to_csv(out / f'{stem}_clean.csv', index=False, encoding='utf-8-sig')
        ok = export_pdf(build_html(src.name, raw, df, log, review, before, after),
                        out / f'{stem}_quality_report.html', out / f'{stem}_quality_report.pdf')
        print(f'\n[{src.name}] السجلات: {len(raw)} ← {len(df)} | الخلايا المعدّلة: {len(log)} | للمراجعة: {len(review)}')
        for k, v in Counter(l['kind'] for l in log).most_common(): print(f'  - {k}: {v}')
        print(f'  الملفات في: {out.resolve()}' + ('' if ok else ' (بدون PDF)'))
    return out


def main():
    ap = argparse.ArgumentParser(description='فحص وتنظيف جودة بيانات الجمعيات الأهلية')
    ap.add_argument('inputs', nargs='+', help='ملف أو أكثر بنفس الأعمدة'); ap.add_argument('--out', default='dq_output')
    a, _ = ap.parse_known_args()          # parse_known_args يتجاهل وسائط Jupyter الإضافية
    run(a.inputs, a.out)


if __name__ == '__main__':
    main()
