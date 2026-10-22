# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Build the telemetry packets the plugin synthesizes for a decoded data product.

Each packet is framed like real telemetry with descriptor FW_PACKET_DP (5), so
COSMOS identifies it against the DP_HEADER / DP.<record> definitions generated
by fprime_parser.py. Payload layouts:

DP_HEADER : DP_KIND U8=0, CONTAINER_ID U32, TIMEBASE U16, CONTEXT U8, SEC U32, USEC U32,
            PRIORITY U32, PROC_TYPES U8, DP_STATE U8, DATA_SIZE U64, HEADER_CRC_OK U8,
            DATA_CRC_OK U8, DECODE_OK U8, RECORD_COUNT U32, USER_DATA, FILE_NAME_LENGTH U8, FILE_NAME
DP.<rec>  : DP_KIND U8=1, CONTAINER_ID U32, TIMEBASE U16, CONTEXT U8, SEC U32, USEC U32,
            RECORD_ID U32, record bytes exactly as serialized in the .fdp
"""

import struct

from fprime_framing import FW_PACKET_DP, frame

DP_KIND_HEADER = 0
DP_KIND_RECORD = 1


def _common(kind, header):
    return struct.pack(">BIHBII", kind, header.container_id, header.time_base, header.time_context,
                       header.seconds, header.useconds)


def build_dp_packets(headers, decoded, file_name):
    header = decoded.header
    name = file_name.encode("utf-8")[:255]
    header_payload = (
        _common(DP_KIND_HEADER, header)
        + struct.pack(">IBBQBBBI", header.priority, header.proc_types, header.dp_state, header.data_size,
                      int(decoded.header_crc_ok), int(decoded.data_crc_ok), int(decoded.error is None),
                      len(decoded.records))
        + header.user_data
        + bytes([len(name)]) + name
    )
    packets = [frame(headers, FW_PACKET_DP, header_payload)]
    for record in decoded.records:
        payload = _common(DP_KIND_RECORD, header) + struct.pack(">I", record.id) + record.raw
        try:
            packets.append(frame(headers, FW_PACKET_DP, payload))
        except ValueError:
            # Too large to frame (SPACE_PACKET limit is 64 KiB); its values are in the .json
            continue
    return packets
