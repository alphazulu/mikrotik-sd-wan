"""Complete cancelled USB requests so their IDs can safely be reused."""
import unittest

import test_emu as harness
from lte_rndis_emu.usbredir import BULK, CANCEL, ST_CANCELLED, ST_SUCCESS, parse_bulk


class CancelTests(unittest.TestCase):
    def link(self, profile="hilink"):
        link = harness.Link(profile=profile)
        bringup = harness.UsbRedirTests()
        bringup.session_configure(link)
        bringup._bring_up(link)
        return link

    def cancel(self, link, ident):
        link.session.receive(link.guest.pack(CANCEL, ident, b""))
        return link.pump()

    def test_cancelled_in_request_has_matching_completion_and_reusable_64bit_id(self):
        link = self.link()
        ident = 0x100000005
        self.assertEqual(link.bulk_in(ident, 0x82, 1664), [])
        replies = self.cancel(link, ident)
        self.assertEqual(len(replies), 1)
        kind, request, payload = replies[0]
        self.assertEqual((kind, request), (BULK, ident))
        self.assertEqual(parse_bulk(payload, link.guest.negotiated), (0x82, ST_CANCELLED, b""))
        self.assertFalse(link.session.pending)
        self.assertEqual(link.bulk_in(ident, 0x82, 1664), [])
        frame = b"return path after reboot" + bytes(40)
        link.session.deliver_rx(frame)
        replies = link.pump()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][:2], (BULK, ident))
        self.assertEqual(parse_bulk(replies[0][2], link.guest.negotiated), (0x82, ST_SUCCESS, harness.wrap_ethernet(frame)))

    def test_cancel_leaves_other_pending_requests_and_incoming_data_intact(self):
        link = self.link()
        self.assertEqual(link.bulk_in(801, 0x82, 1664), [])
        self.assertEqual(link.bulk_in(802, 0x82, 1664), [])
        replies = self.cancel(link, 801)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][:2], (BULK, 801))
        self.assertEqual(list(link.session.pending), [(802, 0x82, 1664)])
        frame = bytes(60)
        link.session.deliver_rx(frame)
        replies = link.pump()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][:2], (BULK, 802))
        self.assertEqual(parse_bulk(replies[0][2], link.guest.negotiated), (0x82, ST_SUCCESS, harness.wrap_ethernet(frame)))

    def test_unknown_or_already_completed_cancel_does_not_double_complete(self):
        link = self.link()
        self.assertEqual(self.cancel(link, 900), [])
        self.assertEqual(link.bulk_in(901, 0x82, 1664), [])
        link.session.deliver_rx(bytes(60))
        self.assertEqual(len(link.pump()), 1)
        self.assertEqual(self.cancel(link, 901), [])

    def test_cancel_completes_at_endpoint_without_touching_network_request(self):
        link = self.link(profile="at")
        self.assertEqual(link.bulk_in(950, 0x84, 512), [])
        self.assertEqual(link.bulk_in(951, 0x82, 1664), [])
        replies = self.cancel(link, 950)
        self.assertEqual(len(replies), 1)
        self.assertEqual(parse_bulk(replies[0][2], link.guest.negotiated), (0x84, ST_CANCELLED, b""))
        self.assertEqual(list(link.session.pending), [(951, 0x82, 1664)])


if __name__ == "__main__":
    unittest.main()
