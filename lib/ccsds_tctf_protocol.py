# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# Licensed under the MIT license. 
# See LICENSE.md file in the project root for details.

import struct
from typing import Any

from openc3.config.config_parser import ConfigParser
from openc3.interfaces.protocols.protocol import Protocol
from openc3.packets.structure import Structure
from openc3.utilities.crc import Crc16

from ccsds_randomizer import CcsdsRandomizer


class CcsdsTctfProtocol(Protocol):
    """CCSDS Telecommand Transfer Frame (TCTF) Protocol.

    Implements CCSDS 232.0-B-3 TC Space Data Link Protocol.
    Provides frame header generation with optional randomization and CRC.
    """

    MAX_LENGTH_VALUE = 1023

    def __init__(
        self,
        randomization: bool | str = True,
        error_control: bool | str = False,
        bypass: int | str = 1,
        scid: int | str = 0,
        vcid: int | str = 0,
        allow_empty_data: bool | None = None,
    ) -> None:
        """Initialize TCTF protocol handler.

        Args:
            randomization: Enable pseudo-random sequence application
            error_control: Enable CRC-16 error control field
            bypass: Bypass flag (0 or 1)
            scid: Spacecraft ID (10 bits, 0-1023)
            vcid: Virtual Channel ID (6 bits, 0-63)
            allow_empty_data: Whether to allow empty data frames (reserved for compatibility)
        """
        super().__init__(allow_empty_data)
        self.randomization = ConfigParser.handle_true_false(randomization)
        self.error_control = ConfigParser.handle_true_false(error_control)

        # Build header structure
        self.header = Structure("BIG_ENDIAN")
        self.header.append_item("VERSION", 2, "UINT")
        self.header.append_item("BYPASS", 1, "UINT")
        self.header.append_item("CTRL_CMD_FLAG", 1, "UINT")
        self.header.append_item("RESERVED", 2, "UINT")
        self.header.append_item("SCID", 10, "UINT")
        self.header.append_item("VCID", 6, "UINT")
        self.header.append_item("LENGTH", 10, "UINT")
        self.header.append_item("SEQ_NUM", 8, "UINT", None, "BIG_ENDIAN", "TRUNCATE")

        # Initialize header values
        self.header.write("VERSION", 0)
        self.header.write("BYPASS", int(str(bypass), 0))
        self.header.write("CTRL_CMD_FLAG", 0)
        self.header.write("RESERVED", 0)
        self.header.write("SCID", int(str(scid), 0))
        self.header.write("VCID", int(str(vcid), 0))
        self.header.write("LENGTH", 0)
        self.header.write("SEQ_NUM", 0)

        self.seq_num = 0
        self.crc16 = Crc16()
        self.randomizer = CcsdsRandomizer(CcsdsRandomizer.TC_MODE)

    def write_data(self, data: bytes, extra: Any = None) -> tuple[bytes, Any]:
        """Encode data into a TCTF frame.

        Args:
            data: Command data to encode
            extra: Optional extra data to pass through

        Returns:
            Tuple of (encoded TCTF frame, extra data)

        Raises:
            ValueError: If data length exceeds maximum frame length
        """
        self.seq_num += 1
        self.header.write("SEQ_NUM", self.seq_num)

        length = 5 + len(data) - 1
        if self.error_control:
            length += 2

        if length > self.MAX_LENGTH_VALUE:
            raise ValueError(f"Data length too large for TC Transfer Frame: {length}")

        self.header.write("LENGTH", length)
        result = bytes(self.header.buffer) + data

        if self.error_control:
            crc = self.crc16.calc(result)
            result += struct.pack(">H", crc)

        if self.randomization:
            result = self.randomizer.apply(result)

        return result, extra
