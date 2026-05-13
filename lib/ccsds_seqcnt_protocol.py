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

    def write_packet(self, packet):
        packet.write(self.field_name, self.seq_num)
        self.seq_num += 1
        return packet
