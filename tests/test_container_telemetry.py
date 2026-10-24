import copy
from pathlib import Path
import unittest
from sdwan.config import load,validate
from sdwan.container_config import telemetry
from sdwan import container_telemetry as web

ROOT=Path(__file__).resolve().parents[1]
class Router:
    def __init__(self,config):
        self.data={'interface/print':[{'name':s} for s in ('ether2','ether3','ether4','ether5','bridge-lan','vlan-office')],
                   'interface/bridge/port/print':[],'interface/list/member/print':[],'interface/list/print':[],
                   'interface/pppoe-client/print':[],'interface/vlan/print':[],'disk/print':[],
                   'ip/firewall/filter':[dict(fields,comment='sdwan-container:'+tag) for tag,fields in web.rule_specs(config)]+[{'comment':'sdwan-container:'+s,'chain':'forward','action':'drop'} for s in ('no-forward','no-forward-to-container')],
                   'ip/firewall/address-list':[{'list':web.CLIENTS,'address':s,'comment':web.PREFIX+'source'} for s in telemetry(config)['allowed_sources']]}
        for rows in self.data.values():
            for n,row in enumerate(rows):row['.id']='*'+str(n)
        self.calls=[]
    def call(self,path,data=None,method=None):
        self.calls.append((path,data,method));assert method in (None,'POST');return copy.deepcopy(self.data[path])
    def read_file(self,path):assert path=='token';return 'a'*64

class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.cfg=load(ROOT/'config/examples/container.json')
        self.cfg['container']['telemetry']={'enabled':True,'allowed_sources':['192.168.50.0/24'],'allowed_interfaces':['ether5']}
    def test_disabled_default_adds_no_listener_rules_or_process_settings(self):
        self.cfg['container'].pop('telemetry');validate(self.cfg)
        self.assertFalse(telemetry(self.cfg)['enabled']);self.assertIsNone(web.process_settings(self.cfg));self.assertEqual(web.rule_specs(self.cfg),[])
    def test_explicit_lan_scopes_and_bounded_ram(self):
        validate(self.cfg);process=web.process_settings(self.cfg)
        self.assertEqual(process['listen'],'172.31.255.2:8080');self.assertEqual(process['token_file'],'/secrets/web-token')
        self.assertNotIn('token',process);self.assertEqual(process['history_points'],360)
        rules=web.rule_specs(self.cfg);self.assertEqual(len(rules),len(self.cfg['wans'])+2)
        self.assertEqual(rules[-2][1]['in-interface'],'ether5');self.assertEqual(rules[-2][1]['src-address-list'],web.CLIENTS)
        self.assertEqual(rules[-1][1]['connection-state'],'established')
    def test_invalid_or_public_sources_and_wan_interfaces_rejected(self):
        for key,value in [('enabled',1),('allowed_sources',[]),('allowed_sources',['0.0.0.0/0']),('allowed_sources',['8.8.8.0/24']),('allowed_sources',['10.8.0.0/24']),('allowed_sources',['192.168.50.1/24']),('allowed_sources',['192.168.50.0/24']*2),('allowed_interfaces',[]),('allowed_interfaces',['ether2']),('allowed_interfaces',['sdwan-container-mgmt']),('sample_seconds',4),('history_points',601),('port',80),('token','forbidden')]:
            with self.subTest(key=key,value=value):
                cfg=copy.deepcopy(self.cfg);cfg['container']['telemetry'][key]=value
                with self.assertRaises(ValueError):validate(cfg)
        self.cfg['controller_backend']='routeros'
        with self.assertRaises(ValueError):validate(self.cfg)
    def test_missing_interface_wan_list_and_transitive_bridge_conflicts(self):
        for rows in [{'interface/print':[]},{'interface/list/member/print':[{'list':'WAN','interface':'ether5'}]},{'interface/bridge/port/print':[{'interface':'ether2','bridge':'bridge-lan'},{'interface':'ether5','bridge':'bridge-lan'}]}]:
            r=Router(self.cfg);r.data.update(rows)
            with self.assertRaises(ValueError):web.validate_interfaces(r,self.cfg)
        web.validate_interfaces(Router(self.cfg),self.cfg)
    def test_prepared_acl_settings_and_web_capability_must_match(self):
        actual={'telemetry':web.process_settings(self.cfg)};r=Router(self.cfg)
        web.check_ready(r,self.cfg,actual,'/sdwan-controller-web','token')
        self.assertTrue(all(method in (None,'POST') for _,_,method in r.calls))
        with self.assertRaisesRegex(ValueError,'optional web'):web.check_ready(r,self.cfg,actual,'/sdwan-controller','token')
        r.data['ip/firewall/filter'][-3]['in-interface']='ether2'
        with self.assertRaisesRegex(ValueError,'scope'):web.check_ready(r,self.cfg,actual,'/sdwan-controller-web','token')
    def test_rule_order_and_foreign_sources_fail_closed(self):
        actual={'telemetry':web.process_settings(self.cfg)}
        for mutate in [lambda r:r.data['ip/firewall/filter'].reverse(),lambda r:r.data['ip/firewall/address-list'].append({'list':web.CLIENTS,'address':'192.168.50.10','comment':'foreign'})]:
            r=Router(self.cfg);mutate(r)
            with self.assertRaises(ValueError):web.check_ready(r,self.cfg,actual,'/sdwan-controller-web','token')
    def test_tokens_have_fixed_dedicated_shape(self):
        self.assertTrue(web.valid_token('a'*64))
        for token in ('a'*63,'a'*65,'A'*64,'a'*63+'\n','secret',None):self.assertFalse(web.valid_token(token))
    def test_enabled_swap_is_rejected_without_modifying_global_disks(self):
        r=Router(self.cfg);r.data['disk/print']=[{'slot':'swap-file','swap':'true'}]
        with self.assertRaisesRegex(ValueError,'swap devices'):web.validate_interfaces(r,self.cfg)
        self.assertTrue(all(method in (None,'POST') for _,_,method in r.calls))
    def test_pppoe_and_vlan_wan_carriers_are_not_lan(self):
        self.cfg['wans'][0]['interface']='pppoe-isp'
        r=Router(self.cfg);r.data['interface/pppoe-client/print']=[{'name':'pppoe-isp','interface':'vlan-provider'}]
        r.data['interface/vlan/print']=[{'name':'vlan-provider','interface':'ether5'}]
        with self.assertRaisesRegex(ValueError,'WAN/container'):web.validate_interfaces(r,self.cfg)
        self.cfg['container']['telemetry']['allowed_interfaces']=['vlan-office'];web.validate_interfaces(r,self.cfg)
    def test_wan_list_include_exclude_and_explicit_membership(self):
        r=Router(self.cfg);r.data['interface/list/print']=[{'name':'WAN','include':'provider-ports','exclude':'internal'},{'name':'provider-ports'},{'name':'internal'}]
        r.data['interface/list/member/print']=[{'list':'provider-ports','interface':'ether5'}]
        with self.assertRaisesRegex(ValueError,'WAN/container'):web.validate_interfaces(r,self.cfg)
        r.data['interface/list/member/print'].append({'list':'internal','interface':'ether5'});web.validate_interfaces(r,self.cfg)
        r.data['interface/list/member/print'].append({'list':'WAN','interface':'ether5'})
        with self.assertRaisesRegex(ValueError,'WAN/container'):web.validate_interfaces(r,self.cfg)

if __name__=='__main__':unittest.main()
