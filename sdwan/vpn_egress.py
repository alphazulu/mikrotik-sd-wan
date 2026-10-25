"""Opt-in external VPN egress contract; no credentials or runtime policy loop here."""
import ipaddress
import re
from .overlay import public_key

TYPES=('wireguard','l2tp','sstp','openvpn')
MENUS={'l2tp':'interface/l2tp-client','sstp':'interface/sstp-client','openvpn':'interface/ovpn-client'}
PPP_PROPERTIES='.id,name,disabled,running,connect-to,port,protocol,add-default-route,route-nopull,mode,use-ipsec,http-proxy'
WG_PROPERTIES='.id,name,disabled,running,listen-port,public-key'
PEER_PROPERTIES='.id,interface,public-key,disabled,endpoint-address,endpoint-port,current-endpoint-address,current-endpoint-port,allowed-address'

def enabled(cfg):return cfg.get('vpn_egress',{}).get('enabled',False)
def vpn_wans(cfg):return [w for w in cfg.get('wans',[]) if w.get('kind')=='vpn']
def menu(kind):return MENUS[kind]
def yes(value):return value in (True,'true','yes','1')

def validate(cfg):
 setting=cfg.get('vpn_egress',{})
 if not isinstance(setting,dict) or setting.keys()-{'enabled','masquerade','allow_selected_forward'}:raise ValueError('vpn_egress accepts enabled, masquerade and allow_selected_forward only')
 for field in setting:
  if type(setting[field]) is not bool:raise ValueError('vpn_egress.'+field+' must be boolean')
 links=vpn_wans(cfg)
 for w in cfg.get('wans',[]):
  if w.get('kind')!='vpn' and any(f in w for f in ('vpn_type','vpn_endpoint','vpn_listen_port','vpn_peer_public_key','underlays')):raise ValueError('VPN metadata belongs only to VPN WANs')
 if links and not enabled(cfg):raise ValueError('VPN channels require explicit vpn_egress.enabled=true')
 if not enabled(cfg):return cfg
 physical={w['name'] for w in cfg['wans'] if w.get('kind')!='vpn'}
 if not physical:raise ValueError('VPN egress requires physical underlay WANs')
 default=next(p for p in cfg['policies'] if not p['source'])
 if not set(default['wans'])<=physical:raise ValueError('Default Internet policy must use physical WANs; VPN exits belong in destination policies')
 bindings={};ports=set()
 for wan in links:
  kind=wan.get('vpn_type')
  if kind not in TYPES:raise ValueError('VPN type must be wireguard, l2tp, sstp or openvpn')
  parents=wan.get('underlays')
  if not isinstance(parents,list) or not parents or any(not isinstance(p,str) for p in parents) or len(set(parents))!=len(parents) or not set(parents)<=physical:raise ValueError('VPN underlays must be distinct physical WAN names')
  endpoint=wan.get('vpn_endpoint')
  if not isinstance(endpoint,str) or not 1<=len(endpoint)<=253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',p) for p in endpoint.split('.')):raise ValueError('VPN endpoint must be an IPv4 address or DNS hostname')
  try:ip=ipaddress.IPv4Address(endpoint)
  except ValueError:ip=None
  if ip is not None:
   if ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip)==0xffffffff:raise ValueError('Invalid VPN endpoint address')
   from .overlay import effective_networks
   if any(ip in ipaddress.IPv4Network(n) for n in effective_networks(cfg)):raise ValueError('VPN endpoint must not recurse into local/branch bypass networks')
  if kind=='wireguard':
   public_key(wan.get('vpn_peer_public_key'))
   port=wan.get('vpn_listen_port')
   if type(port) is not int or not 1024<=port<=65535 or port in ports:raise ValueError('VPN WireGuard requires a distinct local listen port')
   ports.add(port)
  elif 'vpn_peer_public_key' in wan or 'vpn_listen_port' in wan:raise ValueError('WireGuard identity fields are not PPP VPN settings')
  # A shared PPP/IPsec endpoint cannot be pinned to incompatible parents.
  key=(kind,endpoint) if kind!='wireguard' else ('wireguard',wan['interface'])
  if key in bindings and bindings[key]!=parents:raise ValueError('Shared VPN endpoint requires the same underlay order')
  bindings[key]=parents
  if any(t.get('wan')==wan['name'] or t.get('listen_port')==wan.get('vpn_listen_port') or 'sdwan-wg-'+t.get('name','')==wan['interface'] for t in cfg.get('overlay',{}).get('tunnels',[])):raise ValueError('Branch overlay and external VPN identities/underlays must be distinct')
 for policy in cfg['policies']:
  if any(name not in physical for name in policy['wans']) and not policy.get('destination_list'):raise ValueError('VPN egress policy requires a destination_list selector')
 return cfg

def binding(router,wan):
 """Read only public interface/endpoint/routing metadata, never secrets."""
 kind=wan['vpn_type'];iface=wan['interface']
 if kind=='wireguard':
  matches=router.call('interface/wireguard/print',{'.proplist':WG_PROPERTIES,'.query':['name='+iface]},'POST')
  peers=router.call('interface/wireguard/peers/print',{'.proplist':PEER_PROPERTIES,'.query':['interface='+iface]},'POST')
  peers=[p for p in peers if not yes(p.get('disabled'))]
  if len(matches)!=1 or len(peers)!=1:raise ValueError('VPN exit requires one WireGuard interface and one enabled exit peer')
  row=matches[0];peer=peers[0]
  allowed=peer.get('allowed-address',[]);allowed=allowed.split(',') if isinstance(allowed,str) else allowed
  if '0.0.0.0/0' not in allowed:raise ValueError('WireGuard exit peer must allow 0.0.0.0/0; branch peers are not Internet exits')
  if peer.get('public-key')!=wan['vpn_peer_public_key'] or int(row.get('listen-port',0))!=wan['vpn_listen_port']:raise ValueError('WireGuard exit identity/listen port changed; rediscover')
  if peer.get('endpoint-address')!=wan['vpn_endpoint']:raise ValueError('WireGuard exit endpoint changed; rediscover')
  return {'menu':'interface/wireguard','id':row['.id'],'peer_id':peer['.id'],'endpoint':peer['endpoint-address'],'endpoint_port':int(peer.get('endpoint-port',0)),'protocol':'udp','listen_port':int(row['listen-port'])}
 rows=router.call(menu(kind)+'/print',{'.proplist':PPP_PROPERTIES,'.query':['name='+iface]},'POST')
 if len(rows)!=1:raise ValueError('Missing/ambiguous '+kind+' VPN client')
 row=rows[0]
 if row.get('connect-to')!=wan['vpn_endpoint']:raise ValueError('PPP VPN endpoint changed; rediscover')
 if kind=='openvpn' and row.get('mode','ip')!='ip':raise ValueError('OpenVPN egress must use routed IP mode')
 if kind=='sstp' and row.get('http-proxy','') not in ('','::','0.0.0.0','none'):raise ValueError('SSTP HTTP proxy transport requires a separate validated configuration; direct SSTP exits only')
 return {'menu':menu(kind),'id':row['.id'],'endpoint':row['connect-to'],'endpoint_port':int(row.get('port',1701 if kind=='l2tp' else 443 if kind=='sstp' else 1194)),'protocol':'udp' if kind=='l2tp' else row.get('protocol','tcp'),'add_default_route':row.get('add-default-route'),'route_nopull':row.get('route-nopull'),'ipsec':row.get('use-ipsec','no')}


def inventory(router):
 """Optional public metadata for the GUI; caller reports unavailable menus."""
 result=[]
 for kind,path,properties in [('wireguard','interface/wireguard',WG_PROPERTIES)]+[(k,p,PPP_PROPERTIES) for k,p in MENUS.items()]:
  rows=router.call(path+'/print',{'.proplist':properties},'POST')
  if len(rows)>256:raise ValueError('VPN interface inventory exceeds 256 interfaces per protocol')
  peers=router.call('interface/wireguard/peers/print',{'.proplist':PEER_PROPERTIES},'POST') if kind=='wireguard' else []
  if len(peers)>1024:raise ValueError('VPN peer inventory exceeds 1024 peers')
  for row in rows:
   if yes(row.get('disabled')):continue
   item={'interface':row['name'],'vpn_type':kind,'running':yes(row.get('running'))}
   if kind=='wireguard':
    exits=[p for p in peers if p.get('interface')==row['name'] and not yes(p.get('disabled'))]
    if len(exits)!=1:continue
    peer=exits[0];allowed=peer.get('allowed-address',[]);allowed=allowed.split(',') if isinstance(allowed,str) else allowed
    if '0.0.0.0/0' not in allowed:continue
    item.update(vpn_endpoint=peer.get('endpoint-address',''),vpn_listen_port=int(row.get('listen-port',0)),vpn_peer_public_key=peer.get('public-key',''))
   else:
    if kind=='openvpn' and row.get('mode','ip')!='ip':continue
    item['vpn_endpoint']=row.get('connect-to','')
    if kind=='sstp' and row.get('http-proxy','') not in ('','::','0.0.0.0','none'):item['unsupported_reason']='SSTP через HTTP proxy пока не поддерживается'
   if item['vpn_endpoint']:result.append(item)
 return result


def configure(cfg,link,*,name,address_list,underlays,backups,masquerade=False,allow_selected_forward=False,routes=()):
 """Atomic GUI transformation. Keep credentials and dynamic addresses external."""
 import copy
 from .config import validate as validate_config
 from .policies import ordered
 result=copy.deepcopy(cfg)
 physical=[w['name'] for w in result['wans'] if w.get('kind')!='vpn']
 if not physical:raise ValueError('Сначала выберите физические WAN')
 existing=next((w for w in result['wans'] if w['interface']==link['interface']),None)
 if existing and (existing.get('kind')!='vpn' or existing['name']!=name):raise ValueError('Интерфейс уже назначен другому каналу')
 if any(w['name']==name and w is not existing for w in result['wans']):raise ValueError('Имя канала уже занято')
 w=copy.deepcopy(existing or result['wans'][0]);w.pop('address',None);w.pop('gateway',None);w.pop('apn_profile',None)
 for field in ('vpn_type','vpn_endpoint','vpn_listen_port','vpn_peer_public_key'):w.pop(field,None)
 w.update({k:v for k,v in link.items() if k in ('interface','vpn_type','vpn_endpoint','vpn_listen_port','vpn_peer_public_key')})
 w.update(name=name,kind='vpn',probe_table='sdwan-probe-'+name,underlays=list(underlays),admin_state='enabled')
 if existing:result['wans'][result['wans'].index(existing)]=w
 else:result['wans'].append(w)
 policy_name='vpn-'+name
 prior=next((p for p in result['policies'] if p['name']==policy_name),None)
 if prior:
  # Updating transport/order must not erase manually refined client selectors,
  # SLA thresholds, table, priority or degradation preference.
  prior.update(destination_list=address_list,wans=[name]+list(backups))
  prior.pop('destination_group',None)
  if len(prior['wans'])>1:prior['mode']='prefer'
 else:
  others=[p for p in ordered(result) if p['source']]
  # A newly added opaque selector needs explicit, unambiguous precedence.
  for rank,p in enumerate(others,2):p['priority']=rank*10
  default=next(p for p in result['policies'] if not p['source'])
  policy=dict(name=policy_name,source='0.0.0.0/0',table='sdwan-'+policy_name,profile=default['profile'],mode='prefer',wans=[name]+list(backups),allow_degraded=False,priority=10,destination_list=address_list)
  result['policies']=[default,policy]+others
 result['vpn_egress']={'enabled':True,'masquerade':masquerade,'allow_selected_forward':allow_selected_forward}
 from .wan import interface_route
 selectors={row['.id']:row for row in result.get('takeover_routes',[])}
 for row in routes:
  if row.get('dst-address')=='0.0.0.0/0' and row.get('routing-table','main')=='main' and not yes(row.get('dynamic')) and not row.get('comment','').startswith('sdwan:') and interface_route(row,link['interface']):
   selectors[row['.id']]={'.id':row['.id'],'dst-address':'0.0.0.0/0','routing-table':'main','gateway':row['gateway']}
 if selectors:result['takeover_routes']=list(selectors.values())
 return validate_config(result)


def validate_pushed_defaults(routes,cfg):
 """Only a declared OpenVPN client may supply dynamic main def1 routes.

 Its pushed routes are suppressed/reconnected during protected native adoption.
 Other active split defaults would bypass the SLA-governed main policy.
 """
 from .wan import interface_route
 exits=[w for w in vpn_wans(cfg) if w.get('vpn_type')=='openvpn']
 for row in routes:
  if row.get('dst-address') not in ('0.0.0.0/1','128.0.0.0/1') or row.get('routing-table','main')!='main' or yes(row.get('disabled')):continue
  if not (yes(row.get('dynamic')) and yes(row.get('vpn')) and any(interface_route(row,w['interface']) for w in exits)):
   raise ValueError('Unadopted split default would bypass SD-WAN SLA: '+row.get('.id','')+'; declare the existing OpenVPN exit or reconcile this route first')


def disable(cfg):
 """Turn off optional VPN egress, preserving physical backups and other scopes."""
 import copy
 from .config import validate as validate_config
 result=copy.deepcopy(cfg);physical={w['name'] for w in result['wans'] if w.get('kind')!='vpn'}
 result['wans']=[w for w in result['wans'] if w['name'] in physical]
 policies=[]
 for policy in result['policies']:
  policy['wans']=[name for name in policy['wans'] if name in physical]
  if policy['wans']:policies.append(policy)
 result['policies']=policies;result['vpn_egress']={'enabled':False}
 return validate_config(result)
