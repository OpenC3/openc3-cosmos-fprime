# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""TM frames as F Prime 4.4's ComAggregator builds them with packet spanning enabled.

Frames match plugin.txt: 1024 bytes, no sync pattern, no randomization, CRC16 trailer.
The aggregator idle-fills with Space Packets on APID 0x7FF (never 0xE0 bytes), and an idle
packet that does not fit the residual space spans into the next frame.
"""

import struct
from unittest.mock import patch

from ccsds_tmtf_protocol import CcsdsTmtfProtocol

SCID = 0x44
VCID = 1
FRAME_LENGTH = 1024
DATA_FIELD = FRAME_LENGTH - 6 - 2
NO_PACKET_START = 0x7FF


def make_protocol():
    return CcsdsTmtfProtocol(SCID, FRAME_LENGTH, False, 0, None, True, True, False)


def space_packet(apid, size, fill=0x42):
    return struct.pack(">HHH", apid, 0xC000, size - 7) + bytes([fill]) * (size - 6)


def idle_packet(size):
    return space_packet(0x7FF, size, 0)


def frame(count, fhp, data):
    assert len(data) == DATA_FIELD
    header = struct.pack(">HBBH", (SCID << 4) | (VCID << 1), count, count, 0x1800 | fhp)
    protocol = make_protocol()
    body = header + data
    return body + protocol.crc16.calc(body).to_bytes(2, "big")


def read_all(protocol, frames):
    results = []
    with patch("ccsds_tmtf_protocol.Logger") as logger:
        for data in frames:
            result, _ = protocol.read_data(data)
            while result not in ("STOP", "RESYNC"):
                results.append(result)
                result, _ = protocol.read_data(b"")
    return results, logger


def test_packet_spanning_three_frames():
    big = space_packet(0x01, 2500)
    after = space_packet(0x02, 20, 0x11)
    third_used = 2500 - 2 * DATA_FIELD
    frames = [
        frame(0, 0, big[:DATA_FIELD]),
        frame(1, NO_PACKET_START, big[DATA_FIELD : 2 * DATA_FIELD]),
        frame(2, third_used, big[2 * DATA_FIELD :] + after + idle_packet(DATA_FIELD - third_used - 20)),
    ]
    results, logger = read_all(make_protocol(), frames)
    assert results == [big, after]
    logger.error.assert_not_called()
    logger.warn.assert_not_called()


def test_idle_packet_spanning_frames():
    # 1013 bytes of packet leave 3 bytes, too few for a 7 byte idle packet, so its tail spans
    first = space_packet(0x01, DATA_FIELD - 3)
    idle = idle_packet(7)
    second = space_packet(0x02, 100, 0x22)
    frames = [
        frame(0, 0, first + idle[:3]),
        frame(1, 4, idle[3:] + second + idle_packet(DATA_FIELD - 4 - 100)),
    ]
    results, logger = read_all(make_protocol(), frames)
    assert results == [first, second]
    logger.error.assert_not_called()
    logger.warn.assert_not_called()


def test_connect_during_continuation_frame_is_quiet():
    # COSMOS connects while a packet is spanning: the first frame seen has no packet start
    big = space_packet(0x01, 2500)
    after = space_packet(0x02, 20, 0x11)
    third_used = 2500 - 2 * DATA_FIELD
    frames = [
        frame(1, NO_PACKET_START, big[DATA_FIELD : 2 * DATA_FIELD]),
        frame(2, third_used, big[2 * DATA_FIELD :] + after + idle_packet(DATA_FIELD - third_used - 20)),
    ]
    results, logger = read_all(make_protocol(), frames)
    assert results == [after]
    logger.error.assert_not_called()
    logger.warn.assert_not_called()


def test_connect_mid_packet_skips_to_first_header_quietly():
    big = space_packet(0x01, 2500)
    after = space_packet(0x02, 20, 0x11)
    third_used = 2500 - 2 * DATA_FIELD
    frames = [
        frame(2, third_used, big[2 * DATA_FIELD :] + after + idle_packet(DATA_FIELD - third_used - 20)),
    ]
    results, logger = read_all(make_protocol(), frames)
    assert results == [after]
    logger.error.assert_not_called()
    logger.warn.assert_not_called()


def test_lost_frame_drops_partial_packet():
    # The continuation frame (count 1) is lost: the partial packet must not be glued to the
    # tail in frame 2, which would emit a corrupted packet
    big = space_packet(0x01, 2500)
    after = space_packet(0x02, 20, 0x11)
    third_used = 2500 - 2 * DATA_FIELD
    frames = [
        frame(0, 0, big[:DATA_FIELD]),
        frame(2, third_used, big[2 * DATA_FIELD :] + after + idle_packet(DATA_FIELD - third_used - 20)),
    ]
    results, logger = read_all(make_protocol(), frames)
    assert results == [after]
    logger.warn.assert_called()


def test_partial_packet_not_ending_at_first_header_is_dropped():
    # Same counters, but the partial packet's length disagrees with the First Header Pointer
    # (flight dropped the rest of a packet after a failed send): resume at the pointer
    big = space_packet(0x01, 2500)
    after = space_packet(0x02, 20, 0x11)
    frames = [
        frame(0, 0, big[:DATA_FIELD]),
        frame(1, 0, after + idle_packet(DATA_FIELD - 20)),
    ]
    results, logger = read_all(make_protocol(), frames)
    assert results == [after]
