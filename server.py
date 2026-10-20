#!/usr/bin/env python3
"""MTS Ticket Desk: private, zero-dependency SQLite ticket application."""
import base64, csv, hmac, html, io, json, os, secrets, sqlite3, threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('MTS_DB', ROOT / 'mts_tickets.sqlite3'))
HOST = os.environ.get('MTS_HOST', '127.0.0.1')
PORT = int(os.environ.get('MTS_PORT', '8765'))
PASSWORD = os.environ.get('MTS_PASSWORD', '')
LOCK = threading.Lock()
STATUSES = ['New','Diagnosing','Awaiting Parts','In Progress','Ready for Pickup','Completed','Cancelled']

STYLE = '''<style> :root{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e6eefb} header{background:#101e34;border-bottom:1px solid #233854;padding:18px 6%;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap} .brand{font-size:24px;font-weight:800;letter-spacing:.3px}.brand span{color:#47a6ff}nav{display:flex;gap:10px;flex-wrap:wrap}a{color:#7dc4ff;text-decoration:none}nav a,.btn,button{display:inline-block;border:1px solid #326a9a;border-radius:9px;background:#153b65;color:#f5fbff;padding:10px 14px;cursor:pointer;font-weight:600}nav a:hover,.btn:hover,button:hover{background:#205385}main{max-width:1180px;margin:32px auto;padding:0 20px}h1{font-size:29px;margin:0 0 20px}h2{font-size:20px}.muted,small{color:#a7b9d1}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:24px}.stat,.panel{background:#13233b;border:1px solid #273e59;border-radius:14px;padding:20px}.stat strong{font-size:30px;display:block;color:#75bdff}.toolbar{display:flex;gap:12px;flex-wrap:wrap;justify-content:space-between;align-items:center;margin:18px 0}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse;min-width:760px}th,td{text-align:left;padding:13px;border-bottom:1px solid #29405c;vertical-align:top}th{color:#a8c2df;font-size:13px;text-transform:uppercase}tr:hover td{background:#182c47}input,select,textarea{width:100%;padding:11px;background:#0b182b;border:1px solid #37516e;border-radius:8px;color:#f8fbff;font:inherit}input:focus,textarea:focus,select:focus{outline:2px solid #479fff}textarea{min-height:110px;resize:vertical}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.field{display:flex;flex-direction:column;gap:7px}.field.wide{grid-column:1/-1}.field label{font-weight:600;font-size:14px}.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.chip{border-radius:16px;padding:5px 9px;background:#244565;display:inline-block;font-size:12px;white-space:nowrap}.right{text-align:right}.danger{border-color:#75384a;background:#552338}.notice{background:#1a3b38;border:1px solid #357b68;border-radius:9px;padding:12px;margin:15px 0}footer{max-width:1180px;margin:24px auto;padding:12px 20px;color:#92a7c2;font-size:12px}@media(max-width:650px){.formgrid{grid-template-columns:1fr}.brand{font-size:20px}main{margin-top:20px}}</style>'''

def esc(x): return html.escape('' if x is None else str(x), quote=True)
def money(v): return '${:,.2f}'.format(float(v or 0))
def connect():
    c=sqlite3.connect(DB,timeout=15)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=15000')
    return c

def init():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('''CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, customer TEXT NOT NULL, phone TEXT, email TEXT, device TEXT NOT NULL, serial TEXT, issue TEXT NOT NULL, diagnosis TEXT, work_done TEXT, notes TEXT, status TEXT NOT NULL, estimate REAL NOT NULL DEFAULT 0, paid REAL NOT NULL DEFAULT 0)''')

def shell(title,body):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+' | MTS Ticket Desk</title>'+STYLE+'</head><body><header><div class="brand">MARKEY <span>TECH SOLUTIONS</span><div style="font-size:12px;color:#a8c4df">PRIVATE TICKET DESK</div></div><nav><a href="/">Dashboard</a><a href="/tickets">All Tickets</a><a href="/new">+ New Ticket</a><a href="/export">Export CSV</a></nav></header><main>'+body+'</main><footer>MTS Ticket Desk · Data stored in '+esc(str(DB))+' · Back up this database regularly.</footer></body></html>'

def ticket_table(rows):
    if not rows:return '<p class="muted">No tickets found.</p>'
    out='<div class="tablewrap"><table><thead><tr><th>Ticket</th><th>Customer</th><th>Device</th><th>Status</th><th>Balance</th><th>Updated</th></tr></thead><tbody>'
    for r in rows:
        out+=f'<tr><td><a href="/ticket/{r["id"]}">MTS-{r["id"]:05d}</a></td><td>{esc(r["customer"])}</td><td>{esc(r["device"])}</td><td><span class="chip">{esc(r["status"])}</span></td><td>{money(max(0,r["estimate"]-r["paid"]))}</td><td>{esc(r["updated_at"][:10])}</td></tr>'
    return out+'</tbody></table></div>'

def field(name,label,value='',wide=False,textarea=False,kind='text',required=False):
    attr=' required' if required else ''
    control=(f'<textarea name="{name}" id="{name}"{attr}>{esc(value)}</textarea>' if textarea else f'<input type="{kind}" name="{name}" id="{name}" value="{esc(value)}"{attr}'+(' step="0.01" min="0"' if kind=='number' else '')+'>')
    return f'<div class="field{" wide" if wide else ""}"><label for="{name}">{esc(label)}</label>{control}</div>'

def form(row=None):
    r=dict(row) if row else {}
    def g(k):return r.get(k,'')
    status=g('status') or 'New'
    choices=''.join('<option value="'+esc(x)+'"'+(' selected' if x==status else '')+'>'+esc(x)+'</option>' for x in STATUSES)
    body='<h1>'+('Edit '+f'MTS-{r["id"]:05d}' if row else 'Create New Ticket')+'</h1><div class="panel"><form method="post" action="'+('/save/'+str(r['id']) if row else '/create')+'"><div class="formgrid">'
    for n,l,req in [('customer','Customer Full Name',True),('phone','Phone Number',False),('email','Email Address',False),('device','Device / Model',True),('serial','Serial Number',False)]:body+=field(n,l,g(n),required=req)
    body+=field('issue','Reported Problem',g('issue'),True,True,required=True)
    body+=field('diagnosis','Diagnostics / Findings',g('diagnosis'),True,True)
    body+=field('work_done','Work Performed',g('work_done'),True,True)
    body+=field('notes','Internal Notes',g('notes'),True,True)
    body+=f'<div class="field"><label for="status">Status</label><select name="status" id="status">{choices}</select></div>'
    body+=field('estimate','Total Charge / Estimate ($)',g('estimate') if row else '0',kind='number')
    body+=field('paid','Amount Paid ($)',g('paid') if row else '0',kind='number')
    body+='</div><div class="actions"><button type="submit">Save Ticket</button><a class="btn" href="/tickets">Cancel</a></div></form></div>'
    return body

class Handler(BaseHTTPRequestHandler):
    def send(self,status,body,ctype='text/html; charset=utf-8',extra=None):
        b=body.encode('utf-8') if isinstance(body,str) else body
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('X-Frame-Options','DENY')
        if extra:
            for k,v in extra.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(b)
    def authenticated(self):
        val=self.headers.get('Authorization','')
        if not val.startswith('Basic '):return False
        try:
            raw=base64.b64decode(val[6:],validate=True).decode('utf-8');user,passwd=raw.split(':',1)
            return hmac.compare_digest(user,'mts') and hmac.compare_digest(passwd,PASSWORD)
        except (ValueError,UnicodeError):return False
    def check(self):
        if self.authenticated():return True
        self.send(401,'Authentication required','text/plain; charset=utf-8',{'WWW-Authenticate':'Basic realm="MTS Ticket Desk"'});return False
    def do_GET(self):
        if not self.check():return
        path=urlparse(self.path).path
        with connect() as c:
            if path=='/':
                data=c.execute('SELECT status,COUNT(*) n FROM tickets GROUP BY status').fetchall();d={r['status']:r['n'] for r in data}
                total=sum(d.values());active=sum(n for k,n in d.items() if k not in ('Completed','Cancelled'))
                due=c.execute('SELECT COALESCE(SUM(MAX(estimate-paid,0)),0) due FROM tickets WHERE status != "Cancelled"').fetchone()['due']
                latest=c.execute('SELECT * FROM tickets ORDER BY updated_at DESC,id DESC LIMIT 10').fetchall()
                stats=[('Total Tickets',total),('Active Repairs',active),('Ready for Pickup',d.get('Ready for Pickup',0)),('Completed',d.get('Completed',0)),('Outstanding',money(due))]
                cards=''.join(f'<div class="stat"><small>{esc(k)}</small><strong>{esc(v)}</strong></div>' for k,v in stats)
                self.send(200,shell('Dashboard','<h1>MTS Service Dashboard</h1><div class="stats">'+cards+'</div><div class="toolbar"><h2>Recent Tickets</h2><a class="btn" href="/new">+ New Ticket</a></div><div class="panel">'+ticket_table(latest)+'</div>'));return
            if path=='/tickets':
                qs=parse_qs(urlparse(self.path).query);search=qs.get('q',[''])[0].strip();status=qs.get('status',[''])[0]
                sql='SELECT * FROM tickets WHERE 1=1';args=[]
                if search:sql+=' AND (customer LIKE ? OR phone LIKE ? OR email LIKE ? OR device LIKE ? OR issue LIKE ? OR CAST(id AS TEXT) LIKE ?)';args+=['%'+search+'%']*6
                if status in STATUSES:sql+=' AND status=?';args.append(status)
                rows=c.execute(sql+' ORDER BY updated_at DESC,id DESC',args).fetchall()
                options='<option value="">All statuses</option>'+''.join(f'<option value="{esc(s)}"'+(' selected' if status==s else '')+'>'+esc(s)+'</option>' for s in STATUSES)
                toolbar='<form method="get" class="toolbar"><input style="max-width:430px" name="q" placeholder="Search tickets, customer, device..." value="'+esc(search)+'"><select style="max-width:230px" name="status">'+options+'</select><button>Search / Filter</button></form>'
                self.send(200,shell('Tickets','<h1>Tickets</h1>'+toolbar+'<div class="panel">'+ticket_table(rows)+'</div>'));return
            if path=='/new':self.send(200,shell('New Ticket',form()));return
            if path.startswith('/ticket/'):
                try:idx=int(path.split('/')[-1])
                except ValueError:self.send(404,'Not found','text/plain');return
                row=c.execute('SELECT * FROM tickets WHERE id=?',(idx,)).fetchone()
                if not row:self.send(404,'Ticket not found','text/plain');return
                r=dict(row)
                def line(k,label):return f'<p><strong>{label}:</strong> {esc(r[k]) or "—"}</p>'
                content=f'<div class="toolbar"><h1>MTS-{idx:05d}</h1><a class="btn" href="/edit/{idx}">Edit Ticket</a></div><div class="stats"><div class="stat"><small>Status</small><strong style="font-size:19px">{esc(r["status"])}</strong></div><div class="stat"><small>Total Charge</small><strong>{money(r["estimate"])}</strong></div><div class="stat"><small>Paid</small><strong>{money(r["paid"])}</strong></div><div class="stat"><small>Balance</small><strong>{money(max(0,r["estimate"]-r["paid"]))}</strong></div></div>'
                content+='<div class="panel">'+''.join(line(k,l) for k,l in [('customer','Customer'),('phone','Phone'),('email','Email'),('device','Device'),('serial','Serial'),('issue','Reported Problem'),('diagnosis','Diagnostics'),('work_done','Work Performed'),('notes','Internal Notes'),('created_at','Created'),('updated_at','Updated')])+'</div>'
                self.send(200,shell('Ticket',content));return
            if path.startswith('/edit/'):
                try:idx=int(path.split('/')[-1])
                except ValueError:self.send(404,'Not found','text/plain');return
                row=c.execute('SELECT * FROM tickets WHERE id=?',(idx,)).fetchone()
                self.send(200,shell('Edit Ticket',form(row)) if row else 'Ticket not found');return
            if path=='/export':
                output=io.StringIO();writer=csv.writer(output);cols=['id','created_at','updated_at','customer','phone','email','device','serial','issue','diagnosis','work_done','notes','status','estimate','paid'];writer.writerow(cols)
                for r in c.execute('SELECT * FROM tickets ORDER BY id'):writer.writerow([r[col] for col in cols])
                self.send(200,output.getvalue(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="mts_tickets_export.csv"'});return
        self.send(404,'Page not found','text/plain')
    def do_POST(self):
        if not self.check():return
        path=urlparse(self.path).path
        creating=path=='/create'
        if not creating and not path.startswith('/save/'):
            self.send(404,'Not found','text/plain');return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>200000 or size<=0:raise ValueError('Invalid request size')
            params=parse_qs(self.rfile.read(size).decode('utf-8'),keep_blank_values=True)
            get=lambda k: params.get(k,[''])[0].strip()
            customer=get('customer');device=get('device');issue=get('issue');status=get('status')
            if not customer or not device or not issue or status not in STATUSES:raise ValueError('Customer, device, problem, and valid status are required')
            estimate=float(get('estimate') or 0);paid=float(get('paid') or 0)
            if not (0<=estimate<=1e9 and 0<=paid<=1e9):raise ValueError('Amounts must be between 0 and 1 billion')
            values=[customer,get('phone'),get('email'),device,get('serial'),issue,get('diagnosis'),get('work_done'),get('notes'),status,estimate,paid]
            now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with LOCK,connect() as c:
                if creating:
                    cur=c.execute('INSERT INTO tickets(created_at,updated_at,customer,phone,email,device,serial,issue,diagnosis,work_done,notes,status,estimate,paid) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[now,now]+values);idx=cur.lastrowid
                else:
                    idx=int(path.split('/')[-1]);c.execute('UPDATE tickets SET updated_at=?,customer=?,phone=?,email=?,device=?,serial=?,issue=?,diagnosis=?,work_done=?,notes=?,status=?,estimate=?,paid=? WHERE id=?',[now]+values+[idx])
            self.send_response(303);self.send_header('Location',f'/ticket/{idx}');self.send_header('Content-Length','0');self.end_headers()
        except (ValueError,UnicodeError) as ex:self.send(400,shell('Error','<h1>Could not save ticket</h1><p>'+esc(ex)+'</p><a href="/tickets">Back to Tickets</a>'))
    def log_message(self,format,*args): print('%s - %s'%(self.address_string(),format%args))

if __name__=='__main__':
    if not PASSWORD:
        from getpass import getpass
        PASSWORD = getpass('Ticket Desk password (this session): ')
    if not PASSWORD:
        print('Password cannot be empty.');raise SystemExit(1)
    if HOST not in ('127.0.0.1','localhost','::1'):
        print('WARNING: Network access uses unencrypted HTTP. Only use across a trusted LAN or Tailscale; do NOT port-forward this service.')
    init()
    print(f'MTS Ticket Desk: http://{HOST}:{PORT}/  (username: mts)')
    print('Press Ctrl+C to stop.');ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
