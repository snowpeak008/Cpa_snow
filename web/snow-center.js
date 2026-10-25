// Presentation only. Uses the existing authenticated connection store; no extra API calls.
function qoe() {
  const connection = Fm(e => e.connectionStatus);
  const base = Fm(e => e.apiBase);
  const authenticated = Fm(e => e.isAuthenticated);
  const connected = connection === 'connected';
  let address = '—';
  try { address = new URL(base).origin; } catch {}
  return (0,H.jsxs)('section', {className:'snow-center', children:[
    (0,H.jsxs)('header', {className:'snow-center-heading', children:[
      (0,H.jsx)('span', {className:'snow-eyebrow',children:'SNOW CONSOLE'}),
      (0,H.jsx)('h1', {children:'中心信息'}),
      (0,H.jsx)('p', {children:'连接概况，一目了然。'})
    ]}),
    (0,H.jsxs)('div', {className:'snow-center-card',children:[
      (0,H.jsxs)('div', {className:'snow-center-brand',children:[
        (0,H.jsx)('img', {className:'sidebar-brand-logo',src:x,alt:'Snow Console',width:56,height:56}),
        (0,H.jsxs)('div', {children:[
          (0,H.jsx)('h2', {children:'Snow Console'}),
          (0,H.jsx)('p', {children:'雪峰控制台'})
        ]}),
        (0,H.jsx)('span', {className:'snow-connection '+(connected?'connected':''),children:connected?'已连接':connection==='connecting'?'连接中':'未连接'})
      ]}),
      (0,H.jsx)('dl', {className:'snow-center-details',children:[
        ['管理入口',address],['登录状态',authenticated?'已登录':'未登录'],['界面版本','Snow __SNOW_VERSION__ · 简洁版']
      ].map(([label,value])=>(0,H.jsxs)('div',{children:[(0,H.jsx)('dt',{children:label}),(0,H.jsx)('dd',{children:value})]},label))}),
      (0,H.jsxs)('div', {className:'snow-center-footer',children:[
        (0,H.jsx)('span', {children:'账号、配额和连接设置，在左侧统一管理。'}),
        (0,H.jsx)(Yi, {to:'/config',children:'配置面板 →'})
      ]})
    ]})
  ]});
}

// Diff visualization only; never used to serialize or save configuration.
// Preserve line positions while omitting the top-level internal settings block and comments.
function snowDisplayYaml(value) {
  let hidden = false;
  return value.split('\n').map(line => {
    if (/^[^\s#][^:]*:/.test(line)) hidden = /^(?:plugins|["']plugins["'])\s*:/.test(line);
    return hidden || /^\s*#/.test(line) ? '' : line;
  }).join('\n');
}
