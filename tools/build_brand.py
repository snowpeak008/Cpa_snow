"""Pinned, auditable visual customization of the exact deployed standalone HTML."""
import base64
import hashlib
import json
import re
from pathlib import Path
from simplify_panel import simplify_panel

ROOT=Path(__file__).resolve().parents[1]
original=(ROOT/'web/upstream-management.html').read_bytes()
expected='351c286e3a6bf986cb3d4a7763020c30fc8b8c8a97ee7455441b5badc647b4c2'
assert hashlib.sha256(original).hexdigest()==expected, 'Source changed; review branding patches first'
s=original.decode('utf-8')
replacements={
 'CLI Proxy API Management Center':'Snow Console',
 'CLI Proxy API':'Snow Console',
 'CPA（Snow Console）':'服务端',
 'CLIProxyAPI 升级':'服务端升级',
 'CLIProxyAPI源':'服务端源',
 'abbr:`CPAMC`':'abbr:`Snow Console`',
 'alt:`CPAMC`':'alt:`Snow Console`',
 'alt:`CPAMC logo`':'alt:`Snow Console logo`',
 'brandWord,children:`CLI`':'brandWord,children:`Snow`',
 'brandWord,children:`PROXY`':'brandWord,children:`Console`',
 'brandWord,children:`API`':'brandWord,children:`雪峰控制台`',
 'theme:`auto`,resolvedTheme:`light`,setTheme:':'theme:`dark`,resolvedTheme:`dark`,setTheme:',
 '连接 Snow Console v8 或更高版本':'登录雪峰控制台，管理你的服务与连接',
 'Snow Console 管理控制台':'雪峰控制台',
 'Snow Console 版本':'服务端版本',
 'Snow Console 核心程序源代码':'底层服务源代码',
 'AI 提供商':'模型服务',
 'OAuth 登录':'连接账号',
 '静候流量':'运行总览',
 '管理供应商':'管理连接',
 '版本详情与管理中心信息。':'连接状态与控制台概况。',
 '请求头伪装、签名缓存、插件源等不常修改的设置':'请求头与提供商行为等进阶设置',
 '用于面板更新、插件下载等服务端 GitHub 请求。优先于 GITHUB_TOKEN；留空时使用环境变量凭据，未设置凭据则匿名请求。插件商店匹配的认证规则优先。':'用于服务端 GitHub 资源请求。优先于 GITHUB_TOKEN；留空时使用环境变量凭据，未设置凭据则匿名请求。',
}
changes=[]
for before,after in replacements.items():
    count=s.count(before)
    if count:s=s.replace(before,after);changes.append({'from':before,'to':after,'count':count})
def brand_message(match):
    key,value=match.group(1),match.group(2)
    # Localization sentences only; leave URLs, protocol keys and API identifiers alone.
    if '${' in value or '://' in value or not re.search(r'\s|[\u4e00-\u9fff]',value):return match.group(0)
    updated=re.sub(r'\bCPA\b','Snow Console',value).replace('CLIProxyAPI','Snow Console')
    updated=updated.replace('Snow Console (Snow Console)','Snow Console').replace('Snow Console(Snow Console)','Snow Console')
    if updated!=value:changes.append({'from':value,'to':updated,'count':1})
    return key+':`'+updated+'`'
s=re.sub(r'([a-z_]+):`([^`\n]{1,600})`',brand_message,s)
s, simplification = simplify_panel(s, ROOT)
logo='data:image/svg+xml;base64,'+base64.b64encode((ROOT/'web/snow-logo.svg').read_bytes()).decode()
css=(ROOT/'web/snow.css').read_text(encoding='utf-8')
css+='\n'+', '.join(['[class*="LoginPage-module__logo"]','[class*="LoginPage-module__splashLogo"]','.sidebar-brand-logo','[class*="SystemPage-module__aboutLogo"]'])+' { content:url("'+logo+'"); }\n'
favicon='<link rel="icon" type="image/svg+xml" href="'+logo+'">'
s=re.sub(r'<link\b[^>]*\brel=["\'](?:shortcut )?icon["\'][^>]*>','',s)
route_guard='''<script id="snow-section-guard">
(()=>{const allowed=new Set(['/','/login','/dashboard','/auth-files','/auth-files/oauth-excluded','/auth-files/oauth-model-alias','/quota','/config','/system']);
function guard(){const path=(location.hash.slice(1).split('?')[0]||'/').replace(/\\/$/,'')||'/';if(!allowed.has(path))location.replace(location.pathname+location.search+'#/')}
window.addEventListener('hashchange',guard);guard();})();
</script>'''
s=s.replace('</head>',favicon+'\n<style id="snow-console-theme">'+css+'</style>\n'+route_guard+'\n</head>')
for raw in ['"/v8/management"','`/v8/management`','`/credentials`','G.get(`/config`)','G.get(`/plugins`)','x-cpa-version','x-cpa-support-plugin']:
    assert s.count(raw)==original.decode().count(raw), 'API marker changed: '+raw
out=ROOT/'web/management.html';out.write_text(s,encoding='utf-8',newline='\n')
report={'source_sha256':expected,'output_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
        'changes':changes,'simplification':simplification,'api_marker_counts_unchanged':True,'production_deployed':False,
        'boundary':'Presentation changes only. Core protocol, auth, quota, account routing and provider logos unchanged.'}
(ROOT/'evidence/branding-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'ok':True,'literal_replacement_count':sum(x['count'] for x in changes),'output_sha256':report['output_sha256']}))
