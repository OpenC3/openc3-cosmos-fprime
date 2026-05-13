# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license. 
# See LICENSE.md file in the project root for details.

class CcsdsRandomizer:
    """CCSDS Randomizer for TC and TM data.

    Implements pseudo-random sequence generation per:
    - CCSDS 231.0-B-3 (TC mode)
    - CCSDS 131.0-B-3 (TM mode)
    """

    TABLE_LENGTH = 255
    TC_MODE = True
    TM_MODE = False
    INITIAL_STATE = 0xFF
    BITS_PER_BYTE = 8
    BIT_MASK_1 = 0x01
    BIT_MASK_2 = 0x02
    BIT_MASK_3 = 0x04
    BIT_MASK_4 = 0x08
    BIT_MASK_5 = 0x10
    BIT_MASK_6 = 0x20
    BIT_MASK_7 = 0x40
    BIT_MASK_8 = 0x80
    STATE_MASK = 0xFE

    def __init__(self, mode: bool = TC_MODE) -> None:
        """Initialize randomizer.

        Args:
            mode: True for TC (telecommand) mode, False for TM (telemetry) mode
        """
        self.mode = mode
        self.table = self._build_lookup_table(mode)

    def apply(self, data: bytes) -> bytes:
        """Apply pseudo-random sequence to data (XOR operation).

        Applying twice returns the original data (XOR is reversible).

        Args:
            data: Data to randomize/derandomize

        Returns:
            Randomized/derandomized data
        """
        result = bytearray()
        index = 0

        for byte in data:
            result.append(byte ^ self.table[index])
            index += 1
            if index >= self.TABLE_LENGTH:
                index = 0

        return bytes(result)

    def _build_lookup_table(self, is_tc_mode: bool) -> list[int]:
        """Build pseudo-random sequence lookup table.

        Based on CCSDS 231.0-B-3 (TC mode) and CCSDS 131.0-B-3 (TM mode).

        Args:
            is_tc_mode: True for TC mode, False for TM mode

        Returns:
            Lookup table with TABLE_LENGTH entries
        """
        table = []
        state = self.INITIAL_STATE

        for _ in range(self.TABLE_LENGTH):
            table.append(state)

            # Generate next 8 bits
            for _ in range(self.BITS_PER_BYTE):
                bit8 = state & self.BIT_MASK_1
                bit7 = ((state & self.BIT_MASK_2) >> 1) & self.BIT_MASK_1
                bit6 = ((state & self.BIT_MASK_3) >> 2) & self.BIT_MASK_1
                bit5 = ((state & self.BIT_MASK_4) >> 3) & self.BIT_MASK_1
                bit4 = ((state & self.BIT_MASK_5) >> 4) & self.BIT_MASK_1
                bit3 = ((state & self.BIT_MASK_6) >> 5) & self.BIT_MASK_1
                bit2 = ((state & self.BIT_MASK_7) >> 6) & self.BIT_MASK_1
                bit1 = ((state & self.BIT_MASK_8) >> 7) & self.BIT_MASK_1

                if is_tc_mode:
                    next_bit = bit1 ^ bit2 ^ bit3 ^ bit4 ^ bit5 ^ bit7
                else:  # TM mode
                    next_bit = bit1 ^ bit4 ^ bit6 ^ bit8

                state = next_bit | ((state << 1) & self.STATE_MASK)

        return table
