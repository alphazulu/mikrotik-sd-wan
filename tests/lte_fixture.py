"""CHR-only LTE metadata adapter over a real PPP point-to-point data link.

APN objects, routing, scripts, SLA, NAT and traffic are real RouterOS. The
physical LTE device inventory is substituted only in temporary test packages.
No test mode is added to production code; this does not test a radio modem.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab
from sdwan.router import Router
from dynamic_wan_fixture import dynamic_wans

IFACE='sdwan-test-pppoe';PROFILE='sdwan-test-lte-apn';STATE='sdwan-test-lte-radios.json'


class MetadataRouter:
    def __init__(self,router):self.router=router
    def __getattr__(self,key):return getattr(self.router,key)
    def call(self,path,data=None,method=None):
        if path in ('interface/lte','interface/lte/print'):
            raw=json.loads(self.router.read_file(STATE));result=[]
            interfaces={x['name']:x for x in self.router.call('interface')}
            for item in raw:
                iface=interfaces.get(item['name'],{})
                result.append({'.id':item.get('id','*1'),'name':item['name'],'apn-profiles':','.join(item['profiles']),'disabled':iface.get('disabled','true'),'running':iface.get('running','false')})
            return result
        result=self.router.call(path,data,method)
        if path.rstrip('/').startswith('interface/pppoe-client') and (method is None or method=='GET' or path.endswith('/print')) and isinstance(result,list):return [x for x in result if x.get('name')!=IFACE]
        if path in ('interface','interface/print') and isinstance(result,list):
            return [dict(x,type='lte') if x.get('name')==IFACE else x for x in result]
        return result


def adapted_links(source):
    a=source.index(':global sdwanLTEInterfaces do={');b=source.index(':global sdwanLTEBinding do={',a)
    replacement='''# CHR TEST ONLY: LTE inventory adapter; PPP carries real packets.
:global sdwanLTEInterfaces do={
    :local radios [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="sdwan-test-lte-radios.json"] contents]]
    :foreach index,radio in=$radios do={
        :local iface ($radio->"name")
        :local id [/interface/find where name=$iface]
        :if ([:len $id] = 1) do={
            :set ($radio->"running") [/interface/get $id running]
            :set ($radio->"disabled") [/interface/get $id disabled]
        } else={ :set ($radio->"running") false; :set ($radio->"disabled") true }
        :set ($radios->$index) $radio
    }
    :return $radios
}
'''
    return source[:a]+replacement+source[b:]


@contextmanager
def package_adapter(cli):
    original=cli.bundle
    def bundle(cfg,output):
        package=original(cfg,output);path=package/'sdwan-links.rsc';path.write_text(adapted_links(path.read_text()));return package
    with patch.object(cli,'bundle',side_effect=bundle):yield


@contextmanager
def lte_wan(add_default=False):
    r=Router(ROOT,'api://127.0.0.1:18728')
    with dynamic_wans(component_tables=False) as ids:
        try:
            ids['add']('edge','interface/lte/apn',{'name':PROFILE,'apn':'internet','add-default-route':'true' if add_default else 'false','default-route-distance':'77','use-peer-dns':'false','use-network-apn':'false','ip-type':'ipv4'})
            for iface in ('sdwan-test-dhcp-vlan',IFACE):ids['add']('edge','interface/list/member',{'list':'WAN','interface':iface,'comment':'dynamic-wan-acceptance-only'})
            r.upload(STATE,json.dumps([{'id':'*test','name':IFACE,'profiles':[PROFILE]}]))
            yield ids,MetadataRouter(r)
        finally:
            for row in r.call('file/print',{'.proplist':'.id,name'},'POST'):
                if row.get('name')==STATE:r.call('file/'+row['.id'],method='DELETE')
            r.close()
