# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Byte builders for F Prime file packets and data product files, shared by tests."""

import struct
import zlib

from fprime_file_assembler import T_CANCEL, T_DATA, T_END, T_START, cfdp_checksum


def file_start(seq, size, src="/src/file", dest="/dst/file"):
    s, d = src.encode(), dest.encode()
    return struct.pack(">BII", T_START, seq, size) + bytes([len(s)]) + s + bytes([len(d)]) + d


def file_data(seq, offset, chunk):
    return struct.pack(">BIIH", T_DATA, seq, offset, len(chunk)) + chunk


def file_end(seq, checksum):
    return struct.pack(">BII", T_END, seq, checksum)


def file_cancel(seq):
    return struct.pack(">BI", T_CANCEL, seq)


def file_transfer(dest, content, chunk=7, checksum=None, src="/src/file"):
    """START, DATA..., END for content, as F Prime FileDownlink would send them."""
    packets = [file_start(0, len(content), src, dest)]
    seq = 1
    for offset in range(0, len(content), chunk):
        packets.append(file_data(seq, offset, content[offset:offset + chunk]))
        seq += 1
    packets.append(file_end(seq, cfdp_checksum(content) if checksum is None else checksum))
    return packets


V3_WIDTHS = {
    "packet_descriptor": 32, "dp_id": 32, "dp_priority": 32, "size_store": 16, "time_base": 16,
    "time_context": 8, "proc_type": 8, "dp_state": 8, "user_data_size": 32,
}
V4_1_WIDTHS = {**V3_WIDTHS, "packet_descriptor": 16}
V4_4_WIDTHS = {**V3_WIDTHS, "packet_descriptor": 16, "size_store": 64}

U8 = {"kind": "integer", "size": 8, "signed": False}
RECORDS = {
    0x100: {"name": "inst.U32Record", "array": False, "type": {"kind": "integer", "size": 32, "signed": False}},
    0x101: {"name": "inst.U8ArrayRecord", "array": True, "type": U8},
    0x102: {"name": "inst.StringRecord", "array": False, "type": {"kind": "string", "size": 80}},
    0x103: {
        "name": "inst.PointRecord",
        "array": False,
        "type": {
            "kind": "struct",
            "members": [
                {"kind": "float", "size": 32, "name": "x"},
                {"kind": "enum", "representationType": U8, "states": {0: "OFF", 1: "ON"}, "name": "mode"},
            ],
        },
    },
    0x104: {"name": "inst.BoolRecord", "array": False, "type": {"kind": "bool", "size": 8}},
    0x105: {"name": "DpCompression.dpCompressProc.CompressionRecord", "array": True, "type": U8},
}

_CODES = {8: "B", 16: "H", 32: "I", 64: "Q"}


def uint(bits, value):
    return struct.pack(">" + _CODES[bits], value)


def record(widths, rid, payload):
    return uint(widths["dp_id"], rid) + payload


def u32_record(widths, value):
    return record(widths, 0x100, struct.pack(">I", value))


def u8_array_record(widths, values):
    return record(widths, 0x101, uint(widths["size_store"], len(values)) + bytes(values))


def string_record(widths, text):
    raw = text.encode()
    return record(widths, 0x102, uint(widths["size_store"], len(raw)) + raw)


def point_record(widths, x, mode):
    return record(widths, 0x103, struct.pack(">fB", x, mode))


def bool_record(widths, value):
    return record(widths, 0x104, b"\xff" if value else b"\x00")


def compression_record(widths, raw, algorithm=1):
    body = bytes([algorithm]) + (zlib.compress(raw) if algorithm == 1 else raw)
    return record(widths, 0x105, uint(widths["size_store"], len(body)) + body)


def build_fdp(widths, data, container_id=0x200, priority=7, seconds=1700000000, useconds=250000,
              time_base=2, context=0, proc_types=0, user_data=None, dp_state=0, descriptor=5,
              corrupt_header=False, corrupt_data=False):
    w = widths
    if user_data is None:
        user_data = bytes(range(w["user_data_size"]))
    header = (
        uint(w["packet_descriptor"], descriptor) + uint(w["dp_id"], container_id)
        + uint(w["dp_priority"], priority) + uint(w["time_base"], time_base)
        + uint(w["time_context"], context) + struct.pack(">II", seconds, useconds)
        + uint(w["proc_type"], proc_types) + user_data + uint(w["dp_state"], dp_state)
        + uint(w["size_store"], len(data))
    )
    header_crc = zlib.crc32(header) ^ (1 if corrupt_header else 0)
    data_crc = zlib.crc32(data) ^ (1 if corrupt_data else 0)
    return header + struct.pack(">I", header_crc) + data + struct.pack(">I", data_crc)
