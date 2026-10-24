#!/usr/bin/env python3
"""Execute the actual native conversion helper on CHR; no routing changes."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router


def main():
    router=Router(ROOT)
    source=(ROOT/'native/sdwan-controller.rsc').read_text()
    helper=source[source.index('    :local scaled do={'):source.index('    :local report')]
    code=helper+r'''
:global sdwanNumericSelfTestJSON
:onerror err in={
 :local cfg [:deserialize from=json value="{\"rtt\":0.125,\"loss\":0.5,\"jitter\":15.0}"]
 :if ([$scaled value=($cfg->"rtt") scale=1000 digits=3] != 125) do={ :error "fractional RTT conversion" }
 :if ([$scaled value=($cfg->"loss") scale=100 digits=2] != 50) do={ :error "fractional loss conversion" }
 :if ([$scaled value=($cfg->"jitter") scale=1000 digits=3] != 15000) do={ :error "whole float conversion" }
 :set sdwanNumericSelfTestJSON "{\"pass\":true}"
} do={ :local x [:toarray ""]; :set ($x->"error") $err; :set sdwanNumericSelfTestJSON [:serialize to=json value=$x] }
'''
    for row in router.call('system/script/environment'):
        if row.get('name')=='sdwanNumericSelfTestJSON':router.call('system/script/environment/'+row['.id'],method='DELETE')
    script=None;scheduler=None
    try:
        script=router.call('system/script',{'name':'sdwan-selftest','source':code,'policy':'read,write,policy,test'},'PUT')
        scheduler=router.call('system/scheduler',{'name':'sdwan-selftest','interval':'1s','on-event':'/system/script/run sdwan-selftest','policy':'read,write,policy,test'},'PUT')
        time.sleep(3)
        rows=router.call('system/script/environment')
        result=json.loads(next(x['value'] for x in rows if x['name']=='sdwanNumericSelfTestJSON'))
        (ROOT/'runtime/native-numeric.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result.get('pass'),result
        print('PASS native decimal scaling: 0.125ms -> 125us; 0.5% -> 50bp; 15.0ms -> 15000us')
    finally:
        if scheduler:router.call('system/scheduler/'+scheduler['.id'],method='DELETE')
        if script:router.call('system/script/'+script['.id'],method='DELETE')

if __name__=='__main__':main()
