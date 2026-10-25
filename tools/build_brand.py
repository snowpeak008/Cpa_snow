"""Build the cleaned Snow template locally. No upstream download or server access."""
import base64
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
# Negative checks only; these are not request destinations.
FORBIDDEN = re.compile(r'api\.apikey\.fan|slb\.apikey\.fan|api\.fenno\.ai|api\.qnaigc\.com|api\.modelink\.ai|bestproxy|qoeOriginal|SponsorQuickStartPanel|cpa-promotion-disabled|help\.router-for\.me|apikeyFun|fennoAI|qiniuCloud', re.I)

def build():
    source = (ROOT / 'web/panel-base.html').read_text(encoding='utf-8')
    assert not FORBIDDEN.search(source), 'Removed referral code reappeared in template'
    assert 'https://github.com/router-for-me/' not in source, 'Old center/repository address reappeared'
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', version), 'Invalid version'
    center = (ROOT / 'web/snow-center.js').read_text(encoding='utf-8').replace('__SNOW_VERSION__', version)
    logo = 'data:image/svg+xml;base64,' + base64.b64encode((ROOT / 'web/snow-logo.svg').read_bytes()).decode()
    css = (ROOT / 'web/snow.css').read_text(encoding='utf-8')
    css += '\n' + ', '.join(['[class*="LoginPage-module__logo"]', '[class*="LoginPage-module__splashLogo"]', '.sidebar-brand-logo', '[class*="SystemPage-module__aboutLogo"]']) + ' { content:url("' + logo + '"); }\n'
    replacements = {
        '/* SNOW_CENTER_COMPONENT */': center,
        '<!-- SNOW_THEME -->': '<style id="snow-console-theme">' + css + '</style>',
        '<!-- SNOW_FAVICON -->': '<link rel="icon" type="image/svg+xml" href="' + logo + '">',
    }
    output = source
    for marker, replacement in replacements.items():
        assert output.count(marker) == 1, 'Template marker missing or duplicated: ' + marker
        output = output.replace(marker, replacement)
    assert not FORBIDDEN.search(output), 'Removed referral code reappeared in output'
    target = ROOT / 'web/management.html'
    target.write_text(output, encoding='utf-8', newline='\n')
    evidence = ROOT / 'evidence'
    evidence.mkdir(exist_ok=True)
    report = {
        'version': version, 'source': 'web/panel-base.html',
        'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'referral_code_absent': True, 'production_deployed': False,
        'boundary': 'Cleaned five-section frontend only; backend image, authentication, routing and plugins unchanged.',
    }
    (evidence / 'branding-build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    release_path = ROOT / 'release.json'
    if release_path.exists():
        release = json.loads(release_path.read_text(encoding='utf-8'))
        release.update(version=version, ui_sha256=report['output_sha256'], production_deployed=False)
        release_path.write_text(json.dumps(release, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    build()
