/* Channel configuration only; upstream traffic remains in CPA's native executors. */
var SnowUpstreams=(()=>{
 const kinds={gpt:{label:'GPT',family:'openai-compatibility',protocol:'OpenAI Chat Completions'},claude:{label:'Claude',family:'claude',protocol:'Anthropic Messages'},grok:{label:'Grok',family:'openai-compatibility',protocol:'OpenAI Chat Completions'}};
 const clone=v=>JSON.parse(JSON.stringify(v));
 function url(value,proxy=false){
  if(!value&&proxy)return '';
  let u;try{u=new URL(value)}catch{throw Error('请填写完整 URL。')}
  if(!(proxy?['http:','https:','socks5:','socks5h:']:['https:','http:']).includes(u.protocol)||u.hash||u.search||(!proxy&&(u.username||u.password)))throw Error('地址格式不支持：API 地址不能携带凭证、查询参数或片段。');
  if(!proxy&&/\/(messages|chat\/completions|responses)\/?$/.test(u.pathname))throw Error('填写服务根地址，不要包含 messages、chat/completions 或 responses 请求路径。');
  if(!proxy&&u.protocol==='http:'&&!['127.0.0.1','localhost','[::1]'].includes(u.hostname))throw Error('远程 API 地址必须使用 HTTPS。');
  return u.toString().replace(/\/+$/,'');
 }
 function models(value){
  const out=[],seen=new Set();
  for(const line of value.split('\n').map(v=>v.trim()).filter(Boolean)){
   const parts=line.split('=>').map(v=>v.trim());if(parts.length>2||!parts[0]||parts.length===2&&!parts[1])throw Error('模型格式为：上游模型名 => 本地别名，每行一个。');
   const [name,alias=name]=parts;if(/[\s/?#]/.test(name+alias)||seen.has(alias))throw Error('模型名不能包含空格、斜线或重复别名。');
   seen.add(alias);out.push({name,alias});
  }
  if(!out.length)throw Error('至少填写一个由上游提供的模型名。');return out;
 }
 function build(d,previous){
  const kind=kinds[d.kind];if(!kind)throw Error('请选择 GPT、Claude 或 Grok。');
  const slug=d.slug.trim();if(!/^[a-z][a-z0-9-]{0,39}$/.test(slug))throw Error('渠道标识为小写英文开头，允许数字和连字符，最长 40 位。');
  const prefix='snow-'+d.kind+'-'+slug;
  if(previous&&previous.prefix!==prefix)throw Error('编辑时不能修改渠道标识或类型，请另建渠道。');
  const key=d.key.trim()||previous?.keys?.[0]?.['api-key'];if(!key||/[\r\n\s]/.test(key))throw Error('请输入有效的上游 Key。');
  const group=previous?clone(previous):{};group.name=prefix;group.prefix=prefix;group['base-url']=url(d.base);group.models=models(d.models);
  const entry={...(group.keys?.[0]||{}),'api-key':key,'proxy-url':url(d.proxy.trim(),true),weight:d.enabled?1:0};
  delete entry.auth_index;delete entry['auth-index'];group.keys=[entry];delete group.auth_index;delete group['auth-index'];
  if(kind.family==='openai-compatibility')group.disabled=!d.enabled;
  return {family:kind.family,group};
 }
 function entries(config){
  const rows=[];
  for(const [kind,k] of Object.entries(kinds))for(const [index,g] of (config['api-keys']?.[k.family]||[]).entries()){
   const marker='snow-'+kind+'-';if(typeof g.prefix==='string'&&g.prefix.startsWith(marker)&&g.keys?.length===1)rows.push({kind,index,group:g,slug:g.prefix.slice(marker.length)});
  }
  return rows;
 }
 function replace(config,d,previous){
  const {family,group}=build(d,previous?.group);const all=clone(config['api-keys']?.[family]||[]);
  if(previous){if(JSON.stringify(all[previous.index])!==JSON.stringify(previous.group))throw Error('渠道配置已变化，请重新读取后再编辑。');all[previous.index]=group}
  else{if(all.some(g=>g.name===group.name||g.prefix===group.prefix))throw Error('渠道标识已存在。');all.push(group)}
  return {family,groups:all,group};
 }
 function credentials(config,sha){
  return entries(config).flatMap(row=>{
   const g=row.group,k=g.keys[0],key=(k['api-key']||'').trim(),base=(g['base-url']||'').trim(),proxy=(k['proxy-url']??g['proxy-url']??'').trim(),prefix=(k.prefix??g.prefix??'').trim();
   if(!key||!base)return [];
   const claude=row.kind==='claude',headers=k.headers??g.headers??{};
   const serialized=Object.keys(headers).sort().map(n=>n+'\0'+headers[n]+'\0').join('');
   const kind=claude?'claude:apikey':'openai-compatibility:'+g.name.toLowerCase().trim();
   const parts=claude?[key,base,proxy,prefix,serialized]:[key,base,proxy];
   const id=kind+':'+sha([kind,...parts.map(v=>v.trim())].join('\0')).slice(0,12);
   const expected=sha((claude?'claude-api-key:':'openai-compatibility:')+base+'+'+key).slice(0,16);
   const actual=k.auth_index||k['auth-index'];
   if(actual&&actual!==expected)throw Error('渠道运行时身份与配置不匹配，请重新读取。');
   if(!actual&&!g.disabled&&k.weight!==0)throw Error('渠道运行时尚未就绪，请稍后重新读取。');
   return [{id,provider:row.kind,name:kinds[row.kind].label+' · '+row.slug,email:'',disabled:!!g.disabled||k.weight===0,channel:true}];
  });
 }
 function verified(saved,expected){
  return !!saved&&saved.prefix===expected.prefix&&saved['base-url']===expected['base-url']&&saved.keys?.length===1&&saved.keys[0]['api-key']===expected.keys[0]['api-key']&&(saved.keys[0]['proxy-url']||'')===(expected.keys[0]['proxy-url']||'')&&(saved.keys[0].weight??1)===expected.keys[0].weight&&!!saved.disabled===!!expected.disabled&&JSON.stringify(saved.models)===JSON.stringify(expected.models);
 }
 return {kinds,url,models,build,entries,replace,credentials,verified};
})();
if(typeof module!=='undefined')module.exports=SnowUpstreams;
