import copy,hashlib,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sdwan_lab.dut_fixture import Fixture,load_config,topology_config
from sdwan_lab.dut_metrics import GeneratorSampler,receiver_metrics,summarize
from sdwan_lab.iperf_runner import result as iperf_result

ROOT=Path(__file__).resolve().parents[2]

class ConfigurationTests(unittest.TestCase):
    def test_private_paths_are_relative_to_config_and_no_remote_router_URL_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'input.json';cfg={'source':'source','base_disk':'base.qcow2','base_sha256':'a'*64,'credentials':'private.json','identity':'lab-dut','artifacts':'images','variants':'plan'};path.write_text(json.dumps(cfg))
            value=load_config(path);self.assertEqual(value['base_disk'],Path(root)/'base.qcow2');self.assertEqual(value['port_base'],25800);self.assertEqual(value['data_nic'],'virtio-net-pci')
            for changes in [{'api_url':'api://192.0.2.1'},{'port_base':True},{'base_sha256':'unknown'},{'tools':{'shell':'bash'}}]:
                path.write_text(json.dumps(dict(cfg,**changes)))
                with self.subTest(changes=changes),self.assertRaises(ValueError):load_config(path)
    def test_only_the_declared_synthetic_topology_is_accepted(self):
        config=json.loads((ROOT/'config/sdwan.json').read_text())
        for i,w in enumerate(config['wans'],1):w['interface']='wan'+str(i)
        topology_config(config)
        for mutation in ['kind','address','local','priority','probe']:
            bad=copy.deepcopy(config)
            if mutation=='kind':bad['wans'][0]['kind']='vpn'
            if mutation=='address':bad['wans'][0]['address']='192.0.2.1'
            if mutation=='local':bad['local_networks']=[]
            if mutation=='priority':bad['policies'][2]['wans'][0]='wan1'
            if mutation=='probe':bad['wans'][0]['probes'][0]['host']='203.0.113.1'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):topology_config(bad)
    def test_full_run_gate_precedes_adapter_import_and_workspace_creation(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);marker=root/'imported';adapter=root/'adapter.py';adapter.write_text('from pathlib import Path\nPath('+repr(str(marker))+').touch()\n')
            soak=root/'soak.json';soak.write_text('{"status":"running"}');workspace=root/'workspace'
            result=subprocess.run([sys.executable,str(ROOT/'labtools/comparison.py'),'run','--plan',str(root/'missing-plan.json'),'--adapter',str(adapter),'--adapter-config',str(root/'private.json'),'--soak-report',str(soak),'--workspace',str(workspace),'--run-id','blocked'],capture_output=True,text=True,timeout=3)
            self.assertNotEqual(result.returncode,0);self.assertIn('Full original48h',result.stderr);self.assertFalse(marker.exists());self.assertFalse(workspace.exists())

class MetricTests(unittest.TestCase):
    def test_stream_interval_clock_ignores_omitted_warmup_and_rejects_delivery_jitter(self):
        events=[{'event':'start','data':{'test_start':{}}},{'event':'interval','received_monotonic':100,'data':{'sum':{'omitted':True,'end':1}}}]
        events += [{'event':'interval','received_monotonic':200+i+.001,'data':{'sum':{'omitted':False,'start':i-1,'end':i}}} for i in range(1,4)]
        events += [{'event':'end','data':{'sum_received':{}}}]
        self.assertAlmostEqual(iperf_result(events)['measurement_origin_monotonic'],200.001)
        absolute=copy.deepcopy(events)
        for event in absolute:
            if event.get('event')=='interval' and not event['data']['sum']['omitted']:
                event['data']['sum']['start']+=120;event['data']['sum']['end']+=120
        self.assertAlmostEqual(iperf_result(absolute)['measurement_origin_monotonic'],200.001)
        delayed=copy.deepcopy(events);delayed[-2]['received_monotonic']+=.9
        self.assertAlmostEqual(iperf_result(delayed)['measurement_origin_monotonic'],200.001)
        self.assertGreater(iperf_result(delayed)['terminal_interval_delivery_delay_seconds'],.8)
        bad=copy.deepcopy(events);bad[2]['received_monotonic']+=1
        with self.assertRaisesRegex(ValueError,'jitter'):iperf_result(bad)
        with self.assertRaises(ValueError):iperf_result(events[:-1])
    def test_resources_use_the_measurement_window_and_preserve_unknown_write_counter(self):
        generator=SimpleNamespace(errors=[],rows=[]);router=SimpleNamespace(errors=[],rows=[])
        for i in range(30):
            stamp=i*.2;generator.rows.append({'monotonic':stamp,'process_cpu_percent':{'client':10 if 1<=stamp<5 else 99,'server':2},'host_steal_percent':{'cpu0':0}})
        for i in range(6):router.rows.append({'monotonic':i,'resource':{'cpu-load':'20' if 1<=i<5 else '99','free-memory':'1000000','write-sect-total':str(100+i)},'containers':[{'name':'sdwan-container-controller','running':'true','memory-current':'5000'}]})
        report=summarize(generator,router,1,4,'container');self.assertEqual(report['dut_cpu_mean_percent'],20);self.assertEqual(report['generator_cpu_p95_max_percent'],10);self.assertEqual(report['write_sectors_delta'],3);self.assertEqual(report['container_memory_peak_bytes'],5000)
        router.rows[3]['resource']['write-sect-total']='0';self.assertIsNone(summarize(generator,router,1,4,'container')['write_sectors_delta'])
        for row in router.rows:row['containers']=[]
        with self.assertRaisesRegex(ValueError,'memory'):summarize(generator,router,1,4,'container-web')
    def test_bidir_and_receiver_UDP_counters_have_explicit_units(self):
        data={'end':{'sum_received':{'bits_per_second':20},'sum_received_bidir_reverse':{'bits_per_second':18}}};value=receiver_metrics(data,{'kind':'tcp','direction':'bidir'});self.assertEqual(value['receiver_rate'],38);self.assertEqual(value['rate_unit'],'bps')
        value=receiver_metrics(data,{'kind':'tcp','direction':'reverse'});self.assertEqual(value['receiver_rate'],20);self.assertEqual(value['forward_receiver_bps'],0);self.assertEqual(value['reverse_receiver_bps'],20)
        value=receiver_metrics({'end':{'sum_received':{'seconds':10,'packets':100,'lost_packets':5,'lost_percent':5}}},{'kind':'udp','payload_bytes':64});self.assertEqual(value['receiver_rate'],9.5);self.assertEqual(value['rate_unit'],'pps')
    def test_generator_cpu_comes_from_its_process_not_the_entire_host(self):
        child=subprocess.Popen([sys.executable,'-c','import time\ne=time.monotonic()+1\nwhile time.monotonic()<e:pass'])
        try:
            with GeneratorSampler() as sampler:sampler.add(child.pid,'client');child.wait(timeout=3)
            self.assertFalse(sampler.errors);self.assertTrue(any(row['process_cpu_percent'].get('client',0)>0 for row in sampler.rows))
        finally:
            if child.poll() is None:child.kill();child.wait()

class RestorationTests(unittest.TestCase):
    def test_container_image_replacement_waits_for_actual_stop(self):
        fixture=Fixture.__new__(Fixture);fixture.router=object();base={'.id':'*1','comment':'sdwan-container:controller'}
        with patch('sdwan.container_runtime.read_container',side_effect=[dict(base,running='true'),dict(base,stopped='true')]) as read:
            self.assertEqual(fixture.stopped_container('*1')['stopped'],'true');self.assertEqual(read.call_count,2)
    def test_container_identity_change_during_stop_is_not_adopted(self):
        fixture=Fixture.__new__(Fixture);fixture.router=object()
        for row in [None,{'.id':'*2','comment':'sdwan-container:controller','stopped':'true'},{'.id':'*1','comment':'foreign','stopped':'true'}]:
            with self.subTest(row=row),patch('sdwan.container_runtime.read_container',return_value=row),self.assertRaisesRegex(ValueError,'identity changed'):fixture.stopped_container('*1')
    def test_changed_base_cannot_be_reported_as_verified_restore(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)/'base';base.write_bytes(b'before');snapshot={'backing_chain':[{'path':str(base),'sha256':hashlib.sha256(base.read_bytes()).hexdigest()}]};base.write_bytes(b'after')
            fixture=Fixture.__new__(Fixture);fixture.router=None;fixture.child=None;fixture.fds=[];fixture.run=SimpleNamespace(cleanup=lambda:True)
            report=fixture.restore(snapshot);self.assertFalse(report['verified']);self.assertFalse(report['pass']);self.assertTrue(report['resources_released'])
