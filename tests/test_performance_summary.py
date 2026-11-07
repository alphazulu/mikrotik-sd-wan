"""Keep incomplete observations, overload and resource accounting explicit."""
import unittest
from tools.performance_summary import observations,summarize


class SummaryTests(unittest.TestCase):
    def test_short_smoke_never_claims_complete_comparison(self):
        result=summarize({'pass':True,'seconds':5,'repeats':1,'cleanup':{'pass':True},'runs':[]},'abc')
        self.assertFalse(result['comparison_complete'])

    def test_missing_resources_remain_unknown(self):
        result=observations({'mode':'native','label':'missing','iperf':{'error':'connection closed'}})
        self.assertIsNone(result['router_cpu_mean_percent'])
        self.assertIsNone(result['container_cgroup_peak_bytes'])
        self.assertEqual(result['iperf_error'],'connection closed')
        self.assertFalse(result['measurement_complete'])

    def test_udp_loss_and_sla_changes_are_not_hidden(self):
        samples=[{'resource':{'cpu-load':str(cpu),'free-memory':str(memory),'write-sect-total':str(writes)},
                  'sdwan':{'uptime_seconds':tick,'states':{'default/wan1':{'state':quality}},'selected':{'client':selected}},
                  'container':[{'name':'sdwan-container-controller','memory-current':'2097152'}]}
                 for cpu,memory,writes,tick,quality,selected in [(80,4000,10,2,'healthy','wan1'),(100,3000,20,4,'down','none')]]
        result=observations({'mode':'container','label':'udp-64-50M-1','router_samples':samples,'iperf':{'end':{'sum':{'bits_per_second':1000000,'lost_percent':90}}}})
        self.assertEqual(result['router_cpu_mean_percent'],90)
        self.assertEqual(result['disk_sectors_delta'],10)
        self.assertEqual(result['quality_sample_counts']['default/wan1'],{'healthy':1,'down':1})
        self.assertEqual(result['rates']['sum']['lost_percent'],90)
        self.assertEqual(result['selection_sample_counts']['client']['none'],1)


if __name__=='__main__':unittest.main()
