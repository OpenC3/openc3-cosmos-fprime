# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Parse F Prime Fw::FilePacket packets and reassemble downlinked files.

Layouts (identical in F Prime v3.6 and v4.x, all big-endian):
  header : type U8, sequenceIndex U32
  START  : header, fileSize U32, sourcePath (U8 length + bytes), destPath (U8 length + bytes)
  DATA   : header, byteOffset U32, dataSize U16, data
  END    : header, checksum U32 (CFDP checksum of the whole file)
  CANCEL : header
"""

import posixpath
import struct
from dataclasses import dataclass

T_START, T_DATA, T_END, T_CANCEL = 0, 1, 2, 3


@dataclass
class FilePacket:
    type: int
    sequence_index: int
    file_size: int = 0
    source_path: str = ""
    dest_path: str = ""
    byte_offset: int = 0
    data: bytes = b""
    checksum: int = 0


@dataclass
class CompletedFile:
    source_path: str
    dest_path: str
    data: bytes
    complete: bool
    checksum_ok: bool


def _read_path(buf, offset):
    if offset >= len(buf):
        raise ValueError("file packet truncated before path length")
    end = offset + 1 + buf[offset]
    if end > len(buf):
        raise ValueError("file packet truncated in path")
    return buf[offset + 1:end].decode("utf-8", errors="replace"), end


def parse_file_packet(buf):
    buf = bytes(buf)
    try:
        packet_type, seq = struct.unpack_from(">BI", buf, 0)
        if packet_type == T_START:
            (size,) = struct.unpack_from(">I", buf, 5)
            source, offset = _read_path(buf, 9)
            dest, _ = _read_path(buf, offset)
            return FilePacket(packet_type, seq, file_size=size, source_path=source, dest_path=dest)
        if packet_type == T_DATA:
            byte_offset, size = struct.unpack_from(">IH", buf, 5)
            if 11 + size > len(buf):
                raise ValueError(f"file DATA packet claims {size} bytes but has {len(buf) - 11}")
            return FilePacket(packet_type, seq, byte_offset=byte_offset, data=buf[11:11 + size])
        if packet_type == T_END:
            (checksum,) = struct.unpack_from(">I", buf, 5)
            return FilePacket(packet_type, seq, checksum=checksum)
        if packet_type == T_CANCEL:
            return FilePacket(packet_type, seq)
    except struct.error as error:
        raise ValueError(f"file packet truncated: {error}") from error
    raise ValueError(f"unknown file packet type {packet_type}")


def cfdp_checksum(data):
    """CFDP checksum: U32 sum of big-endian 4-byte words, last word zero padded."""
    view = memoryview(data)
    aligned = len(view) - len(view) % 4
    checksum = 0
    for offset in range(0, aligned, 65536):
        chunk = view[offset:min(offset + 65536, aligned)]
        checksum += sum(struct.unpack(f">{len(chunk) // 4}I", chunk))
    if aligned < len(view):
        checksum += int.from_bytes(view[aligned:], "big") << (8 * (4 - len(view[aligned:])))
    return checksum & 0xFFFFFFFF


def safe_file_name(path):
    """Reduce a flight-provided path to a bare file name safe to use in a bucket key."""
    name = posixpath.basename(path.replace("\\", "/"))
    return "unnamed" if name in ("", ".", "..") else name


class FileAssembler:
    """Reassembles one file at a time, as F Prime FileDownlink sends one at a time."""

    def __init__(self, max_file_size=104857600):
        self.max_file_size = int(max_file_size)
        self.reset()

    def reset(self):
        self._start = None
        self._buffer = None
        self._chunks = []

    def feed(self, packet):
        if packet.type == T_START:
            self.reset()
            if packet.file_size > self.max_file_size:
                raise ValueError(
                    f"file {packet.dest_path} is {packet.file_size} bytes, over max_file_size {self.max_file_size}"
                )
            self._start = packet
            self._buffer = bytearray(packet.file_size)
            return None
        if self._start is None:
            return None
        if packet.type == T_DATA:
            end = packet.byte_offset + len(packet.data)
            if end <= len(self._buffer):
                self._buffer[packet.byte_offset:end] = packet.data
                self._chunks.append((packet.byte_offset, end))
            return None
        if packet.type == T_CANCEL:
            self.reset()
            return None
        # T_END
        start, data = self._start, bytes(self._buffer)
        complete = self._covered(len(data))
        self.reset()
        return CompletedFile(start.source_path, start.dest_path, data, complete, cfdp_checksum(data) == packet.checksum)

    def _covered(self, size):
        position = 0
        for begin, end in sorted(self._chunks):
            if begin > position:
                return False
            position = max(position, end)
        return position >= size
