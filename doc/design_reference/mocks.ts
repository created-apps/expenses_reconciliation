export type Status = 'Matched'|'Review'|'Missing invoice'|'No invoice'|'Reversed'|'Credit – manual'|'Payment'|'Bank charge'

export const transactions = [
  { date:'13/06/2026', id:'13598184078', description:'ASSPL Bangalore IN', amount:'₹2,557.44', status:'Matched' as Status, note:'8 invoices add up exactly to the charge', files:['130626_Amazon_187.16(2).pdf','130626_Amazon_198.pdf','130626_Amazon_220.pdf','130626_Amazon_238.pdf','130626_Amazon_499.pdf','130626_Amazon_928.27.pdf','130626_Amazon_98.01.pdf','130626_amazon_189(1).pdf'] },
  { date:'20/06/2026', id:'13642517948', description:'ASSPL Bangalore IN', amount:'₹52,539.00', status:'Review' as Status, note:'Closest invoice is ₹149.00 less', files:['200626_Amazon_52390.pdf'] },
  { date:'07/06/2026', id:'13562235353', description:'INDIGO AIRLINE GURGAON IN', amount:'₹15,846.00', status:'Review' as Status, note:'Two tickets on PNR EBU8WT total ₹16,581.00 (₹735.00 more)', files:[] },
  { date:'21/06/2026', id:'13647499190', description:'SUPABASE SINGAPORE SG*', amount:'₹12,036.13', foreign:'$122.25', status:'Matched' as Status, note:'USD amount matches invoice', files:['Supabase_.pdf'] },
  { date:'18/06/2026', id:'13629230456', description:'MACFOS LIMITED MUMBAI IN', amount:'₹611.00', status:'Matched' as Status, note:'', files:['190626_Macfos_715.pdf'] },
  { date:'19/06/2026', id:'13634979143', description:'MACFOS LIMITED MUMBAI IN', amount:'₹715.01', status:'Missing invoice' as Status, note:'No invoice with this amount was supplied', files:[] },
  { date:'12/06/2026', id:'13592897886', description:'ASSPL Bangalore IN', amount:'−₹52,990.00', status:'Credit – manual' as Status, note:'', files:[] },
  { date:'20/06/2026', id:'13642448945', description:'CREATED ANDHERI WEST IN', amount:'₹4,72,000.00', status:'Reversed' as Status, note:'Reversed by credit on 20/06/2026', files:[] },
  { date:'28/06/2026', id:'13685482676', description:'Interest Charges', amount:'₹64,735.74', status:'Bank charge' as Status, note:'', files:[] },
  { date:'10/06/2026', id:'13578455906', description:'CLICK TO PAY PAYMENT RECEIVED', amount:'−₹60,472.00', status:'Payment' as Status, note:'', files:[] },
]

export const statusCounts: {label:Status; count:number; amount:string}[] = [
 ['Review',5,'₹1,18,385'],['Missing invoice',20,'₹2,41,806'],['Matched',65,'₹7,88,422'],['No invoice',6,'₹42,190'],['Reversed',8,'₹5,22,000'],['Credit – manual',4,'−₹1,18,330'],['Payment',1,'−₹60,472'],['Bank charge',18,'₹1,09,910']
].map(([label,count,amount])=>({label:label as Status,count:count as number,amount:amount as string}))

export const invoiceFiles = ['200626_Amazon_52390.pdf','190626_Macfos_715.pdf','Supabase_.pdf','130626_Amazon_928.27.pdf','indigo_ebu8wt.jpg']
export const invoiceVendors = ['ASSPL Bangalore','MACFOS LIMITED','Supabase','ASSPL Bangalore','Indigo']
export const invoiceNumbers = ['52390','715','SB-2026-06','92827','EBU8WT']
export const invoiceDates = ['20/06/2026','19/06/2026','21/06/2026','13/06/2026','07/06/2026']
export const invoiceAmounts = ['₹52,390.00','₹715.00','₹12,036.13','₹928.27','₹16,581.00']
