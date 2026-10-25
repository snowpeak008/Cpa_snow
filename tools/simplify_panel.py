"""Pinned frontend-only patches. Never transform configuration sent to the server."""
import hashlib


def simplify_panel(source, root):
    changes = []

    def replace(old, new, name):
        nonlocal source
        assert source.count(old) == 1, f'{name}: expected one pinned match'
        source = source.replace(old, new)
        changes.append(name)

    def replace_between(start, end, new, name):
        nonlocal source
        assert source.count(start) == 1 and source.count(end) == 1, name
        a = source.index(start)
        b = source.index(end, a)
        replace(source[a:b], new, name)

    # Keep API clients and backend capability flags intact. Restrict only rendered routes.
    allowed = '[`/`,`/dashboard`,`/auth-files`,`/auth-files/oauth-excluded`,`/auth-files/oauth-model-alias`,`/quota`,`/config`,`/system`,`*`]'
    replace('return br(Joe(Fm(e=>e.supportsPlugin)),e)',
            f'return br(Joe(Fm(e=>e.supportsPlugin)).filter(r=>{allowed}.includes(r.path)),e)',
            'Five sections; removed UI routes fall back to dashboard')
    replace('],he=me.flatMap(e=>Qoe(e.items))',
            '].map(g=>({...g,items:g.items.filter(i=>[`/`,`/auth-files`,`/quota`,`/config`,`/system`].includes(i.path))})).filter(g=>g.items.length),he=me.flatMap(e=>Qoe(e.items))',
            'Filter core and dynamic sidebar menus')
    replace('let ce=(0,y.useCallback)(async()=>{if(i!==`connected`||!o){k([]);return}try{let e=await Ky.list();k(YM(e.plugins))}catch{k([])}},[i,o])',
            'let ce=(0,y.useCallback)(async()=>{k([])},[])',
            'Do not fetch plugin menus from the simplified shell')
    replace('children:M.map(e=>(0,H.jsxs)(Yi,{to:e.to,className:K.ctaCard',
            'children:M.filter(i=>[`/auth-files`,`/quota`,`/config`,`/system`].includes(i.to)).map(e=>(0,H.jsxs)(Yi,{to:e.to,className:K.ctaCard',
            'Restrict dashboard shortcuts')
    replace('to:`/ai-providers`,className:K.primaryAction,children:e(`dashboard.cta_manage_providers`)',
            'to:`/auth-files`,className:K.primaryAction,children:e(`nav.auth_files`)',
            'Primary dashboard action opens authentication files')
    replace('to:`/logs`,className:K.ghostAction,children:[e(`dashboard.cta_inspect_logs`)',
            'to:`/quota`,className:K.ghostAction,children:[e(`nav.quota_management`)',
            'Secondary dashboard action opens quotas')
    replace('O=[n?`v${n.trim().replace(/^[vV]+/,``)}`:null,D].filter(Boolean).join(` · `)',
            'O=D', 'Hide backend version in dashboard heading')
    replace('children:A.map(e=>(0,H.jsxs)(`div`,{className:K.specRow',
            'children:A.slice(0,3).map(e=>(0,H.jsxs)(`div`,{className:K.specRow',
            'Dashboard summary omits backend version, build and proxy credential URL')
    replace('(0,H.jsx)(U,{variant:`ghost`,size:`sm`,onClick:()=>o(`/oauth`),children:e(`auth_files.empty_oauth_link`)})',
            'null', 'Remove removed-section shortcut from authentication empty state')
    replace('L=(0,y.useMemo)(()=>cN(r),[r])',
            'L=(0,y.useMemo)(()=>cN(r).filter(e=>e.type!==`plugin`),[r])',
            'Omit plugin-specific quota entries from presentation')
    replace('[l,u]=(0,y.useState)(()=>MP()?.tab??`all`)',
            '[l,u]=(0,y.useState)(()=>MP()?.tab===`plugin`?`all`:MP()?.tab??`all`)',
            'Clear remembered hidden quota tab in this UI only')
    replace('types:FP,counts:R,active:l', 'types:FP.filter(e=>e!==`plugin`),counts:R,active:l',
            'Hide plugin quota category')

    # Keep the original component unmounted, replace the route component with a small view.
    center = (root / 'web/snow-center.js').read_text(encoding='utf-8')
    replace('function qoe(){', center + '\nfunction qoeOriginal(){',
            'Simple center component without upstream identity, update controls or project links')

    # The visual editor retains original parsing, merge and save code. Only UI changes here.
    replace_between('(0,H.jsx)(Pb,{label:a(`config_management.visual.sections.advanced.plugins_title`)',
                    '(0,H.jsx)(Pb,{label:a(`config_management.visual.sections.advanced.antigravity_title`)',
                    '', 'Remove plugin settings accordion')
    replace('f=(0,y.useMemo)(()=>NV(r,n),[r,n])',
            'f=(0,y.useMemo)(()=>NV(r,n).filter(e=>!/^plugin/i.test(e.fieldId)),[r,n])',
            'Exclude plugin settings from visual field search')
    replace('var PV=AV.length,', 'var PV=AV.filter(e=>!/^plugin/i.test(e.fieldId)).length,',
            'Count only visible configuration fields')
    replace('function MV(e){if(e)return AV.find(t=>t.fieldId===e)}',
            'function MV(e){if(e&&!/^plugin/i.test(e))return AV.find(t=>t.fieldId===e)}',
            'Ignore deep links into hidden settings')
    replace('[S,C]=(0,y.useState)(()=>r?`visual`:WV(localStorage.getItem(EV)))',
            '[S,C]=(0,y.useState)(`visual`)',
            'Always open visual configuration editor')
    replace('(0,H.jsx)(J1,{mode:S,disabled:k.saving||k.loading||k.diffModalOpen||k.recoveryRequired,onChange:F})',
            'null', 'Remove raw YAML mode selector')
    replace('S!==`visual`||!m||(C(`source`),localStorage.setItem(EV,`source`),o(e(`config_management.visual_mode_unavailable_detail`,{message:m}),`error`))',
            'S!==`visual`||!m||o(e(`config_management.visual_mode_unavailable_detail`,{message:m}),`error`)',
            'Parse errors remain errors instead of displaying raw configuration')
    replace('original:k.serverYaml,modified:k.mergedYaml,onConfirm:k.handleConfirmSave',
            'original:snowDisplayYaml(k.serverYaml),modified:snowDisplayYaml(k.mergedYaml),onConfirm:k.handleConfirmSave',
            'Hide internal configuration in display-only diff, preserve actual save inputs')
    # The bundled JavaScript resets the favicon after loading; point it at our favicon too.
    replace('if($9)$9.href=x,$9.type=`image/jpeg`;',
            'if($9)$9.type=`image/svg+xml`;', 'Preserve Snow favicon at runtime')
    # Confirm these high-impact implementation functions remain byte-for-byte identical.
    invariants = {}
    original = (root / 'web/upstream-management.html').read_text(encoding='utf-8')
    for begin, end in [('function ZV(', 'function '), ('function mV(', 'function ')]:
        a = original.index(begin); b = original.index(end, a + len(begin))
        raw = original[a:b]
        # Branding translations do not occur inside the save/merge hooks.
        assert raw in source, 'Configuration save/merge logic changed: ' + begin
        invariants[begin] = hashlib.sha256(raw.encode()).hexdigest()
    return source, {'changes': changes, 'configuration_save_hook_hashes': invariants}
