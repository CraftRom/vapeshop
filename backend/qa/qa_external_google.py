"""Generate an offline browser fixture from the real production Google-tag renderer."""
from pathlib import Path
from api.routers.landing_pages import _google_markup,DEFAULT_GOOGLE
from qa_common import Report
r=Report('Google tag contracts')
config={**DEFAULT_GOOGLE,'enabled':True,'google_tag_id':'G-TEST123','ads_conversion_id':'AW-123456','ads_conversion_label':'TestLabel','consent_mode':'banner'}
meta,head,body=_google_markup(config,preview=False)
r.check(head.index("gtag('consent','default'")<head.index("gtag('config'"),'Consent Mode defaults precede measurement configuration')
r.check('gtag/js' in head and 'gtm.js?id=' not in head,'Google tag mode does not also load GTM')
_,preview_head,preview_body=_google_markup(config,preview=True)
r.check(not preview_head and not preview_body,'editor preview emits no Google tracking requests')
_,gtm_head,_=_google_markup({**config,'mode':'gtm','gtm_container_id':'GTM-TEST123'})
r.check('gtm.js?id=' in gtm_head and 'gtag/js' not in gtm_head,'GTM mode uses a single tagging strategy')
output=Path(__file__).resolve().parents[2]/'qa/output/external-google-fixture.html'
output.parent.mkdir(exist_ok=True)
output.write_text('<!doctype html><html><head>'+meta+head+'</head><body><a class="cta" href="/go">Магазин</a><span class="code">PROMO</span>'+body+'</body></html>',encoding='utf-8')
raise SystemExit(bool(r.done()))
