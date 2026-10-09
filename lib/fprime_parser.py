# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license. 
# See LICENSE.md file in the project root for details.

import json
import os
import pprint
import re
import sys

USAGE = f"Usage: {sys.argv[0]} <target_name> <path_to_Dictionary.json> [SPACE_PACKET|FPRIME]"
if len(sys.argv) not in (3, 4):
    print(USAGE, file=sys.stderr)
    sys.exit(1)

target_name = sys.argv[1]
json_path = sys.argv[2]
if len(sys.argv) > 3:
    headers = sys.argv[3].upper()
    if headers not in ("SPACE_PACKET", "FPRIME"):
        print(USAGE, file=sys.stderr)
        sys.exit(1)
else:
    headers = None
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

data = None
with open(json_path) as file:
    data = json.load(file)

framework_version = data["metadata"]["frameworkVersion"]
major_version = framework_version[1]
if headers is None:
    if major_version == "4":
        # CCSDS Space Packet Framing
        headers = "SPACE_PACKET"
    else:
        # Fprime Framing
        headers = "FPRIME"

types = {}

for type in data["typeDefinitions"]:
    types[type['qualifiedName']] = type

commands = data["commands"]
events = data["events"]
channels = data["telemetryChannels"]
records = data.get("records", [])
containers = data.get("containers", [])

# Widths (bits) of the framework types that appear on the wire. v4 dictionaries
# carry them as alias/enum typeDefinitions; v3 dictionaries don't, so fall back
# to the v3 FpConfig.h defaults. FwSizeStoreType is U16 before v4.4.0 and U64
# (on unix) from v4.4.0, so it must come from the dictionary when present.
def framework_width(name, default):
    t = types.get(name)
    if t is None:
        return default
    if t["kind"] == "alias" and t["underlyingType"]["kind"] == "integer":
        return t["underlyingType"]["size"]
    if t["kind"] == "enum":
        return t["representationType"]["size"]
    return default

def constant_value(name, default):
    for constant in data.get("constants", []):
        if constant["qualifiedName"] == name:
            return constant["value"]
    return default

widths = {
    "packet_descriptor": framework_width("FwPacketDescriptorType", 32),
    "dp_id": framework_width("FwDpIdType", 32),
    "dp_priority": framework_width("FwDpPriorityType", 32),
    "size_store": framework_width("FwSizeStoreType", 16),
    "time_base": framework_width("FwTimeBaseStoreType", 16),
    "time_context": framework_width("FwTimeContextStoreType", 8),
    "proc_type": framework_width("Fw.DpCfg.ProcType", 8),
    "dp_state": framework_width("Fw.DpState", 8),
    "user_data_size": constant_value("Fw.DpCfg.CONTAINER_USER_DATA_SIZE", 32),
}

def flatten_type(t, types):
    kind = t["kind"]
    if kind == "qualifiedIdentifier":
        resolved = types[t["name"]]
        rkind = resolved["kind"]
        if rkind == "enum":
            states = {c["value"]: c["name"] for c in resolved["enumeratedConstants"]}
            return {
                "kind": "enum",
                "representationType": resolved["representationType"],
                "states": states,
            }
        if rkind == "array":
            return {
                "kind": "array",
                "size": resolved["size"],
                "elementType": flatten_type(resolved["elementType"], types),
            }
        if rkind == "alias":
            return flatten_type(resolved["underlyingType"], types)
        if rkind == "struct":
            members = sorted(resolved["members"].items(), key=lambda kv: kv[1]["index"])
            flat_members = []
            for mname, m in members:
                flat = flatten_type(m["type"], types)
                if "size" in m:
                    # FPP member array, e.g. `vals: [3] U32`
                    flat = {"kind": "array", "size": m["size"], "elementType": flat}
                flat["name"] = mname
                flat_members.append(flat)
            return {"kind": "struct", "members": flat_members}
        raise RuntimeError(f"Unhandled typeDefinition kind: {rkind}")
    if kind == "integer":
        return {"kind": "integer", "size": t["size"], "signed": t.get("signed", False)}
    if kind == "float":
        return {"kind": "float", "size": t["size"]}
    if kind == "string":
        return {"kind": "string", "size": t["size"]}
    if kind == "bool":
        return {"kind": "bool", "size": t.get("size", 8)}
    raise RuntimeError(f"Unhandled type kind: {kind}")

def resolve_value_type(t, types):
    """Resolve a type spec to its underlying scalar dict, or None for struct/array."""
    if t["kind"] == "qualifiedIdentifier":
        resolved = types[t["name"]]
        rkind = resolved["kind"]
        if rkind == "alias":
            return resolve_value_type(resolved["underlyingType"], types)
        if rkind == "enum":
            return resolved["representationType"]
        return None
    return t

def _emit_array_line(f, keyword, name, t, types, annotation, emit_element):
    elem = t["elementType"]
    while elem["kind"] == "qualifiedIdentifier" and types[elem["name"]]["kind"] == "alias":
        elem = types[elem["name"]]["underlyingType"]
    elem_kind = elem["kind"]
    if elem_kind == "qualifiedIdentifier":
        # Enum, struct, or nested array elements can't be a COSMOS array item,
        # so emit each element as its own item(s) named NAME_0, NAME_1, ...
        for i in range(t["size"]):
            emit_element(f, f"{name}_{i}", elem, types, annotation)
        return
    size = elem["size"]
    total = size * t["size"]
    if elem_kind == "integer":
        ts = "INT" if elem.get("signed") else "UINT"
        print(f"  {keyword} {name} {size} {ts} {total} \"{annotation}\"", file=f)
    elif elem_kind == "float":
        print(f"  {keyword} {name} {size} FLOAT {total} \"{annotation}\"", file=f)
    elif elem_kind == "string":
        print(f"  {keyword} {name} {size} STRING {total} \"{annotation}\"", file=f)
    elif elem_kind == "bool":
        print(f"  {keyword} {name} {size} UINT {total} \"{annotation}\"", file=f)
        print(f"    STATE FALSE 0", file=f)
        print(f"    STATE TRUE 1", file=f)
    else:
        raise RuntimeError(f"Unhandled array element kind {elem_kind}")

def emit_command_param(f, name, t, types, annotation):
    kind = t["kind"]
    if kind == "qualifiedIdentifier":
        resolved = types[t["name"]]
        rkind = resolved["kind"]
        if rkind == "alias":
            emit_command_param(f, name, resolved["underlyingType"], types, annotation)
            return
        if rkind == "struct":
            for mname, m in sorted(resolved["members"].items(), key=lambda kv: kv[1]["index"]):
                member_name = f"{name}_{mname}"
                if "size" in m:
                    # FPP member array, e.g. `vals: [3] U32`
                    member_array = {"size": m["size"], "elementType": m["type"]}
                    _emit_array_line(f, "APPEND_ARRAY_PARAMETER", member_name, member_array, types, m.get("annotation", ""), emit_command_param)
                else:
                    emit_command_param(f, member_name, m["type"], types, m.get("annotation", ""))
            return
        if rkind == "enum":
            states = {c["name"]: c["value"] for c in resolved["enumeratedConstants"]}
            default = states[resolved["default"].split(".")[-1]]
            rep = resolved["representationType"]
            ts = "INT" if rep["signed"] else "UINT"
            print(f"  APPEND_PARAMETER {name} {rep['size']} {ts} MIN MAX {default} \"{annotation}\"", file=f)
            for key, value in states.items():
                print(f"    STATE {key} {value}", file=f)
            return
        if rkind == "array":
            _emit_array_line(f, "APPEND_ARRAY_PARAMETER", name, resolved, types, annotation, emit_command_param)
            return
        raise RuntimeError(f"Unhandled typeDefinition kind {rkind}")
    if kind == "string":
        print(f"  APPEND_PARAMETER {name} {t['size'] * 8} STRING \"\" \"{annotation}\"", file=f)
        return
    if kind == "integer":
        ts = "INT" if t["signed"] else "UINT"
        print(f"  APPEND_PARAMETER {name} {t['size']} {ts} MIN MAX 0 \"{annotation}\"", file=f)
        return
    if kind == "float":
        print(f"  APPEND_PARAMETER {name} {t['size']} FLOAT MIN MAX 0 \"{annotation}\"", file=f)
        return
    if kind == "bool":
        print(f"  APPEND_PARAMETER {name} {t['size']} UINT 0 1 0 \"{annotation}\"", file=f)
        print(f"    STATE FALSE 0", file=f)
        print(f"    STATE TRUE 1", file=f)
        return
    raise RuntimeError(f"Unhandled type kind {kind}")

def emit_variable_string(f, name, length_bits, annotation=""):
    # COSMOS variable sized items must be declared with a bit size of 0;
    # a non-zero size is counted in the packet's defined length
    print(f"  APPEND_ITEM {name}_LENGTH {length_bits} UINT", file=f)
    print(f"  APPEND_ITEM {name} 0 STRING \"{annotation}\"", file=f)
    print(f"    VARIABLE_BIT_SIZE {name}_LENGTH 8 0", file=f)

FW_PACKET_FILE = 3
FW_PACKET_DP = 5

def clean_annotation(text):
    return text.replace('\n', ' ').replace('\r', '')

def emit_tlm_header(f, descriptor):
    if headers == "FPRIME":
        print("  APPEND_ITEM FPRIME_SYNC 32 UINT", file=f)
        print("  APPEND_ITEM FPRIME_SIZE 32 UINT", file=f)
        print(f"  APPEND_ID_ITEM FPRIME_PACKET_ID 32 UINT {descriptor}", file=f)
    else:
        print("  APPEND_ITEM CCSDS_VERSION 3 UINT", file=f)
        print("  APPEND_ITEM CCSDS_TYPE 1 UINT", file=f)
        print("  APPEND_ITEM CCSDS_SHF 1 UINT", file=f)
        print(f"  APPEND_ID_ITEM CCSDS_APID 11 UINT {descriptor}", file=f)
        print("  APPEND_ITEM CCSDS_SEQ_FLAGS 2 UINT", file=f)
        print("  APPEND_ITEM CCSDS_SEQ_CNT 14 UINT", file=f)
        print("  APPEND_ITEM CCSDS_LENGTH 16 UINT", file=f)
        print("  APPEND_ITEM FPRIME_APID 16 UINT", file=f)

def emit_tlm_trailer(f):
    if headers == "FPRIME":
        print("  ITEM FPRIME_CRC32 -32 32 UINT", file=f)
        # Always follows the payload at runtime, but COSMOS can't know that when
        # the payload is fixed size or ends in a variable sized item
        print("    OVERLAP", file=f)

def rest_of_packet_bits():
    """Bit size for an item that fills the rest of the packet (before the FPRIME CRC)."""
    return -32 if headers == "FPRIME" else 0

def emit_time_items(f):
    print("  APPEND_ITEM FPRIME_TIMEBASE 16 UINT", file=f)
    print("    STATE TB_NONE 0 # No time base has been established", file=f)
    print("    STATE TB_PROC_TIME 1 # Indicates time is processor cycle time. Not tied to external time", file=f)
    print("    STATE TB_WORKSTATION_TIME 2 # Time as reported on workstation where software is running", file=f)
    print("    STATE TB_DONT_CARE 0xFFFF", file=f)
    print("  APPEND_ITEM FPRIME_CONTEXT 8 UINT", file=f)
    print("  APPEND_ITEM FPRIME_TIME_SEC 32 UINT", file=f)
    print("  APPEND_ITEM FPRIME_TIME_USEC 32 UINT", file=f)

def emit_packet_time(f):
    print("  ITEM PACKET_TIME 0 0 DERIVED \"Python time based on FPRIME_TIME_SEC and FPRIME_TIME_USEC\"", file=f)
    print("    READ_CONVERSION openc3/conversions/unix_time_conversion.py FPRIME_TIME_SEC FPRIME_TIME_USEC", file=f)

def emit_bool_flag(f, name, description):
    print(f"  APPEND_ITEM {name} 8 UINT \"{description}\"", file=f)
    print("    STATE FALSE 0", file=f)
    print("    STATE TRUE 1", file=f)

def emit_container_id(f):
    print("  APPEND_ITEM CONTAINER_ID 32 UINT \"Data product container ID\"", file=f)
    for container in containers:
        print(f"    STATE \"{container['name']}\" {container['id']}", file=f)

def emit_record_value(f, record):
    annotation = clean_annotation(record.get("annotation", ""))
    if not record.get("array", False):
        emit_channel_value(f, "VALUE", record["type"], types, annotation)
        return
    print(f"  APPEND_ITEM COUNT {widths['size_store']} UINT \"Number of array elements\"", file=f)
    elem = record["type"]
    while elem["kind"] == "qualifiedIdentifier" and types[elem["name"]]["kind"] == "alias":
        elem = types[elem["name"]]["underlyingType"]
    if elem["kind"] in ("integer", "float", "bool"):
        if elem["kind"] == "float":
            data_type = "FLOAT"
        else:
            data_type = "INT" if elem.get("signed") else "UINT"
        print(f"  APPEND_ARRAY_ITEM VALUE {elem['size']} {data_type} 0 \"{annotation}\"", file=f)
        print(f"    VARIABLE_BIT_SIZE COUNT {elem['size']} 0", file=f)
    else:
        print(f"  APPEND_ITEM VALUE {rest_of_packet_bits()} BLOCK \"{annotation} (raw elements; decoded values are in the .json file)\"", file=f)

def emit_channel_value(f, name, t, types, annotation):
    kind = t["kind"]
    if kind == "qualifiedIdentifier":
        resolved = types[t["name"]]
        rkind = resolved["kind"]
        if rkind == "alias":
            emit_channel_value(f, name, resolved["underlyingType"], types, annotation)
            return
        if rkind == "struct":
            for mname, m in sorted(resolved["members"].items(), key=lambda kv: kv[1]["index"]):
                member_name = f"{name}_{mname}"
                if "size" in m:
                    # FPP member array, e.g. `vals: [3] U32`
                    member_array = {"size": m["size"], "elementType": m["type"]}
                    _emit_array_line(f, "APPEND_ARRAY_ITEM", member_name, member_array, types, m.get("annotation", ""), emit_channel_value)
                else:
                    emit_channel_value(f, member_name, m["type"], types, m.get("annotation", ""))
            return
        if rkind == "enum":
            states = {c["name"]: c["value"] for c in resolved["enumeratedConstants"]}
            rep = resolved["representationType"]
            ts = "INT" if rep["signed"] else "UINT"
            print(f"  APPEND_ITEM {name} {rep['size']} {ts} \"{annotation}\"", file=f)
            for key, value in states.items():
                print(f"    STATE {key} {value}", file=f)
            return
        if rkind == "array":
            _emit_array_line(f, "APPEND_ARRAY_ITEM", name, resolved, types, annotation, emit_channel_value)
            return
        raise RuntimeError(f"Unhandled typeDefinition kind {rkind}")
    if kind == "string":
        emit_variable_string(f, name, widths["size_store"], annotation)
        return
    if kind == "integer":
        ts = "INT" if t["signed"] else "UINT"
        print(f"  APPEND_ITEM {name} {t['size']} {ts} \"{annotation}\"", file=f)
        return
    if kind == "float":
        print(f"  APPEND_ITEM {name} {t['size']} FLOAT \"{annotation}\"", file=f)
        return
    if kind == "bool":
        print(f"  APPEND_ITEM {name} {t['size']} UINT \"{annotation}\"", file=f)
        print(f"    STATE FALSE 0", file=f)
        print(f"    STATE TRUE 1", file=f)
        return
    raise RuntimeError(f"Unhandled type kind {kind}")

def convert_event_format(fmt):
    def replace(m):
        spec = m.group(1)
        if spec == "":
            return "{}"
        if spec.startswith(":"):
            return "{" + spec + "}"
        return "{:" + spec + "}"
    return re.sub(r"\{([^}]*)\}", replace, fmt)

def convert_fprime_format(fmt, type_kind):
    def replace(m):
        spec = m.group(1)
        if spec == "":
            if type_kind == "integer":
                return "%d"
            elif type_kind == "float":
                return "%g"
            else:
                return "%s"
        if spec.startswith(":"):
            spec = spec[1:]
        return "%" + spec
    return re.sub(r"\{([^}]*)\}", replace, fmt)

def format_limits_line(limits, value_type):
    kind = value_type["kind"]
    if kind == "integer":
        size = value_type["size"]
        if value_type.get("signed"):
            lo, hi = -(2 ** (size - 1)), 2 ** (size - 1) - 1
        else:
            lo, hi = 0, 2 ** size - 1
    elif kind == "float":
        if value_type["size"] == 32:
            lo, hi = -3.4028235e38, 3.4028235e38
        else:
            lo, hi = -1.7976931348623157e308, 1.7976931348623157e308
    else:
        lo, hi = -1e30, 1e30
    high = limits.get("high", {})
    low = limits.get("low", {})
    red_high = high.get("red", hi)
    yellow_high = high.get("yellow", high.get("orange", red_high))
    red_low = low.get("red", lo)
    yellow_low = low.get("yellow", low.get("orange", red_low))
    return f"LIMITS DEFAULT 1 ENABLED {red_low} {yellow_low} {yellow_high} {red_high}"

first = True
cmd_path = os.path.join(base_dir, 'targets', target_name, 'cmd_tlm', 'cmd.txt')
os.makedirs(os.path.dirname(cmd_path), exist_ok=True)
with open(cmd_path, 'w') as f:
    print("# This is a file generated by fprime_parser.py", file=f)
    print("# Do not edit directly", file=f)
    print(file=f)    
    for command in commands:
        if first:
            first = False
        else:
            print(file=f)

        print(f"COMMAND <%= target_name %> {command["name"]} BIG_ENDIAN \"{command.get("annotation", "").replace('\n', ' ').replace('\r', '')}\"", file=f)
        if headers == "FPRIME":
            print("  APPEND_PARAMETER FPRIME_SYNC 32 UINT MIN MAX 0", file=f)
            print("  APPEND_PARAMETER FPRIME_SIZE 32 UINT MIN MAX 0", file=f)
            print("  APPEND_ID_PARAMETER FPRIME_PACKET_ID 32 UINT 0 0 0", file=f)
        else:
            print("  APPEND_PARAMETER CCSDS_VERSION 3 UINT 0 0 0", file=f)
            print("  APPEND_PARAMETER CCSDS_TYPE 1 UINT 1 1 1", file=f)
            print("  APPEND_PARAMETER CCSDS_SHF 1 UINT 0 0 0", file=f)
            print("  APPEND_ID_PARAMETER CCSDS_APID 11 UINT 0 0 0", file=f)
            print("  APPEND_PARAMETER CCSDS_SEQ_FLAGS 2 UINT MIN MAX 0", file=f)
            print("  APPEND_PARAMETER CCSDS_SEQ_CNT 14 UINT MIN MAX 0", file=f)
            print("  APPEND_PARAMETER CCSDS_LENGTH 16 UINT MIN MAX 0", file=f)
            print("  APPEND_PARAMETER FPRIME_APID 16 UINT 0 0 0", file=f)
        print(f"  APPEND_ID_PARAMETER FPRIME_OPCODE 32 UINT {command["opcode"]} {command["opcode"]} {command["opcode"]}", file=f)
        for param in command["formalParams"]:
            emit_command_param(f, param["name"], param["type"], types, param.get("annotation", ""))
        if headers == "FPRIME":
            print("  APPEND_PARAMETER FPRIME_CRC32 32 UINT MIN MAX 0", file=f)

tlm_path = os.path.join(base_dir, 'targets', target_name, 'cmd_tlm', 'tlm.txt')
os.makedirs(os.path.dirname(tlm_path), exist_ok=True)
with open(tlm_path, 'w') as f:
    print("# This is a file generated by fprime_parser.py", file=f)
    print("# Do not edit directly", file=f)
    print(file=f)
    print(f"TELEMETRY <%= target_name %> TELEMETRY BIG_ENDIAN \"Channelized Telemetry Packet\"", file=f)
    print("  SUBPACKETIZER fprime_subpacketizer.py", file=f)
    emit_tlm_header(f, 1)
    print(f"  APPEND_ITEM CHANNELS {rest_of_packet_bits()} BLOCK", file=f)
    emit_tlm_trailer(f)
    print(file=f)
    print(f"TELEMETRY <%= target_name %> EVENT BIG_ENDIAN \"Event Packet\"", file=f)
    emit_tlm_header(f, 2)
    print("  APPEND_ITEM FPRIME_EVENT_ID 32 UINT", file=f)
    emit_time_items(f)
    if headers == "FPRIME":
        print("  APPEND_ITEM FPRIME_EVENT_DATA -32 BLOCK", file=f)
        print("  ITEM FPRIME_CRC32 -32 32 UINT", file=f)
    else:
        print("  APPEND_ITEM FPRIME_EVENT_DATA 0 BLOCK", file=f)
    print("  ITEM FPRIME_EVENT_MESSAGE 0 0 DERIVED", file=f)
    print("    READ_CONVERSION fprime_event_conversion.py", file=f)

    for channel in channels:
        print(file=f)
        print(f"TELEMETRY <%= target_name %> {channel["name"]} BIG_ENDIAN \"{clean_annotation(channel.get("annotation", ""))}\"", file=f)
        print("  SUBPACKET", file=f)
        print(f"  APPEND_ID_ITEM FPRIME_CHANNEL_ID 32 UINT {channel['id']}", file=f)
        emit_time_items(f)

        channel_name = channel["name"].split(".")[-1]
        emit_channel_value(f, channel_name, channel["type"], types, channel.get("annotation", ""))
        value_type = resolve_value_type(channel["type"], types)
        if value_type is not None and "format" in channel:
            print(f"    FORMAT_STRING \"{convert_fprime_format(channel['format'], value_type['kind'])}\"", file=f)
        if value_type is not None and value_type["kind"] in ("integer", "float") and "limits" in channel:
            print(f"    {format_limits_line(channel['limits'], value_type)}", file=f)
        emit_packet_time(f)

    file_packets = [
        ("FILE_START", 0, "F Prime file downlink START packet"),
        ("FILE_DATA", 1, "F Prime file downlink DATA packet"),
        ("FILE_END", 2, "F Prime file downlink END packet"),
        ("FILE_CANCEL", 3, "F Prime file downlink CANCEL packet"),
    ]
    for name, file_type, description in file_packets:
        print(file=f)
        print(f"TELEMETRY <%= target_name %> {name} BIG_ENDIAN \"{description}\"", file=f)
        emit_tlm_header(f, FW_PACKET_FILE)
        print(f"  APPEND_ID_ITEM FILE_TYPE 8 UINT {file_type}", file=f)
        print("  APPEND_ITEM SEQUENCE_INDEX 32 UINT", file=f)
        if name == "FILE_START":
            print("  APPEND_ITEM FILE_SIZE 32 UINT \"File size in bytes\"", file=f)
            emit_variable_string(f, "SOURCE_PATH", 8, "Source path on the spacecraft")
            emit_variable_string(f, "DEST_PATH", 8, "Destination path")
        elif name == "FILE_DATA":
            print("  APPEND_ITEM BYTE_OFFSET 32 UINT", file=f)
            print("  APPEND_ITEM DATA_SIZE 16 UINT", file=f)
            print("  APPEND_ITEM DATA 0 BLOCK", file=f)
            print("    VARIABLE_BIT_SIZE DATA_SIZE 8 0", file=f)
        elif name == "FILE_END":
            print("  APPEND_ITEM CHECKSUM 32 UINT \"CFDP checksum of the file\"", file=f)
            print("    FORMAT_STRING \"0x%08X\"", file=f)
        emit_tlm_trailer(f)

    print(file=f)
    print("TELEMETRY <%= target_name %> DP_HEADER BIG_ENDIAN \"Data product header, synthesized by fprime_file_downlink_protocol.py\"", file=f)
    emit_tlm_header(f, FW_PACKET_DP)
    print("  APPEND_ID_ITEM DP_KIND 8 UINT 0", file=f)
    emit_container_id(f)
    emit_time_items(f)
    print("  APPEND_ITEM PRIORITY 32 UINT", file=f)
    print("  APPEND_ITEM PROC_TYPES 8 UINT \"Processing type bit mask\"", file=f)
    print("  APPEND_ITEM DP_STATE 8 UINT", file=f)
    print("    STATE UNTRANSMITTED 0", file=f)
    print("    STATE PARTIAL 1", file=f)
    print("    STATE TRANSMITTED 2", file=f)
    print("  APPEND_ITEM DATA_SIZE 64 UINT \"Record data size in bytes\"", file=f)
    emit_bool_flag(f, "HEADER_CRC_OK", "Header hash matched")
    emit_bool_flag(f, "DATA_CRC_OK", "Data hash matched")
    emit_bool_flag(f, "DECODE_OK", "All records decoded")
    print("  APPEND_ITEM RECORD_COUNT 32 UINT \"Number of records decoded\"", file=f)
    print(f"  APPEND_ITEM USER_DATA {widths['user_data_size'] * 8} BLOCK", file=f)
    emit_variable_string(f, "FILE_NAME", 8, "Downlinked data product file")
    emit_packet_time(f)
    emit_tlm_trailer(f)

    for record in records:
        print(file=f)
        print(f"TELEMETRY <%= target_name %> DP.{record['name']} BIG_ENDIAN \"{clean_annotation(record.get('annotation', ''))}\"", file=f)
        emit_tlm_header(f, FW_PACKET_DP)
        print("  APPEND_ID_ITEM DP_KIND 8 UINT 1", file=f)
        emit_container_id(f)
        emit_time_items(f)
        print(f"  APPEND_ID_ITEM RECORD_ID 32 UINT {record['id']}", file=f)
        emit_record_value(f, record)
        emit_packet_time(f)
        emit_tlm_trailer(f)

events_lookup = {}
for e in events:
    flat_params = []
    for p in e.get("formalParams", []):
        flat = flatten_type(p["type"], types)
        flat["name"] = p["name"]
        flat_params.append(flat)
    events_lookup[e["id"]] = {
        "name": e["name"],
        "severity": e["severity"],
        "format": convert_event_format(e.get("format", "")),
        "params": flat_params,
    }

events_repr = pprint.pformat(events_lookup, indent=2, width=120, sort_dicts=False)

CONVERSION_TEMPLATE = '''# This is a file generated by fprime_parser.py
# Do not edit directly

import struct

from openc3.conversions.conversion import Conversion


def _parse_int(data, offset, size, signed):
    code = {{8: "b", 16: "h", 32: "i", 64: "q"}}[size]
    if not signed:
        code = code.upper()
    val = struct.unpack_from(">" + code, data, offset)[0]
    return val, offset + size // 8


def _parse_float(data, offset, size):
    code = "f" if size == 32 else "d"
    val = struct.unpack_from(">" + code, data, offset)[0]
    return val, offset + size // 8


def _parse_string(data, offset):
    length, offset = _parse_int(data, offset, {size_store_bits}, False)
    s = bytes(data[offset:offset + length]).decode("utf-8", errors="replace")
    return s, offset + length


def _parse_param(data, offset, param):
    kind = param["kind"]
    if kind == "integer":
        return _parse_int(data, offset, param["size"], param.get("signed", False))
    if kind == "float":
        return _parse_float(data, offset, param["size"])
    if kind == "string":
        return _parse_string(data, offset)
    if kind == "bool":
        val, offset = _parse_int(data, offset, param.get("size", 8), False)
        return bool(val), offset
    if kind == "enum":
        rep = param["representationType"]
        val, offset = _parse_int(data, offset, rep["size"], rep.get("signed", False))
        states = param.get("states", {{}})
        return states.get(val, val), offset
    if kind == "array":
        elem = param["elementType"]
        items = []
        for _ in range(param["size"]):
            v, offset = _parse_param(data, offset, elem)
            items.append(v)
        return items, offset
    if kind == "struct":
        result = {{}}
        for m in param["members"]:
            v, offset = _parse_param(data, offset, m)
            result[m["name"]] = v
        return result, offset
    raise RuntimeError(f"Unhandled event param kind: {{kind}}")


EVENTS = {events}


class FprimeEventConversion(Conversion):
    def __init__(self):
        super().__init__()
        self.converted_type = "STRING"
        self.converted_bit_size = 0

    def call(self, value, packet, buffer):
        event_id = packet.read("FPRIME_EVENT_ID", "RAW", buffer)
        event = EVENTS.get(event_id)
        if event is None:
            return f"Unknown event id {{event_id}}"
        try:
            data = packet.read("FPRIME_EVENT_DATA", "RAW", buffer) or b""
            args = []
            offset = 0
            for p in event["params"]:
                v, offset = _parse_param(data, offset, p)
                args.append(v)
            return event["format"].format(*args)
        except Exception as exc:
            return f"Error formatting event {{event['name']}} (id={{event_id}}): {{exc}}"
'''

conversion_path = os.path.join(base_dir, 'targets', target_name, 'lib', 'fprime_event_conversion.py')
os.makedirs(os.path.dirname(conversion_path), exist_ok=True)
with open(conversion_path, 'w') as f:
    f.write(CONVERSION_TEMPLATE.format(events=events_repr, size_store_bits=widths["size_store"]))

DP_DICTIONARY_TEMPLATE = '''# This is a file generated by fprime_parser.py
# Do not edit directly

# Framework type widths in bits (user_data_size is in bytes)
WIDTHS = {widths}

CONTAINERS = {containers}

RECORDS = {records}
'''

dp_containers = {c["id"]: {"name": c["name"], "default_priority": c.get("defaultPriority")} for c in containers}
dp_records = {
    r["id"]: {"name": r["name"], "array": r.get("array", False), "type": flatten_type(r["type"], types)}
    for r in records
}

dp_dictionary_path = os.path.join(base_dir, 'targets', target_name, 'lib', 'fprime_dp_dictionary.py')
with open(dp_dictionary_path, 'w') as f:
    f.write(DP_DICTIONARY_TEMPLATE.format(
        widths=pprint.pformat(widths, sort_dicts=False),
        containers=pprint.pformat(dp_containers, indent=2, width=120, sort_dicts=False),
        records=pprint.pformat(dp_records, indent=2, width=120, sort_dicts=False),
    ))
