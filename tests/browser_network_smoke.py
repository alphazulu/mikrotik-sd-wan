"""Offline Chromium fixture: embedded dashboard network panels, aging and logout."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--chrome',required=True);p.add_argument('--playwright-path',type=Path);p.add_argument('--assets',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
 if args.playwright_path:sys.path.insert(0,str(args.playwright_path))
 from playwright.sync_api import sync_playwright,expect
 asset=args.assets or ROOT/'container-controller/web';token='a'*64;errors=[];transport={'offline':False};checks=[];status={'schema':1,'epoch':1,'stale':False,'age_seconds':1,'history_points':0,'history_capacity':12,'observer_available':False,'resources':{'rss_bytes':None},'current':{'actor':'routeros-fallback','uptime_seconds':15,'profile':'default','wans':[dict(name='wan1',interface='ether2',address='192.0.2.2',state='healthy',rtt_us=1000,jitter_us=100,loss_basis_points=0,rx_bps=1000,tx_bps=2000,observed_seconds=15,unhealthy_seconds=0,warming=False,stale=False)],'policies':[dict(name='default',selected='wan1',transitions=1)],'qualities':{},'transports':[dict(name='vpn1',configured='drain',effective='drain',admit=False,elapsed_seconds=5,timeout_seconds=30,vpn_underlay='wan2',vpn_ready=True)],'overlay':[dict(name='hub-wan1',wan='wan1',cost=10,healthy=True,probe_up=True,sample_age_seconds=1,good_windows=3,bad_windows=0,reason='<img src=x onerror=alert(1)>')]}}
 if args.output:args.output.mkdir(parents=True,exist_ok=False)
 def note(text):checks.append(text);print('PASS '+text,flush=True)
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=args.chrome,headless=True);context=browser.new_context(viewport={'width':1280,'height':900});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  def serve(route):
   path=route.request.url.removeprefix('http://sdwan.test');path=path.split('?')[0]
   if path.startswith('/api/'):
    assert route.request.headers.get('authorization')=='Bearer '+token
    if transport['offline']:route.abort('connectionrefused');return
    value=status if path=='/api/status' else {'epoch':1,'wans':{},'events':[]};route.fulfill(status=200,content_type='application/json',body=json.dumps(value));return
   filename={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}.get(path)
   if filename:route.fulfill(status=200,content_type={'index.html':'text/html','app.js':'text/javascript','style.css':'text/css'}[filename],headers={'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"},body=(asset/filename).read_text(encoding='utf-8'))
   else:route.fulfill(status=404,body='')
  page.route('http://sdwan.test/**',serve);page.goto('http://sdwan.test/',wait_until='networkidle');page.locator('#token').fill(token);page.locator('#auth button').click();page.locator('#dashboard').wait_for(state='visible')
  assert page.locator('#transports tr').count()==1 and page.locator('#overlay tr').count()==1;assert 'wan2' in page.locator('#transports').inner_text();assert 'Допущен' in page.locator('#overlay').inner_text();assert page.locator('#overlay img').count()==0;assert '<img src=x' in page.locator('#overlay').inner_text();note('browser renders bounded VPN/drain and inner SLA panels with escaped text')
  if args.output:page.screenshot(path=str(args.output/'ready.png'),full_page=True)
  status['stale']=True;expect(page.locator('#overlay')).to_contain_text('Устарело',timeout=8000);assert 'Устарело' in page.locator('#transports').inner_text();note('stale controller status invalidates displayed VPN readiness and overlay admission')
  status['stale']=False;page.locator('#actor:not(.stale)').wait_for(state='visible',timeout=8000)
  transport['offline']=True;page.locator('#actor.stale').wait_for(state='visible',timeout=8000)
  assert page.locator('#age').inner_text()=='—' and 'Нет свежих данных' in page.locator('#wans').inner_text();assert 'Устарело' in page.locator('#transports').inner_text() and 'Устарело' in page.locator('#overlay').inner_text();note('failed HTTP requests invalidate previous green WAN cards, admission and age')
  if args.output:page.screenshot(path=str(args.output/'offline.png'),full_page=True)
  transport['offline']=False;page.locator('#actor:not(.stale)').wait_for(state='visible',timeout=8000);assert page.locator('#age').inner_text()=='1 с';assert 'Нет свежих данных' not in page.locator('#wans').inner_text();note('fresh HTTP response restores current data without changing authentication')
  status['current']['policies'][0]['selected']='none';expect(page.locator('#policies')).to_contain_text('Нет доступного канала',timeout=8000);note('no selected WAN is shown in readable form')
  page.set_viewport_size({'width':390,'height':844});cdp=context.new_cdp_session(page);assert cdp.send('Page.getLayoutMetrics')['cssContentSize']['width']<=390
  for local in (True,False):assert not cdp.send('DOMStorage.getDOMStorageItems',{'storageId':{'securityOrigin':'http://sdwan.test','isLocalStorage':local}})['entries']
  if args.output:page.screenshot(path=str(args.output/'mobile.png'),full_page=True)
  page.locator('#logout').click();assert page.locator('#login').is_visible() and page.locator('#overlay tr').count()==0 and page.locator('#transports tr').count()==0;assert page.locator('#age').inner_text()=='—';assert not errors,errors;note('mobile layout stays within viewport and logout clears network state without browser storage')
  if args.output:(args.output/'report.json').write_text(json.dumps({'pass':True,'checks':checks,'page_errors':errors,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [asset/'index.html',asset/'app.js',asset/'style.css',Path(__file__)]}},ensure_ascii=False,indent=2)+'\n')
  context.close();browser.close()

if __name__=='__main__':main()
