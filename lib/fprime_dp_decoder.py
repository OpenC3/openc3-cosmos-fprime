# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Decode F Prime data product (.fdp) files.

File layout (big-endian): Header | HeaderHash U32 | Data[DataSize] | DataHash U32
Header: PacketDescriptor, Id, Priority, TimeTag (base, context, sec U32, usec U32),
        ProcTypes, UserData[user_data_size], DpState, DataSize.
Hashes are CRC-32 (zlib.crc32). Field widths come from the generated WIDTHS
(bits, except user_data_size in bytes) because they vary by F Prime version.
Records: RecordId, then the value; array records put a FwSizeStoreType count first.
"""

import json
import struct
import zlib
from dataclasses import asdict, dataclass, field

DP_DESCRIPTOR = 5
HASH_SIZE = 4

_INT_CODES = {8: "b", 16: "h", 32: "i", 64: "q"}


@dataclass
class DpHeader:
    descriptor: int
    container_id: int
    priority: int
    time_base: int
    time_context: int
    seconds: int
    useconds: int
    proc_types: int
    user_data: bytes
    dp_state: int
    data_size: int


@dataclass
class DpRecord:
    id: int
    name: str
    array: bool
    value: object
    raw: bytes


@dataclass
class DecodedDp:
    header: DpHeader | None
    header_crc_ok: bool = False
    data_crc_ok: bool = False
    records: list = field(default_factory=list)
    compressed: bool = False
    error: str | None = None

    @property
    def ok(self):
        return self.error is None and self.header_crc_ok and self.data_crc_ok


class RecordDecodeError(ValueError):
    def __init__(self, message, records):
        super().__init__(message)
        self.records = records


def _int(data, offset, bits, signed=False):
    size = bits // 8
    if offset + size > len(data):
        raise ValueError(f"need {size} bytes at offset {offset} but only {len(data) - offset} remain")
    code = _INT_CODES[bits] if signed else _INT_CODES[bits].upper()
    return struct.unpack_from(">" + code, data, offset)[0], offset + size


def parse_value(data, offset, t, widths):
    kind = t["kind"]
    if kind == "integer":
        return _int(data, offset, t["size"], t.get("signed", False))
    if kind == "float":
        size = t["size"] // 8
        if offset + size > len(data):
            raise ValueError(f"need {size} bytes at offset {offset} but only {len(data) - offset} remain")
        return struct.unpack_from(">f" if size == 4 else ">d", data, offset)[0], offset + size
    if kind == "bool":
        value, offset = _int(data, offset, t.get("size", 8))
        return value != 0, offset
    if kind == "enum":
        rep = t["representationType"]
        value, offset = _int(data, offset, rep["size"], rep.get("signed", False))
        return t["states"].get(value, value), offset
    if kind == "string":
        length, offset = _int(data, offset, widths["size_store"])
        if offset + length > len(data):
            raise ValueError(f"string of {length} bytes at offset {offset} runs past the data")
        return bytes(data[offset:offset + length]).decode("utf-8", errors="replace"), offset + length
    if kind == "array":
        values = []
        for _ in range(t["size"]):
            value, offset = parse_value(data, offset, t["elementType"], widths)
            values.append(value)
        return values, offset
    if kind == "struct":
        result = {}
        for member in t["members"]:
            result[member["name"]], offset = parse_value(data, offset, member, widths)
        return result, offset
    raise ValueError(f"unhandled type kind {kind}")


def header_size(widths):
    bits = (
        widths["packet_descriptor"] + widths["dp_id"] + widths["dp_priority"] + widths["time_base"]
        + widths["time_context"] + 64 + widths["proc_type"] + widths["dp_state"] + widths["size_store"]
    )
    return bits // 8 + widths["user_data_size"]


def decode_records(payload, widths, records):
    decoded = []
    offset = 0
    while offset < len(payload):
        start = offset
        try:
            record_id, offset = _int(payload, offset, widths["dp_id"])
            definition = records.get(record_id)
            if definition is None:
                raise ValueError(f"unknown record id {record_id} at data offset {start}")
            value_start = offset
            if definition["array"]:
                count, offset = _int(payload, offset, widths["size_store"])
                value = []
                for _ in range(count):
                    element, offset = parse_value(payload, offset, definition["type"], widths)
                    value.append(element)
            else:
                value, offset = parse_value(payload, offset, definition["type"], widths)
        except (ValueError, struct.error) as error:
            raise RecordDecodeError(str(error), decoded) from error
        decoded.append(DpRecord(record_id, definition["name"], definition["array"], value, payload[value_start:offset]))
    return decoded


COMPRESSION_RECORD_SUFFIX = ".CompressionRecord"
UNCOMPRESSED, ZLIB_DEFLATE = 0, 1


def decompress_records(records):
    """Join DpCompressProc records (U8 arrays: algorithm U8 + payload) into the original record stream."""
    out = bytearray()
    for record in records:
        body = bytes(record.value)
        if not body:
            raise ValueError(f"empty compression record {record.name}")
        algorithm, payload = body[0], body[1:]
        if algorithm == UNCOMPRESSED:
            out += payload
        elif algorithm == ZLIB_DEFLATE:
            try:
                out += zlib.decompress(payload)
            except zlib.error as error:
                raise ValueError(f"cannot decompress {record.name}: {error}") from error
        else:
            raise ValueError(f"unsupported compression algorithm {algorithm} in {record.name}")
    return bytes(out)


def _is_compressed(records):
    return bool(records) and all(r.array and r.name.endswith(COMPRESSION_RECORD_SUFFIX) for r in records)


def decode_dp(data, widths, records):
    data = bytes(data)
    size = header_size(widths)
    if len(data) < size + 2 * HASH_SIZE:
        return DecodedDp(None, error=f"file too short for a data product header ({len(data)} bytes)")
    w = widths
    offset = 0
    descriptor, offset = _int(data, offset, w["packet_descriptor"])
    container_id, offset = _int(data, offset, w["dp_id"])
    priority, offset = _int(data, offset, w["dp_priority"])
    time_base, offset = _int(data, offset, w["time_base"])
    time_context, offset = _int(data, offset, w["time_context"])
    seconds, offset = _int(data, offset, 32)
    useconds, offset = _int(data, offset, 32)
    proc_types, offset = _int(data, offset, w["proc_type"])
    user_data = data[offset:offset + w["user_data_size"]]
    offset += w["user_data_size"]
    dp_state, offset = _int(data, offset, w["dp_state"])
    data_size, offset = _int(data, offset, w["size_store"])
    header = DpHeader(descriptor, container_id, priority, time_base, time_context, seconds, useconds,
                      proc_types, user_data, dp_state, data_size)

    result = DecodedDp(header)
    result.header_crc_ok = struct.unpack_from(">I", data, size)[0] == zlib.crc32(data[:size])
    if descriptor != DP_DESCRIPTOR:
        result.error = f"packet descriptor {descriptor} is not FW_PACKET_DP ({DP_DESCRIPTOR})"
        return result
    if not result.header_crc_ok:
        result.error = "header hash mismatch; records not decoded"
        return result
    start = size + HASH_SIZE
    end = start + data_size
    if end + HASH_SIZE > len(data):
        result.error = f"data size {data_size} exceeds the {len(data) - start - HASH_SIZE} bytes in the file"
        return result
    payload = data[start:end]
    result.data_crc_ok = struct.unpack_from(">I", data, end)[0] == zlib.crc32(payload)
    try:
        result.records = decode_records(payload, widths, records)
    except RecordDecodeError as error:
        result.records = error.records
        result.error = str(error)
        return result
    if _is_compressed(result.records):
        try:
            inner = decompress_records(result.records)
        except ValueError as error:
            result.error = str(error)
            return result
        result.compressed = True
        try:
            result.records = decode_records(inner, widths, records)
        except RecordDecodeError as error:
            result.records = error.records
            result.error = str(error)
    return result


def _jsonable(value):
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def decoded_to_json(decoded, file_name, container=None):
    header = None
    if decoded.header is not None:
        header = {key: _jsonable(value) for key, value in asdict(decoded.header).items()}
    doc = {
        "file": file_name,
        "container": container["name"] if container else None,
        "header": header,
        "header_crc_ok": decoded.header_crc_ok,
        "data_crc_ok": decoded.data_crc_ok,
        "compressed": decoded.compressed,
        "error": decoded.error,
        "records": [{"id": r.id, "name": r.name, "array": r.array, "value": r.value} for r in decoded.records],
    }
    return json.dumps(doc, indent=2)
