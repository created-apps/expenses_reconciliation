"""Parse ICICI credit-card statement text (pdftotext -layout) into transactions.
Validates against the statement summary totals."""
import re,sys,json
txt=open(sys.argv[1]).read(); lines=txt.split('\n')
START=re.compile(r'(\d{2}/\d{2}/\d{4})\s+(\d{10,12})\s')
rx=re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(\d{10,12})\s+(.*?)\s{2,}(-?\d+)\s+(?:([\d.]+(?:\s?[A-Z]{3})?)\s+)?([\d,]+\.\d\d)(\s*CR)?\s*$')
card=None; out=[]; bad=[]
def body(l):
    m=START.search(l); return l[m.start():] if m else None
for i,l in enumerate(lines):
    m=re.search(r'(\d{4}X{8}\d{4})',l)
    if m: card=m.group(1)[-4:]
    b=body(l)
    if not b: continue
    full=b.rstrip(); mm=rx.match(full); k=1
    while not mm and k<=3 and i+k<len(lines) and not START.search(lines[i+k]):
        nxt=lines[i+k].strip()
        if nxt: full=full+'  '+nxt
        mm=rx.match(full); k+=1
    if not mm: bad.append((i,b.strip())); continue
    d,ser,desc,pts,intl,amt,cr=mm.groups()
    if intl and not re.search(r'[A-Z]{3}',intl):  # currency code on the next line (e.g. "86.12" / "USD")
        for k in (1,2):
            if i+k<len(lines) and re.search(r'\b(USD|EUR|GBP|SGD)\b\s*$',lines[i+k]): intl=intl+' '+re.search(r'\b(USD|EUR|GBP|SGD)\b',lines[i+k]).group(1); break
    out.append(dict(date=d,ser=ser,desc=re.sub(r'\s+',' ',desc).strip(),pts=int(pts),intl=(intl or '').strip(),amt=float(amt.replace(',','')),cr=bool(cr),card=card))
def money(label):
    m=re.search(label+r'[\s\S]{0,400}?`([\d,]+\.\d\d)',txt); return None
deb=round(sum(x['amt'] for x in out if not x['cr']),2); crs=round(sum(x['amt'] for x in out if x['cr']),2)
# summary figures: row after the headings, order = Total due, Previous, Purchases, Cash adv, Payments
nums=[float(v.replace(',','')) for v in re.findall(r'`([\d,]+\.\d\d)',txt)[:5]]
print(f'{len(out)} transactions parsed, {len(bad)} unparsed; serials unique: {len({x["ser"] for x in out})==len(out)}')
print(f'debits {deb:,.2f} vs summary Purchases/Charges {nums[2]:,.2f} -> {"OK" if abs(deb-nums[2])<0.005 else "MISMATCH"}')
print(f'credits {crs:,.2f} vs summary Payments/Credits {nums[4]:,.2f} -> {"OK" if abs(crs-nums[4])<0.005 else "MISMATCH"}')
print(f'previous + purchases - credits = {nums[1]+nums[2]-nums[4]:,.2f} vs total due {nums[0]:,.2f}')
for b in bad: print('UNPARSED',b)
json.dump(out,open(sys.argv[2],'w'),indent=1)
