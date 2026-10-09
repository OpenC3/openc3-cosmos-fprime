# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for SPACE_PACKET / FPRIME framing helpers."""

import struct
import zlib

import pytest

from fprime_framing import frame, unframe


@pytest.mark.parametrize("headers", ["SPACE_PACKET", "FPRIME"])
def test_round_trip(headers):
    assert unframe(headers, frame(headers, 3, b"payload")) == (3, b"payload")


def test_space_packet_header():
    data = frame("SPACE_PACKET", 5, b"abc")
    word0, word1, length, apid = struct.unpack_from(">HHHH", data)
    assert word0 & 0x07FF == 5 and word0 >> 13 == 0 and (word0 >> 12) & 1 == 0
    assert word1 >> 14 == 3
    assert length == len(data) - 7
    assert apid == 5


def test_fprime_header_and_crc():
    data = frame("FPRIME", 5, b"abc")
    sync, size, descriptor = struct.unpack_from(">III", data)
    assert (sync, size, descriptor) == (0xDEADBEEF, 4 + 3, 5)
    assert struct.unpack(">I", data[-4:])[0] == zlib.crc32(data[:-4])


def test_space_packet_ignores_trailing_bytes():
    assert unframe("SPACE_PACKET", frame("SPACE_PACKET", 3, b"xy") + b"\x00\x00") == (3, b"xy")


@pytest.mark.parametrize("headers, data", [("SPACE_PACKET", b"\x00" * 7), ("FPRIME", b"\x00" * 15)])
def test_short_data_returns_none(headers, data):
    assert unframe(headers, data) is None
