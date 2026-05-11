import json
import os
import pprint
import re
import sys

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} <target_name> <path_to_Dictionary.json>", file=sys.stderr)
    sys.exit(1)

target_name = sys.argv[1]
json_path = sys.argv[2]

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


data = None
with open(json_path) as file:
    data = json.load(file)

framework_version = data["metadata"]["frameworkVersion"]
major_version = framework_version[1]

types = {}

for type in data["typeDefinitions"]:
    types[type['qualifiedName']] = type

commands = data["commands"]
events = data["events"]
channels = data["telemetryChannels"]

first = True
cmd_path = os.path.join(base_dir, 'targets', target_name, 'cmd_tlm', 'cmd.txt')
os.makedirs(os.path.dirname(cmd_path), exist_ok=True)
with open(cmd_path, 'w') as f:
    for command in commands:
        if first:
            first = False
        else:
            print(file=f)

        print(f"COMMAND <%= target_name %> {command["name"]} BIG_ENDIAN \"{command.get("annotation", "")}\"", file=f)
        print("  APPEND_PARAMETER FPRIME_SYNC 32 UINT MIN MAX 0", file=f)
        print("  APPEND_PARAMETER FPRIME_SIZE 32 UINT MIN MAX 0", file=f)
        print("  APPEND_ID_PARAMETER FPRIME_PACKET_ID 32 UINT 0 0 0", file=f)
        print(f"  APPEND_ID_PARAMETER FPRIME_OPCODE 32 UINT {command["opcode"]} {command["opcode"]} {command["opcode"]}", file=f)
        for param in command["formalParams"]:
            type = param["type"]
            type_name = type["name"]
            type_kind = type["kind"]
            if type_kind == "qualifiedIdentifier":
                type = types[type_name]
                if type["kind"] == "enum":
                    states = {}
                    for constant in type['enumeratedConstants']:
                        states[constant['name']] = constant['value']
                    default = states[type['default'].split('.')[-1]]
                    if type["representationType"]['signed']:
                        print(f"  APPEND_PARAMETER {param["name"]} {type["representationType"]["size"]} INT MIN MAX {default} \"{param.get("annotation", "")}\"", file=f)
                    else:
                        print(f"  APPEND_PARAMETER {param["name"]} {type["representationType"]["size"]} UINT MIN MAX {default} \"{param.get("annotation", "")}\"", file=f)
                    for key, value in states.items():
                        print(f"    STATE {key} {value}", file=f)
                elif type["kind"] == "array":
                    if type['elementType']['kind'] == 'integer':
                        if type['elementType']['signed']:
                            print(f"  APPEND_ARRAY_PARAMETER {param["name"]} {type["elementType"]["size"]} INT {type["elementType"]["size"] * type['size']} \"{param.get("annotation", "")}\"", file=f)
                        else:
                            print(f"  APPEND_ARRAY_PARAMETER {param["name"]} {type["elementType"]["size"]} UINT {type["elementType"]["size"] * type['size']} \"{param.get("annotation", "")}\"", file=f)
                    elif type['elementType']['kind'] == 'float':
                        print(f"  APPEND_ARRAY_PARAMETER {param["name"]} {type["elementType"]["size"]} FLOAT {type["elementType"]["size"] * type['size']} \"{param.get("annotation", "")}\"", file=f)
                    elif type['elementType']['kind'] == 'string':
                        print(f"  APPEND_ARRAY_PARAMETER {param["name"]} {type["elementType"]["size"]} STRING {type["elementType"]["size"] * type['size']} \"{param.get("annotation", "")}\"", file=f)
                    elif type['elementType']['kind'] == 'bool':
                        print(f"  APPEND_ARRAY_PARAMETER {param["name"]} {type["elementType"]["size"]} UINT {type["elementType"]["size"] * type['size']} \"{param.get("annotation", "")}\"", file=f)
                        print(f"    STATE FALSE 0", file=f)
                        print(f"    STATE TRUE 1", file=f)
                    else:
                        raise RuntimeError(f"Unhandled element kind {type['elementType']['kind']}")
                else:
                    raise RuntimeError(f"Unhandled element kind {type['kind']}")
            elif type_kind == "string":
                print(f"  APPEND_PARAMETER {param["name"]} {type["size"] * 8} STRING \"\" \"{param.get("annotation", "")}\"", file=f)
            elif type_kind == "integer":
                if type["signed"]:
                    print(f"  APPEND_PARAMETER {param["name"]} {type["size"]} INT MIN MAX 0 \"{param.get("annotation", "")}\"", file=f)
                else:
                    print(f"  APPEND_PARAMETER {param["name"]} {type["size"]} UINT MIN MAX 0 \"{param.get("annotation", "")}\"", file=f)
            elif type_kind == "float":
                print(f"  APPEND_PARAMETER {param["name"]} {type["size"]} FLOAT MIN MAX 0 \"{param.get("annotation", "")}\"", file=f)
            elif type_kind == "bool":
                print(f"  APPEND_PARAMETER {param["name"]} {type["size"]} UINT 0 1 0 \"{param.get("annotation", "")}\"", file=f)
                print(f"    STATE FALSE 0", file=f)
                print(f"    STATE TRUE 1", file=f)
            else:
                raise RuntimeError(f"Unhandled element kind {type_kind}")
        print("  APPEND_PARAMETER FPRIME_CRC32 32 UINT MIN MAX 0", file=f)

tlm_path = os.path.join(base_dir, 'targets', target_name, 'cmd_tlm', 'tlm.txt')
os.makedirs(os.path.dirname(tlm_path), exist_ok=True)
with open(tlm_path, 'w') as f:
    print(f"TELEMETRY <%= target_name %> TELEMETRY BIG_ENDIAN \"Channelized Telemetry Packet\"", file=f)
    print("  SUBPACKETIZER fprime_subpacketizer.py", file=f)
    print("  APPEND_ITEM FPRIME_SYNC 32 UINT", file=f)    
    print("  APPEND_ITEM FPRIME_SIZE 32 UINT", file=f)
    print("  APPEND_ID_ITEM FPRIME_PACKET_ID 32 UINT 1", file=f)
    print("  APPEND_ITEM CHANNELS -32 BLOCK", file=f)
    print("  ITEM FPRIME_CRC32 -32 32 UINT", file=f)
    print(file=f)
    print(f"TELEMETRY <%= target_name %> EVENT BIG_ENDIAN \"Channelized Telemetry Packet\"", file=f)
    print("  APPEND_ITEM FPRIME_SYNC 32 UINT", file=f)    
    print("  APPEND_ITEM FPRIME_SIZE 32 UINT", file=f)
    print("  APPEND_ID_ITEM FPRIME_PACKET_ID 32 UINT 2", file=f)
    print("  APPEND_ITEM FPRIME_EVENT_ID 32 UINT", file=f)
    print("  APPEND_ITEM FPRIME_TIMEBASE 16 UINT", file=f)
    print("    STATE TB_NONE 0 # No time base has been established", file=f)
    print("    STATE TB_PROC_TIME 1 # Indicates time is processor cycle time. Not tied to external time", file=f)
    print("    STATE TB_WORKSTATION_TIME 2 # Time as reported on workstation where software is running", file=f)
    print("    STATE TB_DONT_CARE 0xFFFF", file=f)
    print("  APPEND_ITEM FPRIME_CONTEXT 8 UINT", file=f)
    print("  APPEND_ITEM FPRIME_TIME_SEC 32 UINT", file=f)
    print("  APPEND_ITEM FPRIME_TIME_USEC 32 UINT", file=f)
    print("  APPEND_ITEM FPRIME_EVENT_DATA -32 BLOCK", file=f)
    print("  ITEM FPRIME_CRC32 -32 32 UINT", file=f)
    print("  ITEM FPRIME_EVENT_MESSAGE 0 0 DERIVED", file=f)
    print("    READ_CONVERSION fprime_event_conversion.py", file=f)

    for channel in channels:
        print(file=f)
        print(f"TELEMETRY <%= target_name %> {channel["name"]} BIG_ENDIAN \"{channel.get("annotation", "")}\"", file=f)
        print("  SUBPACKET", file=f)
        print(f"  APPEND_ID_ITEM FPRIME_CHANNEL_ID 32 UINT {channel['id']}", file=f)
        print("  APPEND_ITEM FPRIME_TIMEBASE 16 UINT", file=f)
        print("    STATE TB_NONE 0 # No time base has been established", file=f)
        print("    STATE TB_PROC_TIME 1 # Indicates time is processor cycle time. Not tied to external time", file=f)
        print("    STATE TB_WORKSTATION_TIME 2 # Time as reported on workstation where software is running", file=f)
        print("    STATE TB_DONT_CARE 0xFFFF", file=f)
        print("  APPEND_ITEM FPRIME_CONTEXT 8 UINT", file=f)
        print("  APPEND_ITEM FPRIME_TIME_SEC 32 UINT", file=f)
        print("  APPEND_ITEM FPRIME_TIME_USEC 32 UINT", file=f)

        type = channel["type"]
        type_name = type["name"]
        type_kind = type["kind"]
        channel_name = channel["name"].split(".")[-1]
        if type_kind == "qualifiedIdentifier":
            type = types[type_name]
            if type["kind"] == "enum":
                states = {}
                for constant in type['enumeratedConstants']:
                    states[constant['name']] = constant['value']
                default = states[type['default'].split('.')[-1]]
                if type["representationType"]['signed']:
                    print(f"  APPEND_ITEM {channel_name} {type["representationType"]["size"]} INT \"{channel.get("annotation", "")}\"", file=f)
                else:
                    print(f"  APPEND_ITEM {channel_name} {type["representationType"]["size"]} UINT \"{channel.get("annotation", "")}\"", file=f)
                for key, value in states.items():
                    print(f"    STATE {key} {value}", file=f)
            elif type["kind"] == "array":
                if type['elementType']['kind'] == 'integer':
                    if type['elementType']['signed']:
                        print(f"  APPEND_ARRAY_ITEM {channel_name} {type["elementType"]["size"]} INT {type["elementType"]["size"] * type['size']} \"{channel.get("annotation", "")}\"", file=f)
                    else:
                        print(f"  APPEND_ARRAY_ITEM {channel_name} {type["elementType"]["size"]} UINT {type["elementType"]["size"] * type['size']} \"{channel.get("annotation", "")}\"", file=f)
                elif type['elementType']['kind'] == 'float':
                    print(f"  APPEND_ARRAY_ITEM {channel_name} {type["elementType"]["size"]} FLOAT {type["elementType"]["size"] * type['size']} \"{channel.get("annotation", "")}\"", file=f)
                elif type['elementType']['kind'] == 'string':
                    print(f"  APPEND_ARRAY_ITEM {channel_name} {type["elementType"]["size"]} STRING {type["elementType"]["size"] * type['size']} \"{channel.get("annotation", "")}\"", file=f)
                elif type['elementType']['kind'] == 'bool':
                    print(f"  APPEND_ARRAY_ITEM {channel_name} {type["elementType"]["size"]} UINT {type["elementType"]["size"] * type['size']} \"{channel.get("annotation", "")}\"", file=f)
                    print(f"    STATE FALSE 0", file=f)
                    print(f"    STATE TRUE 1", file=f)
                else:
                    raise RuntimeError(f"Unhandled element kind {type['elementType']['kind']}")
            else:
                raise RuntimeError(f"Unhandled element kind {type['kind']}")
        elif type_kind == "string":
            print(f"  APPEND_ITEM {channel_name}_LENGTH 32 UINT", file=f)
            print(f"  APPEND_ITEM {channel_name} {type["size"] * 8} STRING \"{channel.get("annotation", "")}\"", file=f)
            print(f"    VARIABLE_BIT_SIZE {channel_name}_LENGTH 8 0", file=f)
        elif type_kind == "integer":
            if type["signed"]:
                print(f"  APPEND_ITEM {channel_name} {type["size"]} INT \"{channel.get("annotation", "")}\"", file=f)
            else:
                print(f"  APPEND_ITEM {channel_name} {type["size"]} UINT \"{channel.get("annotation", "")}\"", file=f)
        elif type_kind == "float":
            print(f"  APPEND_ITEM {channel_name} {type["size"]} FLOAT \"{channel.get("annotation", "")}\"", file=f)
        elif type_kind == "bool":
            print(f"  APPEND_ITEM {channel_name} {type["size"]} UINT \"{channel.get("annotation", "")}\"", file=f)
            print(f"    STATE FALSE 0", file=f)
            print(f"    STATE TRUE 1", file=f)
        else:
            raise RuntimeError(f"Unhandled element kind {type_kind}")
        if "format" in channel:
            print(f"    FORMAT_STRING \"{convert_fprime_format(channel['format'], type_kind)}\"", file=f)
        if "limits" in channel:
            value_type = None
            if type_kind == "qualifiedIdentifier" and type["kind"] == "enum":
                value_type = type["representationType"]
            elif type_kind in ("integer", "float"):
                value_type = type
            if value_type is not None:
                print(f"    {format_limits_line(channel['limits'], value_type)}", file=f)
        print("  ITEM PACKET_TIME 0 0 DERIVED \"Python time based on FPRIME_TIME_SEC and FPRIME_TIME_USEC\"", file=f)
        print("    READ_CONVERSION openc3/conversions/unix_time_conversion.py FPRIME_TIME_SEC FPRIME_TIME_USEC", file=f)

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

CONVERSION_TEMPLATE = '''import struct

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
    length, offset = _parse_int(data, offset, 32, False)
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
    f.write(CONVERSION_TEMPLATE.format(events=events_repr))
