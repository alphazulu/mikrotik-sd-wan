"""Private acceptance helpers for the protocol-2 RAM inbox; no file fallback."""
from sdwan.container_runtime import check_intent_inbox

def read_intent(router):
    rows=check_intent_inbox(router)
    if not rows:return ''
    values=router.call('ip/firewall/address-list/print',{
        '.proplist':'.id,list,address,dynamic,disabled,comment',
        '.query':['list=sdwan-container-intent']},'POST')
    # Recheck the returned shape too: the inbox may have changed between reads.
    if len(values)!=1 or any(values[0].get(k)!=rows[0].get(k) for k in ('.id','list','address','dynamic','disabled')):
        raise ValueError('RAM intent inbox changed during observation')
    return values[0].get('comment','')

def write_intent(router,text):
    """Inject a test intent only into an existing, owned dynamic inbox."""
    rows=check_intent_inbox(router)
    if len(rows)!=1:raise ValueError('RAM intent inbox is missing')
    if not text or len(text.encode())>32768:raise ValueError('RAM intent length')
    router.call('ip/firewall/address-list/'+rows[0]['.id'],{'comment':text},'PATCH')
