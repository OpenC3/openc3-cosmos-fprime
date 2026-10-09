# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for synthesized data product telemetry packets."""

import struct

import pytest

import fprime_fixtures as fx
from fprime_dp_decoder import decode_dp
from fprime_dp_packets import DP_KIND_HEADER, DP_KIND_RECORD, build_dp_packets
from fprime_framing import unframe


def _decoded(w=fx.V3_WIDTHS):
    data = fx.u32_record(w, 42) + fx.u8_array_record(w, [7, 8])
    return decode_dp(fx.build_fdp(w, data, container_id=0x200, priority=9, dp_state=1), w, fx.RECORDS)


@pytest.mark.parametrize("headers", ["SPACE_PACKET", "FPRIME"])
def test_one_header_plus_one_per_record(headers):
    packets = build_dp_packets(headers, _decoded(), "Dp_1.fdp")
    assert len(packets) == 3
    assert all(unframe(headers, p)[0] == 5 for p in packets)


def test_header_payload():
    decoded = _decoded()
    _, payload = unframe("SPACE_PACKET", build_dp_packets("SPACE_PACKET", decoded, "Dp_1.fdp")[0])
    kind, container, tb, ctx, sec, usec = struct.unpack_from(">BIHBII", payload, 0)
    assert (kind, container, tb, ctx, sec, usec) == (DP_KIND_HEADER, 0x200, 2, 0, 1700000000, 250000)
    prio, proc, state, size, hok, dok, decode_ok, count = struct.unpack_from(">IBBQBBBI", payload, 16)
    assert (prio, proc, state, size, hok, dok, decode_ok, count) == (9, 0, 1, decoded.header.data_size, 1, 1, 1, 2)
    rest = payload[16 + 21:]
    assert rest[:32] == bytes(range(32))
    assert rest[32] == len("Dp_1.fdp") and rest[33:] == b"Dp_1.fdp"


def test_record_payload_is_raw_record():
    packets = build_dp_packets("SPACE_PACKET", _decoded(), "Dp_1.fdp")
    _, payload = unframe("SPACE_PACKET", packets[2])
    assert payload[0] == DP_KIND_RECORD
    assert struct.unpack_from(">I", payload, 16)[0] == 0x101
    assert payload[20:] == b"\x00\x02\x07\x08"


def test_decode_error_clears_decode_ok():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, fx.record(w, 0x999, b"")), w, fx.RECORDS)
    _, payload = unframe("SPACE_PACKET", build_dp_packets("SPACE_PACKET", decoded, "x.fdp")[0])
    assert payload[16 + 4 + 1 + 1 + 8 + 2] == 0


def test_long_file_name_truncated_to_255():
    _, payload = unframe("SPACE_PACKET", build_dp_packets("SPACE_PACKET", _decoded(), "n" * 300)[0])
    assert payload[16 + 21 + 32] == 255
