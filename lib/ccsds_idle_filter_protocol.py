# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

from openc3.interfaces.protocols.protocol import Protocol


class CcsdsIdleFilterProtocol(Protocol):
    """Drops CCSDS idle Space Packets (APID 0x7FF).

    F Prime 4.4's frameless ComCcsds.SpacePacket stack sends every aggregate idle-filled to the
    TM data field size, so the stream carries idle packets between real ones. In TM frames the
    TM frame protocol drops these itself.
    """

    IDLE_APID = 0x7FF

    def read_data(self, data, extra=None):
        if len(data) >= 2 and (int.from_bytes(data[0:2], "big") & 0x7FF) == self.IDLE_APID:
            return ("STOP", extra)
        return super().read_data(data, extra)
