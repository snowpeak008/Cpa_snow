"""Read-only CPA v8.0.31 Claude usage valuation; Python standard library only."""
import argparse
import collections
import datetime as dt
import html
import json
import pathlib
import re
import sqlite3
from zoneinfo import ZoneInfo

SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'
PRICE_DATE = '2026-10-17'
# USD per million tokens: ordinary input, output, cache read.
PRICES = {
    'claude-haiku-4-5-20251001': (1, 5, .1),
    'claude-haiku-4-5': (1, 5, .1),
    'claude-sonnet-4-5-20250929': (3, 15, .3),
    'claude-sonnet-4-5': (3, 15, .3),
    'claude-sonnet-4-6': (3, 15, .3),
    'claude-opus-4-5-20251101': (5, 25, .5),
    'claude-opus-4-5': (5, 25, .5),
    'claude-opus-4-6': (5, 25, .5),
    'claude-opus-4-7': (5, 25, .5),
    'claude-opus-4-8': (5, 25, .5),
    'claude-opus-5': (5, 25, .5),
    'claude-sonnet-5': (2, 10, .2),
    'claude-fable-5': (10, 50, 1),
    'claude-fable-5-1': (10, 50, .25),
    'claude-opus-5-5': (4, 20, .2),
    'claude-sonnet-5-5': (2, 10, .1),
    'claude-haiku-5-5': (.1, .5, .01),
    'claude-3-5-haiku-20241022': (.8, 4, .08),
    'claude-opus-4-1-20250805': (15, 75, 1.5),
    'claude-opus-4-20250514': (15, 75, 1.5),
    'claude-sonnet-4-20250514': (3, 15, .3),
}

def value_event(d):
    t = d.get('tokens') or {}
    counts = [int(t.get(k, 0) or 0) for k in
              ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens')]
    if any(n < 0 for n in counts):
        raise ValueError('Negative token count')
    i, o, r, w = counts
    model = d.get('model', '')
    price = PRICES.get(model)
    # Never silently guess prices or reinterpret another provider's token schema.
    uncertain = d.get('provider') != 'claude' or price is None
    uncertain |= bool(int(t.get('cached_tokens', 0) or 0) and not (r or w))
    uncertain |= model in ('claude-sonnet-4-5', 'claude-sonnet-4-5-20250929',
                          'claude-sonnet-4-20250514') and i+r+w > 200000
    if uncertain:
        return counts, None
    if model == 'claude-haiku-5-5' and i+r+w > 100000:
        price = (.5, 2.5, .05)
    ip, op, rp = price
    # CPA's Claude input excludes cache; output already includes reasoning.
    base = (i*ip + o*op + r*rp) / 1e6
    # Events do not retain cache-write TTL: report 5m..1h interval.
    return counts, (base+w*ip*1.25/1e6, base+w*ip*2/1e6)

def aggregate(db, now=None):
    zone = ZoneInfo('Asia/Shanghai')
    now = now or dt.datetime.now(zone)
    buckets = {k: {} for k in ('today', 'month', 'all')}
    malformed = 0
    first = None
    with sqlite3.connect(pathlib.Path(db).resolve().as_uri()+'?mode=ro', uri=True) as c:
        for (payload,) in c.execute('SELECT payload FROM usage_events ORDER BY id'):
            try:
                d = json.loads(payload)
                iso = re.sub(r'(\.\d{6})\d+', r'\1', d['timestamp']).replace('Z', '+00:00')
                stamp = dt.datetime.fromisoformat(iso)
                if stamp.tzinfo is None:
                    raise ValueError('Missing timezone')
                stamp = stamp.astimezone(zone)
                counts, money = value_event(d)
                account = str(d.get('source') or '未知账号')
                # Never export arbitrary source values that might be API keys.
                if '@' not in account or account.startswith('sk-'):
                    account = '未知账号'
                first = min(first, stamp) if first else stamp
                periods = ['all']
                if stamp.date() == now.date(): periods.append('today')
                if (stamp.year, stamp.month) == (now.year, now.month): periods.append('month')
                for period in periods:
                    a = buckets[period].setdefault(account, dict(requests=0,failed=0,input=0,output=0,read=0,write=0,low=0.,high=0.,unknown=0,models=[]))
                    a['requests'] += 1
                    a['failed'] += bool(d.get('failed'))
                    for key, n in zip(('input','output','read','write'), counts): a[key] += n
                    if money is None: a['unknown'] += 1
                    else:
                        a['low'] += money[0]
                        a['high'] += money[1]
                    if d.get('model') not in a['models']: a['models'].append(d.get('model'))
            except (ValueError, TypeError, KeyError, OverflowError):
                malformed += 1
    return dict(generated=now.isoformat(timespec='seconds'), first=first.isoformat() if first else None,
                periods=buckets, malformed=malformed, price_date=PRICE_DATE)

def render(data):
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CPA 账号美元估值</title><style>body{background:#101827;color:#e5edf8;font:16px system-ui;margin:32px auto;max-width:1200px;padding:0 20px}h1{margin-bottom:8px}p{color:#aebed2;line-height:1.7}.cards{display:flex;gap:16px;flex-wrap:wrap}.card{background:#1a2940;padding:22px;border-radius:14px;min-width:190px}.card strong{display:block;font-size:28px;color:#6ee7c0}button{background:#253957;color:white;border:1px solid #587092;padding:10px 22px;border-radius:8px;margin:18px 8px 18px 0;cursor:pointer}button.active{background:#087f6b}table{width:100%;border-collapse:collapse;background:#162239}td,th{text-align:left;padding:14px;border-bottom:1px solid #2a3c56;font-size:14px}th{color:#a7c1e0}.scroll{overflow:auto}a{color:#7dd3fc}.note{padding:16px;background:#242c35;border-left:4px solid #edbc59}small{color:#adc0d5}</style>
<h1>CPA 账号美元估值</h1><p>按 API 标准单价折算的 token 价值 · 不是 Pro 实际账单或剩余额度</p><p id="meta"></p>
<div><button data-p="today">今天</button><button data-p="month">本月</button><button data-p="all">累计</button></div><div class="cards" id="cards"></div>
<h2>按账号统计</h2><div class="scroll"><table><thead><tr><th>账号 / 模型</th><th>请求 / 失败</th><th>普通输入</th><th>输出</th><th>缓存读取</th><th>缓存写入</th><th>美元估值</th><th>未计价请求</th></tr></thead><tbody id="rows"></tbody></table></div>
<p class="note">只涵盖此 CPA 插件已记录的请求；历史未记录用量无法补回。未知模型不按零美元计价，金额仅为已计价部分。缓存写入缺少时长信息时显示 5 分钟至 1 小时价格区间。失败但带 token 的请求也纳入估值。按标准同步 API 价格估算，不含快速模式、批处理折扣、地域或工具费用。价格快照更新后会重新估算全部记录。</p>
<p>日/月边界：北京时间 Asia/Shanghai。该页面是生成时的快照，更新数据请重新双击 Open-CPA-Cost.cmd；浏览器刷新不会重新查询服务器。</p>
<p>价格核对日期：2026-10-17 · <a href="https://platform.claude.com/docs/en/about-claude/pricing">Anthropic 官方价格</a></p>
<script>const D='''+payload+''';const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const num=n=>Number(n).toLocaleString('zh-CN');const money=(a,b)=>Math.abs(a-b)<1e-10?'$'+a.toFixed(6):'$'+a.toFixed(6)+'–$'+b.toFixed(6);document.getElementById('meta').textContent='生成时间：'+D.generated+'　首条记录：'+(D.first||'暂无')+'　异常记录：'+D.malformed;
function show(p){document.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.p===p));const rows=Object.entries(D.periods[p]);let lo=0,hi=0,req=0,unknown=0;document.getElementById('rows').innerHTML=rows.map(([name,a])=>{lo+=a.low;hi+=a.high;req+=a.requests;unknown+=a.unknown;return '<tr><td>'+esc(name)+'<br><small>'+a.models.map(esc).join('<br>')+'</small></td><td>'+a.requests+' / '+a.failed+'</td>'+['input','output','read','write'].map(k=>'<td>'+num(a[k])+'</td>').join('')+'<td>'+money(a.low,a.high)+(a.unknown?'（部分）':'')+'</td><td>'+a.unknown+'</td></tr>'}).join('')||'<tr><td colspan="8">这个时间段暂无记录</td></tr>';document.getElementById('cards').innerHTML='<div class="card">'+(unknown?'已计价部分':'API 等值金额')+'<strong>'+money(lo,hi)+'</strong></div><div class="card">请求数<strong>'+req+'</strong></div><div class="card">未计价请求<strong>'+unknown+'</strong></div>'}document.querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.p));show('today');</script></html>'''

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='/opt/cpa/auths/usage-report.sqlite')
    p.add_argument('--json', action='store_true')
    args = p.parse_args()
    data = aggregate(args.db)
    print(json.dumps(data, ensure_ascii=False) if args.json else render(data))
