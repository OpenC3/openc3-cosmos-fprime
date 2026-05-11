import json

data = None
with open("/Users/ryanmelt/Development/fprime/MyProject/build-artifacts/Darwin/ServerDeployment/dict/ServerDeploymentTopologyDictionary.json") as file:
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
with open('../targets/FPRIME/cmd_tlm/cmd.txt', 'w') as f:
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

with open('../targets/FPRIME/cmd_tlm/tlm.txt', 'w') as f:
    print(f"TELEMETRY <%= target_name %> TELEMETRY BIG_ENDIAN \"Channelized Telemetry Packet\"", file=f)
    print("  SUBPACKETIZER fprime_subpacketizer.py", file=f)
    print("  APPEND_ITEM FPRIME_SYNC 32 UINT", file=f)    
    print("  APPEND_ITEM FPRIME_SIZE 32 UINT", file=f)
    print("  APPEND_ID_ITEM FPRIME_PACKET_ID 32 UINT 1", file=f)
    print("  APPEND_ITEM CHANNELS -32 BLOCK", file=f)
    print("  ITEM FPRIME_CRC32 -32 32 UINT", file=f)

    print(f"TELEMETRY <%= target_name %> TELEMETRY BIG_ENDIAN \"Channelized Telemetry Packet\"", file=f)
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
    print("    READ_CONVERSION fprime_event_conversion.py")

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
        print("  ITEM PACKET_TIME 0 0 DERIVED \"Python time based on FPRIME_TIME_SEC and FPRIME_TIME_USEC\"", file=f)
        print("    READ_CONVERSION openc3/conversions/unix_time_conversion.py FPRIME_TIME_SEC FPRIME_TIME_USEC", file=f)

#      "format" : "{} us",
