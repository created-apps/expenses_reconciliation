"""Extract invoice facts from PDFs in a folder. Amazon invoices are split per invoice block."""
import re,sys,json,subprocess,os,glob
d=sys.argv[1]; out=[]
VEND=[('amazon',r'amazon|ASSPL|Amazon Seller Services'),('macfos',r'macfos|robu'),('dtdc',r'dtdc'),('indigo',r'InterGlobe|IndiGo|^TaxInvoice'),
 ('vistaprint',r'vistaprint|^VP_'),('fathom',r'fathom'),('vercel',r'vercel'),('supabase',r'supabase'),('zapier',r'zapier'),('railway',r'railway'),
 ('anthropic',r'anthropic'),('mailchimp',r'mailchimp|intuit'),('periskope',r'periskope'),('genspark',r'genspark'),('scriptit',r'scriptit'),
 ('airtel',r'airtel'),('google',r'google'),('aqtronics',r'aqtronics'),('makemytrip',r'makemytrip|lemon tree|MMT'),('tripify',r'tripify|TFY'),
 ('created',r'^created|CREATED-'),('sembly',r'sembly'),('calendly',r'calendly'),('phantombuster',r'phantombuster'),('microsoft',r'microsoft'),
 ('openai',r'openai'),('wix',r'wix'),('robocraze',r'robocraze'),('shott',r'shott'),('thinkrobotics',r'thinkrobotics|atlantis')]
def vendor(f,t):
    for v,p in VEND:
        if re.search(p,f,re.I): return v
    head=t[:3000]
    for v,p in VEND:
        if re.search(p,head,re.I): return v
    return 'unknown'
money=re.compile(r'(?<![\d.])(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{1,2}|\d{2,7})(?![\d.,]*\d)')
for f in sorted(glob.glob(os.path.join(d,'*.pdf'))):
    fn=os.path.basename(f)
    t=subprocess.run(['pdftotext','-layout',f,'-'],capture_output=True,text=True).stdout
    v=vendor(fn,t)
    if v=='amazon' and 'Order Number' in t:
        cur=None; blocks=[]
        for p in t.split('\f'):
            if 'Order Number' in p:
                cur=dict(file=fn,vendor='amazon',order=re.search(r'Order Number:\s*([\d-]+)',p).group(1),
                  inv=(re.search(r'Invoice Number\s*:\s*(\S+)',p) or [0,None])[1],date=(re.search(r'Invoice Date\s*:\s*([\d.]+)',p) or [0,None])[1],
                  credit=bool(re.search(r'Credit Note',p,re.I)),txt=p); blocks.append(cur)
            elif cur: cur['txt']+=p
        for b in blocks:
            g=re.findall(r'TOTAL:[^\n]*',b['txt']); a=re.findall(r'₹\s?([\d,]+\.\d\d)',g[-1]) if g else []
            b['total']=float(a[-1].replace(',','')) if a else None; b.pop('txt'); out.append(b)
        continue
    amts=set()
    for m in re.finditer(r'(?:₹|Rs\.?|INR|\$|USD|US\$)\s?([\d,]+(?:\.\d{1,2})?)|([\d,]+\.\d{2})\b',t):
        s=(m.group(1) or m.group(2)).replace(',','')
        try:
            x=float(s)
            if 0<x<10_000_000: amts.add(round(x,2))
        except: pass
    usd=sorted({float(x.replace(',','')) for x in re.findall(r'(?:\$|USD\s?|US\$)\s?([\d,]+\.?\d*)',t) if x.replace(',','').replace('.','').isdigit()})
    dates=re.findall(r'\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ,]+\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})\b',t)
    invno=re.search(r'(?:Invoice\s*(?:No\.?|Number|#)\s*[:.]?\s*)([A-Z0-9][\w/-]{3,})',t,re.I)
    out.append(dict(file=fn,vendor=v,amounts=sorted(amts),usd=usd,dates=dates[:6],inv=invno.group(1) if invno else None,chars=len(t)))
json.dump(out,open(sys.argv[2],'w'),indent=1)
from collections import Counter
print(len(out),'records'); print(Counter(x['vendor'] for x in out))
print('amazon blocks',sum(x['vendor']=='amazon' and 'order' in x for x in out),'in files',len({x['file'] for x in out if 'order' in x}))
for x in out:
    if x['vendor']=='unknown' or (x['vendor']=='amazon' and 'order' not in x): print('CHECK',x['file'],x.get('amounts',[])[:8])
