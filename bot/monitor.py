"""Tiny built-in web monitor so a cloud deploy (Railway/Render/VPS) gives you a
URL to watch the bot from anywhere — live dashboard + recent logs.

It runs in a daemon thread next to the trading loop and binds to $PORT (set by
the host). Routes:
  /           -> dashboard page (reads /bot.json and /logs)
  /bot.json   -> the current status snapshot
  /logs       -> recent log lines (plain text)
  /health     -> "ok" (for uptime checks)

Only non-sensitive status is exposed — never API keys.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT_JSON = HERE.parent / "docs" / "crypto" / "data" / "bot.json"

# ring buffer of recent log lines, filled by trading_bot.log()
LOGS = deque(maxlen=400)

# Chat box wiring (set by trading_bot via set_brain).
BRAIN = None
CONTEXT_FN = None
CHAT_HISTORY = []


def add_log(line):
    LOGS.append(line)


def set_brain(brain, context_fn):
    global BRAIN, CONTEXT_FN
    BRAIN = brain
    CONTEXT_FN = context_fn


PAGE = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🤖 بوت التداول</title><style>
:root{--bg:#0b0f1a;--card:#151c2c;--bd:#243049;--tx:#e8edf6;--mut:#93a0bd;--up:#16c784;--dn:#ea3943;--ac:#f7931a}
*{box-sizing:border-box;margin:0}body{background:var(--bg);color:var(--tx);font-family:-apple-system,Segoe UI,Tahoma,Arial,sans-serif;padding:14px;max-width:960px;margin:auto;line-height:1.6}
h1{font-size:1.3rem}h2{font-size:1rem;color:var(--ac);margin:20px 0 8px}
.pill{font-size:.78rem;padding:3px 10px;border-radius:999px;border:1px solid var(--bd)}
.live{background:var(--dn);color:#fff;border-color:var(--dn)}.dryrun{background:var(--up);color:#fff}.testnet{background:#5b8def;color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.st{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px}.st .l{font-size:.78rem;color:var(--mut)}.st .v{font-size:1.25rem;font-weight:700;margin-top:4px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--bd);border-radius:12px;overflow:hidden}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--bd);font-size:.86rem;white-space:nowrap}th{background:#1b2436;color:var(--mut)}
.up{color:var(--up)}.dn{color:var(--dn)}.mut{color:var(--mut)}.scroll{overflow-x:auto}
pre{background:#0a0e17;border:1px solid var(--bd);border-radius:12px;padding:12px;font-size:.78rem;max-height:320px;overflow:auto;direction:ltr;text-align:left;white-space:pre-wrap}
</style></head><body>
<h1>🤖 بوت التداول <span id="mode" class="pill">…</span></h1>
<div id="warn" style="color:var(--ac);margin:8px 0"></div>
<div class="grid">
<div class="st"><div class="l">قيمة المحفظة (USDT)</div><div class="v" id="eq">—</div></div>
<div class="st"><div class="l">USDT متاح</div><div class="v" id="freeusdt">—</div></div>
<div class="st"><div class="l">الربح/الخسارة المحقّقة</div><div class="v" id="pnl">—</div></div>
<div class="st"><div class="l">صفقات مفتوحة</div><div class="v" id="op">—</div></div>
<div class="st"><div class="l">الخوف/الطمع</div><div class="v" id="fng">—</div></div>
</div>
<h2>الصفقات المفتوحة</h2><div class="scroll"><table id="pos"><thead><tr><th>العملة</th><th>دخول</th><th>الآن</th><th>ربح%</th></tr></thead><tbody></tbody></table></div>
<h2>الاستراتيجية المتعلّمة</h2><div class="scroll"><table id="str"><thead><tr><th>العملة</th><th>حالة</th><th>سريع/بطيء</th><th>عائد الباك-تيست</th><th>ML</th></tr></thead><tbody></tbody></table></div>
<h2>آخر الصفقات</h2><div class="scroll"><table id="trd"><thead><tr><th>وقت</th><th>عملة</th><th>نوع</th><th>سعر</th><th>سبب</th></tr></thead><tbody></tbody></table></div>
<h2>🧠 قرارات العقل</h2><div class="scroll"><table id="brn"><thead><tr><th>عملة</th><th>قرار</th><th>ثقة</th><th>السبب</th></tr></thead><tbody></tbody></table></div>
<h2>💬 تحدّث مع العقل</h2>
<div id="chatbox" style="background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:10px;max-height:260px;overflow:auto;font-size:.9rem"></div>
<div style="display:flex;gap:8px;margin-top:8px">
  <input id="chatin" placeholder="اسأل العقل… (مثلاً: ليش اشتريت SOL؟)" style="flex:1;padding:10px;border-radius:10px;border:1px solid var(--bd);background:var(--card);color:var(--tx)">
  <button id="chatsend" onclick="sendChat()" style="padding:10px 16px;border:0;border-radius:10px;background:var(--ac);color:#000;font-weight:700;cursor:pointer">إرسال</button>
</div>
<h2>السجلّ المباشر</h2><pre id="logs">…</pre>
<script>
const $=i=>document.getElementById(i),f=(n,d=2)=>n==null||isNaN(n)?'—':(+n).toLocaleString('en',{maximumFractionDigits:d});
const sg=(v,d=2)=>(v>0?'+':'')+f(v,d),cl=v=>v>0?'up':v<0?'dn':'';
function ago(t){if(!t)return'—';let s=(Date.now()-new Date(t))/1e3;return s<60?'الآن':s<3600?(s/60|0)+'د':s<86400?(s/3600|0)+'س':(s/86400|0)+'ي'}
async function tick(){
 try{const d=await(await fetch('/bot.json?t='+Date.now())).json();
  const m=$('mode');m.textContent=({dryrun:'محاكاة',testnet:'تجريبي',live:'حقيقي'}[d.mode]||d.mode||'—');m.className='pill '+(d.mode||'');
  $('warn').textContent=d.mode==='live'?'⚠️ يتداول بأموال حقيقية':'';
  const ac=d.account||{};
  $('eq').textContent=f(ac.total_usdt!=null?ac.total_usdt:d.equity_quote);
  $('freeusdt').textContent=ac.free_usdt!=null?f(ac.free_usdt):'—';
  const p=$('pnl');p.textContent=sg(d.realized_pnl_quote);p.className='v '+cl(d.realized_pnl_quote);
  $('op').textContent=(d.positions||[]).length;const R=d.regime||{};
  $('fng').textContent=R.fear_greed==null?'—':R.fear_greed+(R.fear_greed_label?(' '+R.fear_greed_label):'');
  let b=$('pos').querySelector('tbody');b.innerHTML=(d.positions||[]).map(x=>`<tr><td>${x.symbol}</td><td>${f(x.entry_price,4)}</td><td>${f(x.price,4)}</td><td class=${cl(x.pnl_pct)}>${sg(x.pnl_pct)}%</td></tr>`).join('')||'<tr><td colspan=4 class=mut>لا صفقات</td></tr>';
  b=$('str').querySelector('tbody');b.innerHTML=(d.strategy||[]).map(s=>{let pp=s.params||{},bt=s.backtest||{};return `<tr><td>${s.symbol}</td><td class=${s.active?'up':'mut'}>${s.active?'يتداول':'مراقبة'}</td><td>${pp.fast??'—'}/${pp.slow??'—'}</td><td class=${cl(bt.return_pct)}>${bt.return_pct==null?'—':sg(bt.return_pct)+'%'}</td><td>${s.ml_accuracy==null?'—':(s.ml_accuracy*100|0)+'%'}</td></tr>`}).join('');
  b=$('trd').querySelector('tbody');b.innerHTML=(d.recent_trades||[]).slice().reverse().map(t=>`<tr><td class=mut>${ago(t.time)}</td><td>${t.symbol}</td><td class=${t.side==='BUY'?'up':'dn'}>${t.side==='BUY'?'شراء':'بيع'}</td><td>${f(t.price,4)}</td><td class=mut>${t.reason||''}</td></tr>`).join('')||'<tr><td colspan=5 class=mut>لا صفقات بعد</td></tr>';
 }catch(e){}
  const bb=$('brn').querySelector('tbody');const br=d.brain||{};const keys=Object.keys(br);
  bb.innerHTML=keys.filter(k=>br[k]).map(k=>{const x=br[k];const a=x.action;
    const cls=a==='buy'?'up':a==='sell'?'dn':'mut';const lbl=a==='buy'?'شراء':a==='sell'?'بيع':'انتظار';
    return `<tr><td>${k}</td><td class=${cls}>${lbl}</td><td>${x.confidence==null?'—':Math.round(x.confidence*100)+'%'}</td><td class=mut>${(x.reason||'').slice(0,90)}</td></tr>`}).join('')||'<tr><td colspan=4 class=mut>لا قرارات بعد</td></tr>';
 }catch(e){}
 try{$('logs').textContent=await(await fetch('/logs?t='+Date.now())).text()}catch(e){}
}
function addMsg(who,text){const b=$('chatbox');const me=who==='you';
 b.insertAdjacentHTML('beforeend',`<div style="margin:6px 0"><b style="color:${me?'#5b8def':'#f7931a'}">${me?'أنت':'العقل'}:</b> ${text.replace(/</g,'&lt;')}</div>`);b.scrollTop=b.scrollHeight;}
async function sendChat(){const i=$('chatin');const m=i.value.trim();if(!m)return;i.value='';addMsg('you',m);
 $('chatsend').disabled=true;addMsg('bot','…');
 try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});
  const d=await r.json();$('chatbox').lastChild.remove();addMsg('bot',d.reply||'…');}
 catch(e){$('chatbox').lastChild.remove();addMsg('bot','تعذّر الاتصال');}
 $('chatsend').disabled=false;}
$('chatin').addEventListener('keydown',e=>{if(e.key==='Enter')sendChat();});
tick();setInterval(tick,5000);
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/bot.json":
            try:
                self._send(200, BOT_JSON.read_text(encoding="utf-8"),
                           "application/json; charset=utf-8")
            except Exception:
                self._send(200, "{}", "application/json")
        elif path == "/logs":
            self._send(200, "\n".join(LOGS), "text/plain; charset=utf-8")
        elif path == "/health":
            self._send(200, "ok", "text/plain")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/chat":
            self._send(404, "not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or "{}")
            msg = (body.get("message") or "").strip()
        except Exception:
            msg = ""
        if not msg:
            self._send(400, json.dumps({"reply": "رسالة فارغة"}),
                       "application/json")
            return
        if BRAIN is None or not getattr(BRAIN, "available", False):
            reply = "العقل غير مفعّل. أضِف ANTHROPIC_API_KEY و ENABLE_BRAIN=true."
        else:
            ctx = CONTEXT_FN() if CONTEXT_FN else {}
            reply = BRAIN.chat(CHAT_HISTORY, msg, ctx)
            CHAT_HISTORY.append({"role": "user", "content": msg})
            CHAT_HISTORY.append({"role": "assistant", "content": reply})
            del CHAT_HISTORY[:-16]
        self._send(200, json.dumps({"reply": reply}, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def log_message(self, *args):  # silence default request logging
        pass


def start(port):
    """Start the monitor server in a background daemon thread."""
    srv = ThreadingHTTPServer(("0.0.0.0", int(port)), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
