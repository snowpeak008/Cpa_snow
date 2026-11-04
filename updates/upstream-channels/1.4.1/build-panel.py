from pathlib import Path
import json,hashlib
root=Path(__file__).parent
text=(root/'baseline-management.html').read_text(encoding='utf-8')
marker='function useSnowKeyAccounts('
injection=(root/'channels-core.js').read_text(encoding='utf-8')+'\n'+(root/'channels-page.js').read_text(encoding='utf-8')+'\n'
assert text.count(marker)==1
text=text.replace(marker,injection+marker)
route='{path:`/auth-files`,element:(0,H.jsx)(Rj,{})}'
assert text.count(route)==1
text=text.replace(route,'{path:`/upstream-channels`,element:(0,H.jsx)(SnowUpstreamPage,{})},'+route)
nav='{path:`/ai-providers`,labelKey:`nav.ai_providers`,metaKey:`nav_meta.ai_providers`,icon:K9.aiProviders}'
assert text.count(nav)==1
text=text.replace(nav,nav+',{path:`/upstream-channels`,labelKey:`上游渠道`,icon:K9.aiProviders}')
start=text.index(marker);end=text.index('function zae',start);old=text[start:end]
new=old.replace(".filter(a=>a.provider==='claude'||a.type==='claude')",".filter(a=>typeof a.id==='string'&&a.id)")
assert new!=old and old.count(".filter(a=>a.provider==='claude'||a.type==='claude')")==2
new=new.replace('专属 Claude 账号','专属账号与上游渠道').replace('全部 Claude 账号','全部账号与上游渠道')
new=new.replace('a.email||a.name||a.id',"(a.provider||a.type||'账号')+' · '+(a.email||a.name||a.id)")
new=new.replace("Promise.all([G.get('/credentials'),Ky.getConfig('account-concurrency'),", "Promise.all([G.get('/credentials'),Ky.getConfig('account-concurrency'),")
needle="G.get(apiBase.replace(/\\/$/,'')+'/v0/management/plugins/account-concurrency/status')]).then(([auths,config,status])=>"
assert needle in new
new=new.replace(needle,"G.get(apiBase.replace(/\\/$/,'')+'/v0/management/plugins/account-concurrency/status'),G.get('/config')]).then(([auths,config,status,rawChannels])=>")
needle="const accounts=(auths.files||[]).filter(a=>typeof a.id==='string'&&a.id);"
assert needle in new
sha="value=>rae(mae((new TextEncoder).encode(value)))"
new=new.replace(needle,"const accounts=[...(auths.files||[]),...SnowUpstreams.credentials(rawChannels,"+sha+")].filter((a,i,all)=>typeof a.id==='string'&&a.id&&all.findIndex(b=>b.id===a.id)===i);")
needle="const accounts=await G.get('/credentials');checkConnection();const known=new Set((accounts.files||[]).filter(a=>typeof a.id==='string'&&a.id).map(a=>a.id));"
assert needle in new
new=new.replace(needle,"const [accounts,rawChannels]=await Promise.all([G.get('/credentials'),G.get('/config')]);checkConnection();const known=new Set([...(accounts.files||[]),...SnowUpstreams.credentials(rawChannels,"+sha+")].filter(a=>typeof a.id==='string'&&a.id).map(a=>a.id));")
text=text[:start]+new+text[end:]
(root/'management.html').write_text(text,encoding='utf-8')
print(json.dumps({'sha256':hashlib.sha256((root/'management.html').read_bytes()).hexdigest(),'route':'#/upstream-channels','existing_key_editor_expanded':True}))
