# -*- coding: utf-8 -*-
"""
استخراج جداول مسح منشآت القطاع غير الربحي 2018 (الهيئة العامة للإحصاء).
  جدول 1: التوزيع النسبي للمنشآت حسب التصنيف     جدول 9: التوزيع النسبي للمستفيدين     جدول 10: التحديات الرئيسية
الاستخدام:  python extract_survey2018.py <xlsx أو pdf> [out_dir]
  - ملف Excel من موقع الهيئة (المفضّل: أرقام بدقة كاملة وأسماء رسمية)
  - أو ملف PDF للمسح (احتياطي، يحتاج pip install pypdf)
المخرجات: survey2018_demand_clean.csv (10 تصنيفات: منشآت + مستفيدون) و survey2018_challenges_clean.csv و survey2018_log.csv
يتوقف إذا لم يكن عدد الصفوف صحيحاً أو لم يكن المجموع 100%. لا يُحسب هنا أي مؤشر مشتق.
"""
import re, sys
from pathlib import Path
import pandas as pd

# ترتيب الصفوف في المسح = ترتيب التصنيف النوعي الرسمي = نفس أسماء category_map في config.json
GROUPS = ['الثقافة والترفيه', 'التعليم والأبحاث', 'الصحة', 'الخدمات الاجتماعية', 'البيئة', 'التنمية والإسكان',
          'التأييد والمؤازرة', 'دعم العمل الخيري', 'الدعوة والتعليم الديني وضيوف الرحمن', 'الروابط المهنية']
CHECK = ['الثقاف', 'التعليم', 'الصحة', 'الاجتماعية', 'البيئة', 'التنمية', 'التأييد', 'دعم العمل', 'الدعوة', 'المهنية']   # تحقق أن الصف n هو التخصص n
LOG = []


def log(name, where, vals):
    s = sum(vals); assert abs(s - 100) < 0.1, f'{name}: المجموع {s:.3f}% وليس 100%'
    LOG.append(dict(step=name, where=where, rows=len(vals), sum_pct=round(s, 3)))


def from_xlsx(src):
    x = pd.ExcelFile(src)
    def sheet(key, n, name):
        sh = next((s for s in x.sheet_names if key in s), None); assert sh, f'لم أجد ورقة «{key}»'
        d = pd.read_excel(x, sh, header=None)
        d = d[pd.to_numeric(d[0], errors='coerce').between(1, n)]          # صفوف البنود المرقمة فقط
        assert len(d) == n, f'{name}: {len(d)} صفوف بدل {n}'
        vals = (pd.to_numeric(d[2]) * 100).round(3).tolist()            # النسب مخزنة كسوراً (0.3016) ← 30.16
        log(name, f'ورقة «{sh.strip()}»', vals)
        return d[1].astype(str).str.strip().tolist(), vals
    names, est = sheet('المنشآت', 10, 'جدول 1: المنشآت')
    names9, ben = sheet('المستفيدين', 10, 'جدول 9: المستفيدون')
    for i, (a, b) in enumerate(zip(names, names9)):
        assert CHECK[i] in a and CHECK[i] in b, f'ترتيب التصنيفات غير متوقع في الصف {i + 1}: {a} / {b}'
    ch_names, ch = sheet('التحديات', 6, 'جدول 10: التحديات')
    return est, ben, ch_names, ch


def from_pdf(src):
    from pypdf import PdfReader
    pages = [pg.extract_text() or '' for pg in PdfReader(src).pages]
    pct = lambda t: [float(v) for v in re.findall(r'(\d+(?:\.\d+)?)\s*%', t)]
    norm = lambda t: re.sub(r'\s+', '', t).lower()
    def table(key, n, name):
        i = next((i for i, t in enumerate(pages) if norm(key) in norm(t) and len(pct(t)) >= n), None); assert i is not None, f'لم أجد {name}'
        vals = pct(pages[i])[:n]; log(name, f'صفحة {i + 1}', vals); return vals
    ch_names = ['تحديات في التدفقات المالية', 'تحديات في التعامل مع البنوك', 'تحديات في توظيف أيدي عاملة ماهرة',
                'صعوبة الحصول على متطوعين', 'إجراءات الرقابة من الجهات الحكومية', 'نصوص الأنظمة واللوائح التشريعية']
    return table('Non-Profit Establishments', 10, 'جدول 1: المنشآت'), table('Beneficiaries', 10, 'جدول 9: المستفيدون'), ch_names, table('Challenges', 6, 'جدول 10: التحديات')


def main():
    src = Path(sys.argv[1]); out = Path(sys.argv[2] if len(sys.argv) > 2 else '.'); out.mkdir(parents=True, exist_ok=True)
    est, ben, ch_names, ch = (from_pdf if src.suffix.lower() == '.pdf' else from_xlsx)(src)
    pd.DataFrame({'group': GROUPS, 'establishments_share_pct': est, 'beneficiaries_share_pct': ben, 'year': 2018,
                  'scope_note': 'وطني؛ كل المنشآت غير الربحية؛ الهيئة العامة للإحصاء'}
                 ).to_csv(out / 'survey2018_demand_clean.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame({'challenge': ch_names, 'share_pct': ch, 'year': 2018}).to_csv(out / 'survey2018_challenges_clean.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(LOG).assign(source=src.name).to_csv(out / 'survey2018_log.csv', index=False, encoding='utf-8-sig')
    print('تم: 10 تصنيفات (منشآت + مستفيدون) و 6 تحديات | المجاميع:', ' / '.join(f"{l['sum_pct']}%" for l in LOG))


if __name__ == '__main__':
    main()
