# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Frame and unframe F Prime packets as they look after the interface's framing protocols.

SPACE_PACKET (F Prime 4.x): CCSDS primary header (APID = descriptor), U16 descriptor, payload
FPRIME (F Prime 3.x):        0xDEADBEEF, U32 size, U32 descriptor, payload, U32 CRC-32
"""

import struct
import zlib

FW_PACKET_FILE = 3
FW_PACKET_DP = 5

FPRIME_SYNC = 0xDEADBEEF


def frame(headers, descriptor, payload):
    if headers == "FPRIME":
        body = struct.pack(">I", descriptor) + payload
        head = struct.pack(">II", FPRIME_SYNC, len(body))
        return head + body + struct.pack(">I", zlib.crc32(head + body))
    body = struct.pack(">H", descriptor) + payload
    if len(body) > 65536:
        raise ValueError(f"payload of {len(payload)} bytes is too large for a CCSDS space packet")
    # version 0, type 0 (telemetry), no secondary header, unsegmented (sequence flags 3)
    return struct.pack(">HHH", descriptor & 0x07FF, 0xC000, len(body) - 1) + body


def unframe(headers, data):
    """Return (descriptor, payload) or None if data is too short to be a packet."""
    if headers == "FPRIME":
        if len(data) < 16:
            return None
        size, descriptor = struct.unpack_from(">II", data, 4)
        return descriptor, bytes(data[12:8 + size])
    if len(data) < 8:
        return None
    apid = struct.unpack_from(">H", data, 0)[0] & 0x07FF
    length = struct.unpack_from(">H", data, 4)[0] + 1
    return apid, bytes(data[8:6 + length])
