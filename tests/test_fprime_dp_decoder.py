# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for the F Prime data product decoder."""

import json

import pytest

import fprime_fixtures as fx
from fprime_dp_decoder import decode_dp, decoded_to_json, header_size

WIDTHS = {"v3": fx.V3_WIDTHS, "v4_1": fx.V4_1_WIDTHS, "v4_4": fx.V4_4_WIDTHS}


def all_records(w):
    return (
        fx.u32_record(w, 42)
        + fx.u8_array_record(w, [1, 2, 3])
        + fx.string_record(w, "hi there")
        + fx.point_record(w, 1.5, 1)
        + fx.bool_record(w, True)
    )


@pytest.mark.parametrize("version, expected", [("v3", 59), ("v4_1", 57), ("v4_4", 63)])
def test_header_size(version, expected):
    assert header_size(WIDTHS[version]) == expected


@pytest.mark.parametrize("version", WIDTHS)
def test_header_fields(version):
    w = WIDTHS[version]
    decoded = decode_dp(fx.build_fdp(w, all_records(w), container_id=0x222, priority=3, dp_state=2), w, fx.RECORDS)
    h = decoded.header
    assert (h.descriptor, h.container_id, h.priority) == (5, 0x222, 3)
    assert (h.time_base, h.time_context, h.seconds, h.useconds) == (2, 0, 1700000000, 250000)
    assert h.user_data == bytes(range(32))
    assert h.dp_state == 2
    assert h.data_size == len(all_records(w))
    assert decoded.header_crc_ok and decoded.data_crc_ok and decoded.error is None and decoded.ok


@pytest.mark.parametrize("version", WIDTHS)
def test_record_values(version):
    w = WIDTHS[version]
    decoded = decode_dp(fx.build_fdp(w, all_records(w)), w, fx.RECORDS)
    values = {r.name: r.value for r in decoded.records}
    assert values == {
        "inst.U32Record": 42,
        "inst.U8ArrayRecord": [1, 2, 3],
        "inst.StringRecord": "hi there",
        "inst.PointRecord": {"x": 1.5, "mode": "ON"},
        "inst.BoolRecord": True,
    }


def test_raw_includes_array_count_but_not_record_id():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, fx.u8_array_record(w, [9, 8])), w, fx.RECORDS)
    assert decoded.records[0].raw == b"\x00\x02\x09\x08"
    assert decoded.records[0].id == 0x101 and decoded.records[0].array


def test_bad_header_hash_skips_records():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, fx.u32_record(w, 1), corrupt_header=True), w, fx.RECORDS)
    assert decoded.header is not None and not decoded.header_crc_ok
    assert decoded.records == [] and "header hash" in decoded.error


def test_bad_data_hash_still_decodes():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, fx.u32_record(w, 1), corrupt_data=True), w, fx.RECORDS)
    assert not decoded.data_crc_ok and decoded.records[0].value == 1 and not decoded.ok


def test_unknown_record_keeps_earlier_records():
    w = fx.V3_WIDTHS
    data = fx.u32_record(w, 5) + fx.record(w, 0x999, b"\x00\x01") + fx.u32_record(w, 6)
    decoded = decode_dp(fx.build_fdp(w, data), w, fx.RECORDS)
    assert [r.value for r in decoded.records] == [5]
    assert "unknown record id 2457" in decoded.error and not decoded.ok


def test_truncated_record_keeps_earlier_records():
    w = fx.V3_WIDTHS
    data = fx.u32_record(w, 5) + fx.u32_record(w, 6)[:-2]
    decoded = decode_dp(fx.build_fdp(w, data), w, fx.RECORDS)
    assert [r.value for r in decoded.records] == [5] and decoded.error


def test_wrong_descriptor():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, fx.u32_record(w, 1), descriptor=3), w, fx.RECORDS)
    assert "descriptor 3" in decoded.error and decoded.records == []


def test_too_short_for_header():
    decoded = decode_dp(b"\x00" * 10, fx.V3_WIDTHS, fx.RECORDS)
    assert decoded.header is None and "too short" in decoded.error


def test_data_size_past_end_of_file():
    w = fx.V3_WIDTHS
    fdp = fx.build_fdp(w, fx.u32_record(w, 1))
    decoded = decode_dp(fdp[:-6], w, fx.RECORDS)
    assert "exceeds" in decoded.error and decoded.records == []


def test_empty_product():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, b""), w, fx.RECORDS)
    assert decoded.ok and decoded.records == []


def test_to_json():
    w = fx.V3_WIDTHS
    decoded = decode_dp(fx.build_fdp(w, fx.u32_record(w, 42)), w, fx.RECORDS)
    doc = json.loads(decoded_to_json(decoded, "Dp_1.fdp", {"name": "inst.Container", "default_priority": 7}))
    assert doc["file"] == "Dp_1.fdp" and doc["container"] == "inst.Container"
    assert doc["header"]["container_id"] == 0x200
    assert doc["header"]["user_data"] == bytes(range(32)).hex()
    assert doc["records"] == [{"id": 0x100, "name": "inst.U32Record", "array": False, "value": 42}]
    assert doc["header_crc_ok"] and doc["data_crc_ok"] and doc["error"] is None


def test_to_json_without_header():
    decoded = decode_dp(b"", fx.V3_WIDTHS, fx.RECORDS)
    doc = json.loads(decoded_to_json(decoded, "bad.fdp"))
    assert doc["header"] is None and doc["container"] is None and doc["error"]
