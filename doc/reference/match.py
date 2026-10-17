"""Match statement lines to invoices. Rules: bank charges & credits are not matched;
Amazon and IndiGo use exact subset sums of invoice totals within a date window; others match on exact amount (INR, or USD for foreign lines)."""
import json,sys,re,subprocess,os,itertools
from datetime import datetime,timedelta
d=sys.argv[1]
T=json.load(open(d+'/stmt/txns.json')); INV=json.load(open(d+'/invoices_all.json'))
P=lambda s:datetime.strptime(s.replace('-','.').replace('/','.'),'%d.%m.%Y')
# de-duplicate identical invoice files (same invoice number + total)
seen={}; 
for i,x in enumerate(INV):
    k=(x['vendor'],x.get('inv'),x.get('total'),tuple(x.get('amounts',[])))
    x['id']=i; x['dup_of']=seen.get(k) if x.get('inv') else None
    if x.get('inv') and k not in seen: seen[k]=x['file']
# IndiGo grand totals and PNR
for x in INV:
    if x['vendor']=='indigo':
        t=subprocess.run(['pdftotext','-layout',os.path.join(d,'inv',x['file']),'-'],capture_output=True,text=True).stdout
        x['total']=float(re.search(r'Grand Total.*?([\d,]+\.\d\d)\s*$',t,re.M).group(1).replace(',',''))
        x['odate']=datetime.strptime(re.search(r'Date : (\d{2}-\w{3}-\d{4})',t).group(1),'%d-%b-%Y').strftime('%d.%m.%Y')
        x['pnr']=re.search(r'PNR\s*:\s*([A-Z0-9]{6})',t).group(1)
ALIAS=[('amazon',r'ASSPL|AMAZONIN'),('macfos',r'MACFOS'),('dtdc',r'DTDC'),('indigo',r'INDIGO'),('makemytrip',r'MAKEMYTRIP'),('tripify',r'TRIPIFY'),
 ('vistaprint',r'VISTAPRINT'),('fathom',r'FATHOM'),('vercel',r'VERCEL'),('supabase',r'SUPABASE'),('zapier',r'ZAPIER'),('railway',r'RAILWAY'),
 ('anthropic',r'ANTHROPIC'),('mailchimp',r'MAILCHIMP'),('periskope',r'PERISKOPE'),('genspark',r'GENSPARK'),('scriptit',r'SCRIPTIT'),('airtel',r'AIRTEL'),
 ('google',r'GOOGLE'),('aqtronics',r'AQTRONICS'),('shott',r'SHOTT'),('calendly',r'CALENDLY'),('phantombuster',r'PHANTOMBUSTER'),('microsoft',r'MICROSOFT'),
 ('openai',r'OPENAI'),('wix',r'WIX'),('robocraze',r'ROBOCRAZE'),('thinkrobotics',r'ATLANTIS ROBOTICS')]
FEES=r'^(DCC Fee|SGST-CI|CGST-CI|Late Payment Fee|Interest Charges)'
def vend(desc):
    for v,p in ALIAS:
        if re.search(p,desc,re.I): return v
    return None
used=set(); res={}
def mark(t,status,files,basis):
    res[t['ser']]=dict(status=status,files=files,basis=basis)
# 1) bank charges and credits
for t in T:
    if re.match(FEES,t['desc']): mark(t,'Bank charge',[],'Card fee or GST on fee; no vendor invoice')
    elif 'PAYMENT RECEIVED' in t['desc'].upper(): mark(t,'Payment',[],'Card bill payment')
# 1b) reversals: a debit and a credit from the same merchant for the same amount within 7 days
key=lambda t:re.sub(r'\s+',' ',t['desc'].upper())[:18]
for c in [t for t in T if t['cr'] and 'PAYMENT RECEIVED' not in t['desc'].upper()]:
    for t in T:
        if not t['cr'] and t['ser'] not in res and key(t)==key(c) and abs(t['amt']-c['amt'])<0.005 and abs((P(t['date'])-P(c['date'])).days)<=7:
            mark(t,'Reversed',[],f"Reversed by credit on {c['date']} (SerNo {c['ser']}); no invoice needed")
            res[c['ser']]=dict(status='Reversed',files=[],basis=f"Reverses the charge on {t['date']} (SerNo {t['ser']})"); break
for t in T:
    if t['cr'] and t['ser'] not in res: mark(t,'Credit – manual',[],'Refund or credit; handled manually by the client')
# 2) subset-sum vendors (amazon, indigo): joint per posting date
def subsets(pool,target):
    out=[]
    for k in range(1,min(len(pool),12)+1):
        for c in itertools.combinations(pool,k):
            if round(sum(x['total'] for x in c)*100)==round(target*100): out.append(c)
        if len(out)>50: break
    return out
for v,back,fwd in (('amazon',3,0),('indigo',3,1)):
    lines=[t for t in T if t['ser'] not in res and vend(t['desc'])==v]
    lines.sort(key=lambda t:(P(t['date']),t['amt']))
    # pass 1: single exact match; pass 2: subsets
    for passno in (1,2):
        for t in lines:
            if t['ser'] in res: continue
            td=P(t['date'])
            pool=[x for x in INV if x['vendor']==v and x['id'] not in used and not x['dup_of'] and x.get('total') and not x.get('credit')
                  and td-timedelta(days=back)<=P(x.get('odate') or x['date'])<=td+timedelta(days=fwd)]
            sols=[s for s in subsets(pool,t['amt']) if passno==2 or len(s)==1]
            if not sols: continue
            if v=='indigo':  # prefer invoices of one PNR
                same=[s for s in sols if len({x['pnr'] for x in s})==1]; sols=same or sols
            if len(sols)>1 and v=='amazon':
                # prefer subsets that keep each order's invoices together, then closest dates
                def score(s):
                    orders={x['order'] for x in s}
                    split=sum(1 for x in pool if x['order'] in orders and x not in s)
                    return (split,sum(abs((td-P(x['odate'])).days) for x in s))
                sols.sort(key=score)
                if score(sols[0])==score(sols[1]): mark(t,'Review',[x['file'] for x in sols[0]],f'{len(sols)} invoice combinations add up to this amount'); continue
            elif len(sols)>1: mark(t,'Review',[x['file'] for x in sols[0]],f'{len(sols)} invoice combinations add up to this amount'); continue
            s=sols[0]
            for x in s: used.add(x['id'])
            mark(t,'Matched',[x['file'] for x in s],'Exact amount' if len(s)==1 else f'{len(s)} invoices sum exactly to the charge')
# 3) other vendors: global assignment by exact amount (INR, within Rs1 for paise rounding, or USD for foreign lines), closest date first
MON={m:i for i,m in enumerate(['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],1)}
def pdates(x):
    out=[]
    for s_ in x.get('dates',[])+[x.get('date') or '', x.get('odate') or '']:
        s_=s_.strip()
        m=re.match(r'(\d{1,2})[./-](\d{1,2})[./-](\d{4})$',s_)
        if m:
            for a_,b_ in ((m[2],m[1]),(m[1],m[2])):
                try: out.append(datetime(int(m[3]),int(a_),int(b_))); break
                except ValueError: pass
            continue
        m=re.match(r'(\d{1,2})[- ]([A-Za-z]{3})[a-z]*[- ,]+(\d{4})',s_) or None
        if m and m[2].lower() in MON: out.append(datetime(int(m[3]),MON[m[2].lower()],int(m[1]))); continue
        m=re.match(r'([A-Za-z]{3})[a-z]* (\d{1,2}),? (\d{4})',s_)
        if m and m[1].lower() in MON: out.append(datetime(int(m[3]),MON[m[1].lower()],int(m[2])))
    return [x_ for x_ in out if 2026<=x_.year<=2026]
# Macfos (Robu): use the invoice's own Total, not line amounts
for x in INV:
    if x['vendor']=='macfos':
        t=subprocess.run(['pdftotext','-layout',os.path.join(d,'inv',x['file']),'-'],capture_output=True,text=True).stdout
        tot=re.findall(r'\bTotal\s+₹\s*([\d,]+\.\d\d)',t)
        if tot: x['amounts']=[float(tot[-1].replace(',',''))]
pairs=[]
rest=[t for t in T if t['ser'] not in res]
for t in rest:
    v=vend(t['desc']); td=P(t['date'])
    if not v: continue
    usd=float(re.match(r'[\d.]+',t['intl']).group(0)) if t['intl'] else None
    for x in INV:
        if x['vendor']!=v or x['id'] in used or x['dup_of']: continue
        amts=set(x.get('amounts',[]))|({x['total']} if x.get('total') else set())
        ds=pdates(x); gap=min((abs((td-q).days) for q in ds),default=None)
        if gap is not None and gap>7: continue
        if t['amt'] in amts: b='Exact INR amount'; rank=0
        elif usd and (usd in amts or usd in set(x.get('usd',[]))): b=f'USD {usd:g} matches invoice'; rank=0
        elif any(abs(t['amt']-a)<=1.0 for a in amts): b='INR amount within Rs 1 (paise rounding on invoice)'; rank=1
        else: continue
        pairs.append((rank, gap if gap is not None else 5, t['ser'], x['id'], b))
pairs.sort()
byser={t['ser']:t for t in T}; done=set()
for rank,gap,ser,iid,b in pairs:
    if ser in done or iid in used: continue
    x=INV[iid]; used.add(iid); done.add(ser)
    mark(byser[ser],'Matched',[x['file']],b)
for t in rest:
    if t['ser'] in res: continue
    v=vend(t['desc'])
    if not v: mark(t,'No invoice',[],'No invoice supplied for this merchant'); continue
    td=P(t['date'])
    near=[x for x in INV if x['vendor']==v and x['id'] not in used and not x['dup_of'] and any(abs((td-q).days)<=7 for q in pdates(x))]
    if len(near)==1 and not t['intl'] and near[0].get('usd'):
        mark(t,'Review',[near[0]['file']],'Only invoice from this vendor near this date; it is in USD and the statement shows INR only'); used.add(near[0]['id']); continue
    mark(t,'Missing invoice',[],f'No {v} invoice with this amount')
json.dump(res,open(d+'/matches.json','w'),indent=1)
from collections import Counter
print(Counter(r['status'] for r in res.values()))
for t in T:
    r=res[t['ser']]
    if r['status']!='Bank charge': print(t['date'],t['desc'][:30].ljust(30),('%.2f'%t['amt']).rjust(10),'CR' if t['cr'] else '  ',r['status'].ljust(16),'|',', '.join(r['files'])[:70],'|',r['basis'])
print('\nUNUSED invoices:')
for x in INV:
    if x['id'] not in used and not x['dup_of']: print('  ',x['vendor'],x['file'],x.get('total') or (x.get('amounts') or [])[-3:],x.get('odate') or x.get('date') or '')
print('duplicates:',[(x['file'],x['dup_of']) for x in INV if x['dup_of']])
