# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Byte builders for F Prime file packets and data product files, shared by tests."""

import struct

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
