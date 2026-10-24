# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Idle Space Packets (APID 0x7FF) must not reach packet identification."""

import struct

from ccsds_idle_filter_protocol import CcsdsIdleFilterProtocol


def space_packet(apid, size):
    return struct.pack(">HHH", apid, 0xC000, size - 7) + bytes(size - 6)


def test_idle_packet_is_dropped():
    protocol = CcsdsIdleFilterProtocol()
    assert protocol.read_data(space_packet(0x7FF, 100), {}) == ("STOP", {})


def test_other_packets_pass_through():
    protocol = CcsdsIdleFilterProtocol()
    packet = space_packet(0x001, 100)
    assert protocol.read_data(packet, {"a": 1}) == (packet, {"a": 1})


def test_apid_ignores_type_and_secondary_header_bits():
    # 0x1FFF: telecommand type bit and secondary header flag set, APID still 0x7FF
    protocol = CcsdsIdleFilterProtocol()
    assert protocol.read_data(space_packet(0x1FFF, 7), None) == ("STOP", None)


def test_short_data_passes_through():
    protocol = CcsdsIdleFilterProtocol()
    assert protocol.read_data(b"\x07", None) == (b"\x07", None)
