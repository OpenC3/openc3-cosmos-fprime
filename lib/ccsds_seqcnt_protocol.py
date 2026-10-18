# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license. 
# See LICENSE.md file in the project root for details.

from openc3.interfaces.protocols.protocol import Protocol

class CcsdsSeqcntProtocol(Protocol):
    def __init__(
        self,
        field_name = "CCSDS_SEQ_CNT",
        allow_empty_data = None,
    ):
        super().__init__(allow_empty_data)
        self.field_name = field_name
        self.seq_num = 0
        self.apid_seq_nums = {}

    def write_packet(self, packet):
        # CCSDS counts sequence per APID; packets without an APID share one counter
        if "CCSDS_APID" in packet.items:
            apid = packet.read("CCSDS_APID")
            seq_num = self.apid_seq_nums.get(apid, 0)
            self.apid_seq_nums[apid] = (seq_num + 1) & 0x3FFF
        else:
            seq_num = self.seq_num
            self.seq_num = (seq_num + 1) & 0x3FFF
        packet.write(self.field_name, seq_num)
        return packet
