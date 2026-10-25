"""Offline Chromium fixture: embedded dashboard network panels, aging and logout."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--chrome',required=True);p.add_argument('--playwright-path',type=Path);args=p.parse_args()
 if args.playwright_path:sys.path.insert(0,str(args.playwright_path))
 from playwright.sync_api import sync_playwright
 asset=ROOT/'container-controller/web';token='a'*64;errors=[];status={'schema':1,'epoch':1,'stale':False,'age_seconds':1,'history_points':0,'history_capacity':12,'observer_available':False,'resources':{'rss_bytes':None},'current':{'actor':'routeros-fallback','uptime_seconds':15,'profile':'default','wans':[],'policies':[],'qualities':{},'transports':[dict(name='vpn1',configured='drain',effective='drain',admit=False,elapsed_seconds=5,timeout_seconds=30,vpn_underlay='wan2',vpn_ready=True)],'overlay':[dict(name='hub-wan1',wan='wan1',cost=10,healthy=True,probe_up=True,sample_age_seconds=1,good_windows=3,bad_windows=0,reason='<img src=x onerror=alert(1)>')]}}
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=args.chrome,headless=True);context=browser.new_context(viewport={'width':1280,'height':900});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  def serve(route):
   path=route.request.url.removeprefix('http://sdwan.test');path=path.split('?')[0]
   if path.startswith('/api/'):
    assert route.request.headers.get('authorization')=='Bearer '+token
    value=status if path=='/api/status' else {'epoch':1,'wans':{},'events':[]};route.fulfill(status=200,content_type='application/json',body=json.dumps(value));return
   filename={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}.get(path)
   if filename:route.fulfill(status=200,content_type={'index.html':'text/html','app.js':'text/javascript','style.css':'text/css'}[filename],body=(asset/filename).read_text(encoding='utf-8'))
   else:route.fulfill(status=404,body='')
  page.route('http://sdwan.test/**',serve);page.goto('http://sdwan.test/',wait_until='networkidle');page.locator('#token').fill(token);page.locator('#auth button').click();page.locator('#dashboard').wait_for(state='visible')
  assert page.locator('#transports tr').count()==1 and page.locator('#overlay tr').count()==1;assert 'wan2' in page.locator('#transports').inner_text();assert 'Допущен' in page.locator('#overlay').inner_text();assert page.locator('#overlay img').count()==0;assert '<img src=x' in page.locator('#overlay').inner_text();print('PASS browser renders bounded VPN/drain and inner SLA panels with escaped text')
  status['stale']=True;page.wait_for_function("document.querySelector('#overlay').textContent.includes('Устарело')",timeout=8000);assert 'Устарело' in page.locator('#transports').inner_text();print('PASS stale controller status invalidates displayed VPN readiness and overlay admission')
  page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth')<=390;assert page.evaluate('localStorage.length+sessionStorage.length')==0;page.locator('#logout').click();assert page.locator('#login').is_visible() and page.locator('#overlay tr').count()==0 and page.locator('#transports tr').count()==0;assert not errors,errors;print('PASS mobile layout stays within viewport and logout clears network state without browser storage')
  context.close();browser.close()

if __name__=='__main__':main()
