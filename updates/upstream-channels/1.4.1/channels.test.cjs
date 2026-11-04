const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const c=require('./channels-core.js');
const draft=kind=>({kind,slug:'team-a',base:kind==='claude'?'https://anthropic.example':'https://openai.example/v1',key:'fixture-upstream-key',proxy:'',models:'provider-model => local-model',enabled:true});
for(const kind of ['gpt','claude','grok'])test(kind+' native config, model prefix, no caller key',()=>{
 const r=c.build(draft(kind));assert.equal(r.family,kind==='claude'?'claude':'openai-compatibility');assert.equal(r.group.prefix,'snow-'+kind+'-team-a');assert.equal(r.group.keys[0]['api-key'],'fixture-upstream-key');assert.deepEqual(r.group.models,[{name:'provider-model',alias:'local-model'}]);
});
test('remote cleartext and credential-bearing URLs refused',()=>{for(const base of ['http://remote.example/v1','https://user:pass@remote.example','https://remote.example?key=secret','file:///etc/passwd','https://remote.example/v1/messages'])assert.throws(()=>c.build({...draft('gpt'),base}))});
test('loopback mock transport allowed',()=>assert.equal(c.url('http://127.0.0.1:18880/v1/'),'http://127.0.0.1:18880/v1'));
test('proxy optional and explicit protocols',()=>{assert.equal(c.url('',true),'');assert.equal(c.url('socks5://test:fixture@proxy.example:1234',true),'socks5://test:fixture@proxy.example:1234');assert.throws(()=>c.url('javascript:alert(1)',true))});
test('missing or invalid fields rejected',()=>{for(const delta of [{kind:'other'},{slug:'with space'},{key:''},{models:''},{models:'up => local\nup2 => local'},{models:'up => '},{models:'up => too => many'},{models:'up/name'}])assert.throws(()=>c.build({...draft('gpt'),...delta}))});
test('new channel cannot overwrite imported credentials',()=>{
 const cfg={'api-keys':{'claude':[{name:'old',keys:[{'api-key':'fixture-old',headers:{X:'kept'}}]}]}};const before=JSON.stringify(cfg);const r=c.replace(cfg,draft('claude'));assert.equal(r.groups.length,2);assert.equal(r.groups[0].keys[0].headers.X,'kept');assert.equal(JSON.stringify(cfg),before);
});
test('duplicate prefix rejected',()=>{const d=draft('gpt'),g=c.build(d).group;assert.throws(()=>c.replace({'api-keys':{'openai-compatibility':[g]}},d))});
test('edit blank key preserves key and unknown fields',()=>{
 const d=draft('gpt'),g=c.build(d).group;g.headers={'X-Provider':'kept'};g.keys[0]['request-retry']=3;
 const cfg={'api-keys':{'openai-compatibility':[g]}};const row=c.entries(cfg)[0];const r=c.replace(cfg,{...d,key:'',models:'another'},row);assert.equal(r.group.keys[0]['api-key'],g.keys[0]['api-key']);assert.deepEqual(r.group.headers,g.headers);assert.equal(r.group.keys[0]['request-retry'],3);assert.deepEqual(cfg['api-keys']['openai-compatibility'][0].models,g.models);
});
test('stale edit rejected',()=>{const d=draft('gpt'),g=c.build(d).group,cfg={'api-keys':{'openai-compatibility':[g]}},row=structuredClone(c.entries(cfg)[0]);cfg['api-keys']['openai-compatibility'][0]['base-url']='https://other.example';assert.throws(()=>c.replace(cfg,d,row))});
test('disabled configurations exclude routing',()=>{for(const kind of ['gpt','claude','grok']){const {group}=c.build({...draft(kind),enabled:false});assert.equal(group.keys[0].weight,0);if(kind!=='claude')assert.equal(group.disabled,true)}});
test('type and slug immutable while editing',()=>{const d=draft('gpt'),p=c.build(d).group;assert.throws(()=>c.build({...d,kind:'grok'},p));assert.throws(()=>c.build({...d,slug:'new'},p))});
test('only channels owned by this editor listed',()=>{assert.equal(c.entries({'api-keys':{'claude':[{name:'legacy',prefix:'legacy',keys:[]}]}}).length,0)});
const sha=s=>require('node:crypto').createHash('sha256').update(s).digest('hex');
for(const kind of ['gpt','claude','grok'])test(kind+' config-backed identity and safe key editor projection',()=>{
 const {group:g,family}=c.build(draft(kind));g.keys[0].auth_index=sha((kind==='claude'?'claude-api-key:':'openai-compatibility:')+g['base-url']+'+'+g.keys[0]['api-key']).slice(0,16);
 const rows=c.credentials({'api-keys':{[family]:[g]}},sha);assert.equal(rows.length,1);assert.ok(rows[0].id.startsWith(kind==='claude'?'claude:apikey:':'openai-compatibility:snow-'+kind+'-team-a:'));assert.ok(!JSON.stringify(rows).includes('fixture-upstream-key'));
 g.keys[0].auth_index='bad';assert.throws(()=>c.credentials({'api-keys':{[family]:[g]}},sha));
});
test('unready runtime refused but disabled channel assignable',()=>{
 let {group:g,family}=c.build(draft('gpt'));assert.throws(()=>c.credentials({'api-keys':{[family]:[g]}},sha));g.disabled=true;assert.equal(c.credentials({'api-keys':{[family]:[g]}},sha)[0].disabled,true);
});
test('save confirmation verifies enabled state, proxy and models',()=>{
 const expected=c.build(draft('gpt')).group;assert.ok(c.verified(structuredClone(expected),expected));
 for(const mutate of [g=>g.disabled=true,g=>g.keys[0].weight=0,g=>g.keys[0]['proxy-url']='http://other.example',g=>g.models=[],g=>g.keys[0]['api-key']='changed']){const saved=structuredClone(expected);mutate(saved);assert.equal(c.verified(saved,expected),false)}
});
test('complete management module parses',()=>{const html=fs.readFileSync(__dirname+'/management.html','utf8'),js=html.match(/<script\b[^>]*>([\s\S]*?)<\/script>/)[1];try{new vm.SourceTextModule(js)}catch(e){throw Error(e.message)};assert.ok(js.includes('path:`/upstream-channels`'));assert.ok(js.includes(".filter(a=>typeof a.id==='string'&&a.id)"))});
