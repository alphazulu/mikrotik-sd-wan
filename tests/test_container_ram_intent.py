from unittest.mock import patch
import copy
import unittest
from sdwan.container_runtime import check_intent_inbox

class Router:
    def __init__(self,rows):self.rows=rows;self.calls=[]
    def call(self,path,data,method):self.calls.append((path,data,method));return self.rows

class RAMInboxTests(unittest.TestCase):
    def test_missing_inbox_and_one_owned_dynamic_entry_are_ready_without_creation(self):
        for rows in ([],[{'.id':'*7','list':'sdwan-container-intent','address':'127.0.0.1','dynamic':'true','disabled':'false'}]):
            r=Router(rows);self.assertEqual(check_intent_inbox(r),rows)
            self.assertEqual(r.calls,[('ip/firewall/address-list/print',{'.proplist':'.id,list,address,dynamic,disabled','.query':['list=sdwan-container-intent']},'POST')])
    def test_static_duplicate_foreign_and_missing_id_never_modified(self):
        base={'.id':'*7','list':'sdwan-container-intent','address':'127.0.0.1','dynamic':'true','disabled':'false'}
        cases=[[base,base]]
        for key,value in (('list','foreign'),('address','192.0.2.1'),('dynamic','false'),('disabled','true'),('.id','')):
            cases.append([{**base,key:value}])
        missing=copy.copy(base);del missing['.id'];cases.append([missing])
        for rows in cases:
            with self.subTest(rows=rows):
                r=Router(rows)
                with self.assertRaisesRegex(ValueError,'RAM intent inbox'):check_intent_inbox(r)
                self.assertEqual(len(r.calls),1);self.assertTrue(r.calls[0][0].endswith('/print'))

class RAMAcceptanceHelpersTests(unittest.TestCase):
    def test_read_observes_empty_or_owned_comment_without_file_calls(self):
        from tools.container_intent import read_intent
        base={'.id':'*7','list':'sdwan-container-intent','address':'127.0.0.1','dynamic':'true','disabled':'false'}
        for first,second,expected in (([],[],''),([base],[dict(base,comment='payload')],'payload')):
            class ReadRouter:
                def __init__(self):self.calls=[]
                def call(self,path,data,method):
                    self.calls.append(path);return first if len(self.calls)==1 else second
            r=ReadRouter();self.assertEqual(read_intent(r),expected)
            self.assertTrue(all(path=='ip/firewall/address-list/print' for path in r.calls))
    def test_read_rechecks_snapshot_and_injection_never_uses_file_fallback(self):
        from tools.container_intent import read_intent,write_intent
        base={'.id':'*7','list':'sdwan-container-intent','address':'127.0.0.1','dynamic':'true','disabled':'false'}
        class Changed:
            def __init__(self):self.calls=[]
            def call(self,path,data,method):
                self.calls.append((path,data,method));return [base] if len(self.calls)==1 else []
        with self.assertRaisesRegex(ValueError,'changed'):read_intent(Changed())
        with self.assertRaisesRegex(ValueError,'missing'):write_intent(Router([]),'payload')
        for text in ('','я'*16385):
            r=Router([base])
            with self.assertRaisesRegex(ValueError,'length'):write_intent(r,text)
            self.assertEqual(len(r.calls),1)
        r=Router([base]);write_intent(r,'payload');self.assertEqual(r.calls[-1],('ip/firewall/address-list/*7',{'comment':'payload'},'PATCH'))
