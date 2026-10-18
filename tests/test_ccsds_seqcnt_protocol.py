# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for CCSDS Sequence Count Protocol."""

from openc3.packets.packet import Packet

from ccsds_seqcnt_protocol import CcsdsSeqcntProtocol


def _make_packet(field_name: str = "CCSDS_SEQ_CNT") -> Packet:
    packet = Packet("TGT", "PKT")
    packet.append_item(field_name, 14, "UINT")
    return packet


class TestCcsdsSeqcntProtocol:
    """Test suite for CCSDS Sequence Count Protocol."""

    def test_starts_at_zero(self):
        protocol = CcsdsSeqcntProtocol()
        packet = _make_packet()
        protocol.write_packet(packet)
        assert packet.read("CCSDS_SEQ_CNT") == 0

    def test_increments_per_packet(self):
        protocol = CcsdsSeqcntProtocol()
        for expected in range(5):
            packet = _make_packet()
            protocol.write_packet(packet)
            assert packet.read("CCSDS_SEQ_CNT") == expected

    def test_returns_same_packet(self):
        protocol = CcsdsSeqcntProtocol()
        packet = _make_packet()
        result = protocol.write_packet(packet)
        assert result is packet

    def test_custom_field_name(self):
        protocol = CcsdsSeqcntProtocol(field_name="MY_SEQ")
        packet = _make_packet(field_name="MY_SEQ")
        protocol.write_packet(packet)
        protocol.write_packet(packet)
        assert packet.read("MY_SEQ") == 1

    def test_independent_protocol_instances(self):
        protocol_a = CcsdsSeqcntProtocol()
        protocol_b = CcsdsSeqcntProtocol()

        packet_a = _make_packet()
        protocol_a.write_packet(packet_a)
        protocol_a.write_packet(packet_a)
        protocol_a.write_packet(packet_a)
        assert packet_a.read("CCSDS_SEQ_CNT") == 2

        packet_b = _make_packet()
        protocol_b.write_packet(packet_b)
        assert packet_b.read("CCSDS_SEQ_CNT") == 0

    def test_counts_per_apid(self):
        # CCSDS sequence counts are per APID; F Prime's ApidManager checks each APID separately
        protocol = CcsdsSeqcntProtocol()

        def send(apid):
            packet = _make_packet()
            packet.append_item("CCSDS_APID", 11, "UINT")
            packet.write("CCSDS_APID", apid)
            protocol.write_packet(packet)
            return packet.read("CCSDS_SEQ_CNT")

        assert [send(0), send(3), send(3), send(0), send(3)] == [0, 0, 1, 1, 2]

    def test_wraps_at_14_bits(self):
        protocol = CcsdsSeqcntProtocol()
        protocol.seq_num = 0x3FFF
        packet = _make_packet()
        protocol.write_packet(packet)
        assert packet.read("CCSDS_SEQ_CNT") == 0x3FFF
        protocol.write_packet(packet)
        assert packet.read("CCSDS_SEQ_CNT") == 0
