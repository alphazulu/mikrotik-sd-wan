"""Command construction only: never start or stop existing lab nodes."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('sdwan_lte_lab_test', Path(__file__).resolve().parents[2] / 'lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

class LabOptInTests(unittest.TestCase):
    def test_disabled_default_and_only_edge_changes_when_enabled(self):
        with patch.dict(os.environ, {'LTE_RNDIS_EMU': '0'}):
            original = {name: lab.node_command(name, 'kvm') for name in lab.NODES}
        with patch.dict(os.environ, {'LTE_RNDIS_EMU': '1'}), patch('lte_rndis_emu.emulator.qemu_chardev', return_value='socket,id=lteusb,host=127.0.0.1,port=24320'):
            enabled = {name: lab.node_command(name, 'kvm') for name in lab.NODES}
        for name in lab.NODES:
            if name == 'edge':
                self.assertEqual(enabled[name][:len(original[name])], original[name])
                self.assertIn('usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0', enabled[name])
            else:
                self.assertEqual(enabled[name], original[name])
