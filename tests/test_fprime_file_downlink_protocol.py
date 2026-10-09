# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for the F Prime file downlink / data product protocol."""

import json
from unittest.mock import patch

import pytest

from openc3.environment import OPENC3_LOGS_BUCKET, OPENC3_SCOPE
from openc3.interfaces.interface import Interface

import fprime_fixtures as fx
from fprime_dp_packets import DP_KIND_HEADER, DP_KIND_RECORD
from fprime_file_downlink_protocol import FprimeFileDownlinkProtocol
from fprime_framing import frame, unframe

W = fx.V3_WIDTHS


class FakeDictionary:
    WIDTHS = W
    RECORDS = fx.RECORDS
    CONTAINERS = {0x200: {"name": "inst.Container", "default_priority": 7}}


class Recording(FprimeFileDownlinkProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stored = {}
        self._dictionary = FakeDictionary

    def store(self, name, body):
        self.stored[name] = bytes(body)


def _fdp():
    return fx.build_fdp(W, fx.u32_record(W, 42) + fx.u8_array_record(W, [1, 2]))


def _send(protocol, headers, dest, content, **kwargs):
    outputs = []
    for raw in fx.file_transfer(dest, content, **kwargs):
        data = frame(headers, 3, raw)
        out, _ = protocol.read_data(data)
        assert out == data
        outputs.append(out)
    return outputs


def _drain(protocol):
    packets = []
    while True:
        out, _ = protocol.read_data(b"")
        if out == "STOP":
            return packets
        packets.append(out)


@pytest.mark.parametrize("headers", ["SPACE_PACKET", "FPRIME"])
def test_stores_plain_file(headers):
    p = Recording(headers, "FSW", allow_empty_data=False)
    _send(p, headers, "/dst/log.txt", b"plain file contents")
    assert p.stored == {"log.txt": b"plain file contents"}
    assert _drain(p) == []


def test_non_file_packets_pass_through():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    data = frame("SPACE_PACKET", 1, b"\x00\x00\x00\x01telemetry")
    assert p.read_data(data) == (data, None)
    assert p.stored == {}


@pytest.mark.parametrize("headers", ["SPACE_PACKET", "FPRIME"])
def test_data_product_stored_decoded_and_queued(headers):
    p = Recording(headers, "FSW", allow_empty_data=False)
    _send(p, headers, "/dp/Dp_00000512_1_2.fdp", _fdp())
    assert p.stored["Dp_00000512_1_2.fdp"] == _fdp()
    doc = json.loads(p.stored["Dp_00000512_1_2.json"])
    assert doc["container"] == "inst.Container"
    assert [r["value"] for r in doc["records"]] == [42, [1, 2]]
    packets = [unframe(headers, data) for data in _drain(p)]
    assert [d for d, _ in packets] == [5, 5, 5]
    assert [payload[0] for _, payload in packets] == [DP_KIND_HEADER, DP_KIND_RECORD, DP_KIND_RECORD]


def test_incomplete_file_not_decoded():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    raws = fx.file_transfer("/dp/Dp_1.fdp", _fdp())
    del raws[2]
    for raw in raws:
        p.read_data(frame("SPACE_PACKET", 3, raw))
    assert list(p.stored) == ["Dp_1.fdp.incomplete"]
    assert _drain(p) == []


def test_bad_checksum_still_stored():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    _send(p, "SPACE_PACKET", "/dst/a.bin", b"abcdef", checksum=1)
    assert p.stored == {"a.bin": b"abcdef"}


def test_dest_path_traversal_is_flattened():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    _send(p, "SPACE_PACKET", "../../etc/passwd", b"x")
    assert list(p.stored) == ["passwd"]


def test_unknown_record_still_stores_and_emits_header():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    fdp = fx.build_fdp(W, fx.u32_record(W, 1) + fx.record(W, 0x999, b""))
    _send(p, "SPACE_PACKET", "/dp/Dp_2.fdp", fdp)
    assert "unknown record" in json.loads(p.stored["Dp_2.json"])["error"]
    packets = _drain(p)
    assert len(packets) == 2  # header + the one good record


def test_missing_dictionary_stores_file_only():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    p._dictionary = False
    _send(p, "SPACE_PACKET", "/dp/Dp_3.fdp", _fdp())
    assert list(p.stored) == ["Dp_3.fdp"]
    assert _drain(p) == []


def test_store_failure_does_not_break_stream():
    class Broken(Recording):
        def store(self, name, body):
            raise ConnectionError("bucket down")

    p = Broken("SPACE_PACKET", "FSW", allow_empty_data=False)
    with patch("fprime_file_downlink_protocol.Logger") as logger:
        _send(p, "SPACE_PACKET", "/dst/a.bin", b"abc")
    assert "bucket down" in logger.error.call_args[0][0]


def test_malformed_file_packet_passes_through():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    data = frame("SPACE_PACKET", 3, b"\x09")
    with patch("fprime_file_downlink_protocol.Logger"):
        assert p.read_data(data) == (data, None)


def test_oversize_file_rejected():
    p = Recording("SPACE_PACKET", "FSW", max_file_size=4, allow_empty_data=False)
    with patch("fprime_file_downlink_protocol.Logger") as logger:
        _send(p, "SPACE_PACKET", "/dst/big", b"0123456789")
    assert p.stored == {}
    assert "max_file_size" in logger.error.call_args[0][0]


def test_bucket_key():
    p = FprimeFileDownlinkProtocol("SPACE_PACKET", "FSW")
    assert p.bucket_key("x.fdp") == f"{OPENC3_SCOPE}/fprime_downlink/FSW/x.fdp"


def test_default_store_uses_logs_bucket():
    p = FprimeFileDownlinkProtocol("SPACE_PACKET", "FSW")
    with patch("fprime_file_downlink_protocol.Bucket") as bucket:
        p.store("x.bin", b"abc")
    bucket.getClient.return_value.put_object.assert_called_once_with(
        bucket=OPENC3_LOGS_BUCKET, key=f"{OPENC3_SCOPE}/fprime_downlink/FSW/x.bin", body=b"abc"
    )


def test_reset_drops_queue_and_transfer():
    p = Recording("SPACE_PACKET", "FSW", allow_empty_data=False)
    _send(p, "SPACE_PACKET", "/dp/Dp_1.fdp", _fdp())
    p.reset()
    assert _drain(p) == []


class ScriptedInterface(Interface):
    def __init__(self, chunks):
        super().__init__()
        self.chunks = list(chunks)

    def connected(self):
        return True

    def read_interface(self):
        if not self.chunks:
            return (None, None)
        data = self.chunks.pop(0)
        self.read_interface_base(data, None)
        return (data, None)


def test_interface_drains_synthesized_packets_before_new_data():
    file_frames = [frame("SPACE_PACKET", 3, raw) for raw in fx.file_transfer("/dp/Dp_1.fdp", _fdp())]
    later = frame("SPACE_PACKET", 1, b"\x00\x00\x00\x01later")
    interface = ScriptedInterface(file_frames + [later])
    protocol = interface.add_protocol(Recording, ["SPACE_PACKET", "FSW"], "READ")
    buffers = []
    while (packet := interface.read()) is not None:
        buffers.append(bytes(packet.buffer))
    assert buffers[: len(file_frames)] == file_frames
    synthesized = buffers[len(file_frames):-1]
    assert [unframe("SPACE_PACKET", b)[0] for b in synthesized] == [5, 5, 5]
    assert buffers[-1] == later
    assert "Dp_1.json" in protocol.stored


def test_synthesized_packets_precede_packets_cached_upstream():
    """END and later packets arriving in one read: the length protocol hands them
    out one at a time, but the DP packets must still come right after END."""
    from openc3.interfaces.protocols.length_protocol import LengthProtocol

    file_frames = [frame("FPRIME", 3, raw) for raw in fx.file_transfer("/dp/Dp_1.fdp", _fdp())]
    later = [frame("FPRIME", 1, b"\x00\x00\x00\x01later"), frame("FPRIME", 1, b"\x00\x00\x00\x02again")]
    interface = ScriptedInterface(file_frames[:-1] + [file_frames[-1] + b"".join(later)])
    interface.add_protocol(LengthProtocol, [32, 32, 12, 1, "BIG_ENDIAN", 0, "0xDEADBEEF", None, True], "READ")
    interface.add_protocol(Recording, ["FPRIME", "FSW"], "READ")
    buffers = []
    while (packet := interface.read()) is not None:
        buffers.append(bytes(packet.buffer))
    assert buffers[: len(file_frames)] == file_frames
    assert [unframe("FPRIME", b)[0] for b in buffers[len(file_frames):-2]] == [5, 5, 5]
    assert buffers[-2:] == later
