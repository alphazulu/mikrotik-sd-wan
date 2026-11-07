"""Explicit, bounded API snapshots for GUI diagnostics; never a policy loop."""
import ipaddress
MAX_ROWS=4096

def snapshot(router,names=None):
 """Return list-name -> IPv4 prefixes, or None when membership is unavailable.

 Address List matching itself always remains in RouterOS. A missing/truncated
 snapshot must never be interpreted as an empty list by the flow explainer.
 """
 names=None if names is None else sorted(set(names))
 if names==[]:return {}
 queries=[] if names is None else ['list='+name for name in names]+['#|']*(len(names)-1)
 count=router.call('ip/firewall/address-list/print',{'count-only':'yes','.query':queries},'POST')
 if not isinstance(count,dict) or not str(count.get('ret','')).isdigit():return None
 if int(count['ret'])>MAX_ROWS:return None
 rows=router.call('ip/firewall/address-list/print',{'.proplist':'list,address,disabled,invalid','.query':queries},'POST')
 if not isinstance(rows,list) or len(rows)>MAX_ROWS:return None
 result={} if names is None else {name:[] for name in names}
 for row in rows:
  name=row.get('list','')
  if not name:continue
  result.setdefault(name,[])
  if row.get('disabled') in (True,'true','yes') or row.get('invalid') in (True,'true','yes'):continue
  try:prefix=str(ipaddress.IPv4Network(row['address'],strict=False))
  except (ValueError,KeyError):continue # DNS parent/IPv6; resolved A children count
  if prefix not in result[name]:result[name].append(prefix)
 return result
