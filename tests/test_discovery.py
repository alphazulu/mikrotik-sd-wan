import copy
from pathlib import Path
import unittest
from sdwan.config import load
from sdwan.discovery import candidates,generate,discover,validate_wan_choices,WANSelectionError

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    inv={'identity':{'name':'ordinary-router'},'resource':{'version':'7.24.5'},'warnings':[],
      'interface':[{'name':'WAN ISP A','type':'ether','running':'true'},{'name':'ether2','type':'ether','running':'true'},{'name':'bridge-lan','type':'bridge','running':'true'}],
      'ip/address':[{'interface':'WAN ISP A','address':'192.0.2.2/30'},{'interface':'ether2','address':'198.51.100.2/30'},{'interface':'bridge-lan','address':'10.5.0.1/24'}],
      'ip/route':[{'.id':'*1','dst-address':'0.0.0.0/0','gateway':'192.0.2.1','distance':'1'},{'.id':'*2','dst-address':'0.0.0.0/0','gateway':'198.51.100.1','distance':'2'}],
      'routing/rule':[],'ip/dhcp-client':[],'interface/pppoe-client':[],'interface/bridge/port':[],'interface/list/member':[],
      'ip/firewall/filter':[],'ip/firewall/nat':[],'ip/firewall/mangle':[],'active_config':None}
    inv['candidates']=candidates(inv);return inv


def choices(inv):return [{k:c[k] for k in ('interface','address','gateway','priority')} for c in inv['candidates'] if c['suggested']]


def build(inv,chosen=None,**kwargs):
    return generate(inv,choices(inv) if chosen is None else chosen,probes=[{'name':n,'type':'tcp-conn','host':ip,'port':443} for n,ip in [('a','203.0.113.10'),('b','203.0.113.11'),('c','203.0.113.12')]],icmp_target='203.0.113.10',**kwargs)


class DiscoveryTests(unittest.TestCase):
    def test_uncommented_route_adoption_uses_exact_selector(self):
        cfg=build(fixture());self.assertEqual([r['.id'] for r in cfg['takeover_routes']],['*1','*2']);self.assertEqual(cfg['takeover_rule'],{'src-address':'','table':''})
    def test_custom_interface_name_preserved(self):self.assertEqual(build(fixture())['wans'][0]['interface'],'WAN ISP A')
    def test_local_network_derived_from_non_wan(self):self.assertEqual(build(fixture())['local_networks'],['10.5.0.0/24'])
    def test_user_priority_controls_order(self):
        inv=fixture();c=choices(inv);c[0]['priority']=2;c[1]['priority']=1;self.assertEqual(build(inv,c)['wans'][0]['interface'],'ether2')
    def test_nothing_selected(self):
        with self.assertRaisesRegex(ValueError,'внешний'):build(fixture(),[])
    def test_missing_gateway_not_guessed(self):
        inv=fixture();c=choices(inv);c[0]['gateway']=''
        with self.assertRaises(WANSelectionError) as caught:build(inv,c)
        self.assertEqual(caught.exception.interface,'WAN ISP A');self.assertEqual(caught.exception.field,'gateway')
        self.assertIn('не указан шлюз',str(caught.exception))
    def test_empty_wan_address_explains_where_to_fix_it(self):
        inv=fixture();chosen=choices(inv);chosen[0]['address']=''
        with self.assertRaises(WANSelectionError) as caught:validate_wan_choices(inv,chosen)
        self.assertEqual(caught.exception.field,'address');self.assertIn('WAN ISP A',str(caught.exception));self.assertNotIn('Address cannot be empty',str(caught.exception))
    def test_ambiguous_gateway_lists_choices(self):
        inv=fixture();inv['candidates'][0]['gateways']=['192.0.2.1','192.0.2.3'];chosen=choices(inv);chosen[0]['gateway']=''
        with self.assertRaisesRegex(WANSelectionError,'несколько вариантов: 192.0.2.1, 192.0.2.3'):validate_wan_choices(inv,chosen)
    def test_recursive_target_does_not_replace_real_gateway(self):
        inv=fixture();route=inv['ip/route'][0];route.update(gateway='203.0.113.100',**{'immediate-gw':'192.0.2.1%WAN ISP A'})
        inv['ip/route'].append({'.id':'*3','dst-address':'0.0.0.0/0','gateway':'192.0.2.1','routing-table':'provider-a'})
        inv['candidates']=candidates(inv)
        self.assertEqual(inv['candidates'][0]['gateways'],['192.0.2.1']);self.assertEqual(inv['candidates'][0]['gateway'],'192.0.2.1')
        cfg=build(inv);self.assertEqual(cfg['wans'][0]['gateway'],'192.0.2.1')
        self.assertEqual(cfg['takeover_routes'][0]['gateway'],'203.0.113.100')
    def test_unresolved_recursive_target_not_guessed_as_gateway(self):
        inv=fixture();inv['ip/route'][0]['gateway']='203.0.113.100';inv['candidates']=candidates(inv)
        self.assertEqual(inv['candidates'][0]['gateway'],'')
    def test_probe_domain_names_are_accepted(self):
        inv=fixture();cfg=generate(inv,choices(inv),icmp_target='203.0.113.10',probes=[{'name':host,'type':'tcp-conn','host':host,'port':443} for host in ('example.com','example.net','example.org')])
        self.assertEqual([p['name'] for p in cfg['wans'][0]['probes']],['example.com','example.net','example.org'])
    def test_no_subnet_dot_one_guess(self):
        inv=fixture();inv['ip/route']=[];inv['candidates']=candidates(inv);self.assertEqual(inv['candidates'][0]['gateways'],[])
    def test_multiple_addresses_require_choice(self):
        inv=fixture();inv['ip/address'].append({'interface':'ether2','address':'198.51.100.6/30'});self.assertEqual(candidates(inv)[1]['address'],'')
    def test_bridge_port_not_used_as_l3_wan(self):
        inv=fixture();inv['interface/bridge/port']=[{'interface':'ether2','bridge':'bridge-lan'}];inv['candidates']=candidates(inv)
        with self.assertRaisesRegex(ValueError,'bridge'):build(inv)
    def test_dhcp_not_frozen_into_static_snapshot(self):
        inv=fixture();inv['ip/dhcp-client']=[{'interface':'ether2','status':'bound','gateway':'198.51.100.1'}];inv['candidates']=candidates(inv)
        cfg=build(inv);wan=next(x for x in cfg['wans'] if x['interface']=='ether2')
        self.assertEqual(wan['kind'],'dhcp');self.assertNotIn('address',wan);self.assertNotIn('gateway',wan)
    def test_unbound_dhcp_does_not_require_manual_address_or_gateway(self):
        inv=fixture();inv['ip/address']=[x for x in inv['ip/address'] if x['interface']!='ether2'];inv['ip/route']=[x for x in inv['ip/route'] if x['.id']!='*2'];inv['ip/dhcp-client']=[{'interface':'ether2','status':'searching'}];inv['candidates']=candidates(inv)
        next(x for x in inv['candidates'] if x['interface']=='ether2')['priority']=2
        cfg=build(inv);self.assertEqual(next(x for x in cfg['wans'] if x['interface']=='ether2')['kind'],'dhcp')
    def test_dynamic_defaults_only_adopted_for_selected_provider_clients(self):
        inv=fixture();inv['ip/dhcp-client']=[{'interface':'ether2'}];inv['ip/route'][1].update(dynamic='true',dhcp='true',**{'vrf-interface':'ether2'});inv['candidates']=candidates(inv)
        self.assertEqual(len(build(inv).get('takeover_routes',[])),1)
        with self.assertRaisesRegex(ValueError,'не принадлежит'):build(inv,choices(inv)[:1])
    def test_disconnected_pppoe_logical_interface_can_be_selected(self):
        inv=fixture();inv['interface'].append({'name':'pppoe-isp','type':'pppoe-out','running':'false'});inv['interface/pppoe-client']=[{'name':'pppoe-isp','interface':'ether2'}];inv['candidates']=candidates(inv)
        next(x for x in inv['candidates'] if x['interface']=='pppoe-isp')['priority']=3
        cfg=build(inv);wan=next(x for x in cfg['wans'] if x['interface']=='pppoe-isp')
        self.assertEqual(wan['kind'],'pppoe');self.assertNotIn('address',wan);self.assertNotIn('gateway',wan)
    def test_disabled_interface_rejected(self):
        inv=fixture();inv['interface'][1]['disabled']='true';inv['candidates']=candidates(inv)
        with self.assertRaisesRegex(ValueError,'выключен'):build(inv)
    def test_unselected_live_default_route_rejected(self):
        inv=fixture()
        with self.assertRaisesRegex(ValueError,'невыбранный'):build(inv,choices(inv)[:1])
    def test_fasttrack_explicit_in_plan(self):
        inv=fixture();inv['ip/firewall/filter']=[{'.id':'*4','chain':'forward','action':'fasttrack-connection'}]
        self.assertEqual(build(inv)['disable_fasttrack'][0]['.id'],'*4')
    def test_routing_marks_not_silently_overwritten(self):
        inv=fixture();inv['ip/firewall/mangle']=[{'action':'mark-routing'}]
        with self.assertRaisesRegex(ValueError,'mark-routing'):build(inv)
    def test_managed_mangle_does_not_block_reconfiguration(self):
        inv=fixture();inv['ip/firewall/mangle']=[{'action':'mark-routing','comment':'sdwan:v1:reply:sdwan-output:wan1'}]
        self.assertEqual(len(build(inv)['wans']),2)
    def test_discovery_projection_preserves_ownership_and_rejects_foreign_marks(self):
        stored=fixture()
        stored['ip/firewall/mangle']=[{'action':'mark-routing','comment':'sdwan:v1:reply:sdwan-output:wan1'}]
        class ProjectedRouter:
            def call(self,path,data=None,method=None):
                rows=stored.get(path.removesuffix('/print'),[])
                if path=='system/identity/print':rows=[stored['identity']]
                if path=='system/resource/print':rows=[stored['resource']]
                fields=set(data['.proplist'].split(','))
                return [{k:v for k,v in row.items() if k in fields} for row in rows]
        self.assertEqual(len(build(discover(ProjectedRouter()))['wans']),2)
        stored['ip/firewall/mangle'].append({'action':'mark-connection','comment':'operator rule'})
        with self.assertRaisesRegex(ValueError,'mark-routing'):build(discover(ProjectedRouter()))
    def test_foreign_connection_marks_not_silently_overwritten(self):
        inv=fixture();inv['ip/firewall/mangle']=[{'action':'mark-connection'}]
        with self.assertRaisesRegex(ValueError,'mark-connection'):build(inv)
    def test_notrack_rejected_before_connection_mark_configuration(self):
        inv=fixture();inv['ip/firewall/raw']=[{'action':'notrack'}]
        with self.assertRaisesRegex(ValueError,'notrack'):build(inv)
    def test_active_policies_and_profiles_preserved(self):
        cfg=load(ROOT/'config/sdwan.json');inv=fixture();inv['active_config']=cfg;inv['interface']=[{'name':w['interface'],'type':'ether'} for w in cfg['wans']];inv['ip/address']=[{'interface':w['interface'],'address':w['address']+'/30'} for w in cfg['wans']];inv['ip/route']=[];inv['candidates']=candidates(inv)
        result=generate(inv,choices(inv));self.assertEqual(result['policies'][1:],cfg['policies'][1:]);self.assertEqual(result['sla_profiles'],cfg['sla_profiles'])
    def test_required_critical_inventory_error_propagates(self):
        class Restricted:
            def call(self,path,*args):
                if path.startswith('system/'):return [{'name':'r','version':'7.24.5'}]
                raise RuntimeError('permission denied')
        with self.assertRaisesRegex(RuntimeError,'permission denied'):discover(Restricted())
    def test_unreadable_routing_conflicts_block_generation(self):
        inv=fixture();inv['unreadable_paths']=['ip/firewall/mangle']
        with self.assertRaisesRegex(ValueError,'Недостаточно данных'):build(inv)
    def test_unreadable_active_config_cannot_be_replaced(self):
        inv=fixture();inv['active_config_error']='permission denied';inv['ip/route'][0]['comment']='sdwan:v1:route:default:wan1'
        with self.assertRaisesRegex(ValueError,'действующий SD-WAN'):build(inv)
    def test_new_wan_name_does_not_collide_with_retained_names(self):
        cfg=load(ROOT/'config/sdwan.json');inv=fixture();inv['active_config']=cfg
        inv['interface']=[{'name':w['interface'],'type':'ether'} for w in cfg['wans']]+[{'name':'new-wan','type':'ether'}]
        inv['ip/address']=[{'interface':w['interface'],'address':w['address']+'/30'} for w in cfg['wans']]+[{'interface':'new-wan','address':'203.0.113.2/30'}]
        inv['ip/route']=[{'.id':'*9','dst-address':'0.0.0.0/0','gateway':'203.0.113.1'}];inv['candidates']=candidates(inv)
        chosen=choices(inv)
        for c in chosen:c['priority']=1 if c['interface']=='new-wan' else c['priority']+1
        result=build(inv,chosen)
        self.assertEqual([w['name'] for w in result['wans']],['wan4','wan1','wan2','wan3'])
    def test_inventory_only_reads_and_uses_no_password_properties(self):
        class Recorder:
            def __init__(self):self.calls=[]
            def call(self,path,data=None,method=None):
                self.calls.append((path,data,method))
                if path=='system/identity/print':return [{'name':'r'}]
                if path=='system/resource/print':return [{'version':'7.24.5'}]
                return []
        r=Recorder();discover(r)
        self.assertTrue(all(path.endswith('/print') for path,_,_ in r.calls))
        self.assertTrue(all('password' not in str(data) for _,data,_ in r.calls))

if __name__=='__main__':unittest.main()
