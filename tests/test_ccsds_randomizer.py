# Copyright 2025 OpenC3, Inc.
# All Rights Reserved.
#
# This file may only be used under the terms of a commercial license
# purchased from OpenC3, Inc.
#
# The development of this software was funded in-whole or in-part by MethaneSAT LLC.

from ccsds_randomizer import CcsdsRandomizer


class TestCcsdsRandomizer:
    """Test suite for CCSDS Randomizer."""

    def test_tc_mode_table_values(self):
        """Test that TC mode generates correct lookup table values."""
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TC_MODE)
        assert randomizer.table[0] == 0xFF
        assert randomizer.table[1] == 0x39
        assert randomizer.table[2] == 0x9E
        assert randomizer.table[3] == 0x5A
        assert randomizer.table[4] == 0x68

    def test_tc_mode_roundtrip(self):
        """Test that applying randomization twice returns original data in TC mode."""
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TC_MODE)

        # Create test data (1-512)
        data = bytes(range(1, 256)) + bytes(range(1, 256)) + bytes([1])

        # Randomize
        result = randomizer.apply(data)
        assert result != data

        # De-randomize (apply again)
        result = randomizer.apply(result)
        assert result == data

    def test_tm_mode_table_values(self):
        """Test that TM mode generates correct lookup table values."""
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        assert randomizer.table[0] == 0xFF
        assert randomizer.table[1] == 0x48
        assert randomizer.table[2] == 0x0E
        assert randomizer.table[3] == 0xC0
        assert randomizer.table[4] == 0x9A

    def test_tm_mode_roundtrip(self):
        """Test that applying randomization twice returns original data in TM mode."""
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)

        # Create test data (1-512)
        data = bytes(range(1, 256)) + bytes(range(1, 256)) + bytes([1])

        # Randomize
        result = randomizer.apply(data)
        assert result != data

        # De-randomize (apply again)
        result = randomizer.apply(result)
        assert result == data

    def test_wrapping_at_table_length(self):
        """Test that randomizer wraps at TABLE_LENGTH."""
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TC_MODE)

        # Create data longer than TABLE_LENGTH
        data = bytes([0x42] * 300)

        result = randomizer.apply(data)

        # First 255 bytes should match table XOR with 0x42
        for i in range(CcsdsRandomizer.TABLE_LENGTH):
            assert result[i] == (0x42 ^ randomizer.table[i])

        # Bytes after TABLE_LENGTH should wrap
        for i in range(CcsdsRandomizer.TABLE_LENGTH, len(data)):
            table_index = i % CcsdsRandomizer.TABLE_LENGTH
            assert result[i] == (0x42 ^ randomizer.table[table_index])
