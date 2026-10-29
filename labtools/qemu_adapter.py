"""comparison.py adapter entry point; configure it with a private JSON file."""
from sdwan_lab.dut_adapter import Adapter

_adapter=None

def configure(config_path,plan_path):
    global _adapter
    _adapter=Adapter(config_path,plan_path)

def preflight(*args):return _adapter.preflight(*args)
def snapshot(*args):return _adapter.snapshot(*args)
def set_mode(*args):return _adapter.set_mode(*args)
def measure(*args):return _adapter.measure(*args)
def switching(*args):return _adapter.switching(*args)
def restore(*args):return _adapter.restore(*args)
