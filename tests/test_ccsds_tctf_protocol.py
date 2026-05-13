# Copyright 2025 OpenC3, Inc.
# All Rights Reserved.
#
# This file may only be used under the terms of a commercial license
# purchased from OpenC3, Inc.
#
# The development of this software was funded in-whole or in-part by MethaneSAT LLC.

import pytest

from ccsds_randomizer import CcsdsRandomizer
from ccsds_tctf_protocol import CcsdsTctfProtocol


class TestCcsdsTctfProtocol:
    """Test suite for CCSDS TCTF Protocol."""

    def test_with_randomization_no_error_control_bypass(self):
        """Test TCTF with randomization, no error control, bypass flag set."""
        protocol = CcsdsTctfProtocol(
            randomization=True, error_control=False, bypass=1, scid=31, vcid=32
        )

        # First frame
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        result, extra = protocol.write_data(data)

        expected_result = b"\x20\x1f\x80\x0c\x01" + data
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TC_MODE)
        expected = randomizer.apply(expected_result)
        assert result == expected
        assert extra is None

        # Second frame (sequence number increments)
        data = b"\x03\x04\x05\x06\x07\x08\x09\x0a"
        result, extra = protocol.write_data(data)

        expected_result = b"\x20\x1f\x80\x0c\x02" + data
        expected = randomizer.apply(expected_result)
        assert result == expected

    def test_no_randomization_no_error_control_bypass(self):
        """Test TCTF with no randomization, no error control, bypass flag set."""
        protocol = CcsdsTctfProtocol(
            randomization=False, error_control=False, bypass=1, scid=31, vcid=32
        )

        # First frame
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        result, extra = protocol.write_data(data)

        expected_result = b"\x20\x1f\x80\x0c\x01" + data
        assert result == expected_result
        assert extra is None

        # Second frame
        data = b"\x03\x04\x05\x06\x07\x08\x09\x0a"
        result, extra = protocol.write_data(data)

        expected_result = b"\x20\x1f\x80\x0c\x02" + data
        assert result == expected_result

    def test_with_randomization_error_control_no_bypass(self):
        """Test TCTF with randomization, error control, no bypass flag."""
        protocol = CcsdsTctfProtocol(
            randomization=True, error_control=True, bypass=0, scid=31, vcid=32
        )

        # First frame
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        result, _ = protocol.write_data(data)

        # Build expected frame
        expected_result = b"\x00\x1f\x80\x0e\x01" + data
        # Calculate CRC
        crc = protocol.crc16.calc(expected_result)
        expected_result = expected_result + crc.to_bytes(2, "big")
        # Apply randomization
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TC_MODE)
        expected = randomizer.apply(expected_result)

        assert result == expected

        # Second frame
        data = b"\x03\x04\x05\x06\x07\x08\x09\x0a"
        result, _ = protocol.write_data(data)

        expected_result = b"\x00\x1f\x80\x0e\x02" + data
        crc = protocol.crc16.calc(expected_result)
        expected_result = expected_result + crc.to_bytes(2, "big")
        expected = randomizer.apply(expected_result)

        assert result == expected

    def test_sequence_number_increment(self):
        """Test that sequence number increments and wraps at 255."""
        protocol = CcsdsTctfProtocol(
            randomization=False, error_control=False, bypass=1, scid=0, vcid=0
        )

        data = b"\x01\x02\x03"

        # Generate 256 frames to test wrapping
        for i in range(256):
            result, _ = protocol.write_data(data)
            # Sequence number is in byte 4 (0-indexed)
            seq_num = result[4]
            assert seq_num == ((i + 1) % 256)

    def test_data_too_large(self):
        """Test that protocol raises error for data that exceeds max length."""
        protocol = CcsdsTctfProtocol()

        # Create data that will exceed MAX_LENGTH_VALUE
        # Max length is 1023, which includes header (5 bytes) - 1
        # So max data is 1023 - 5 + 1 = 1019 bytes
        data = b"\x00" * 1020

        with pytest.raises(ValueError, match="Data length too large"):
            protocol.write_data(data)

    def test_header_format(self):
        """Test that header is formatted correctly."""
        protocol = CcsdsTctfProtocol(
            randomization=False,
            error_control=False,
            bypass=1,
            scid=0x3FF,  # Max 10-bit value
            vcid=0x3F,  # Max 6-bit value
        )

        data = b"\x01\x02\x03"
        result, _ = protocol.write_data(data)

        # Extract header fields
        byte0 = result[0]
        byte1 = result[1]
        byte2 = result[2]
        byte3 = result[3]
        byte4 = result[4]

        # Check VERSION (bits 7-6 of byte0) = 0
        version = (byte0 >> 6) & 0x03
        assert version == 0

        # Check BYPASS (bit 5 of byte0) = 1
        bypass = (byte0 >> 5) & 0x01
        assert bypass == 1

        # Check SCID (bits 1-0 of byte0 + all of byte1) = 0x3FF
        scid = ((byte0 & 0x03) << 8) | byte1
        assert scid == 0x3FF

        # Check VCID (bits 7-2 of byte2) = 0x3F
        vcid = (byte2 >> 2) & 0x3F
        assert vcid == 0x3F

        # Check LENGTH (bits 1-0 of byte2 + all of byte3)
        length = ((byte2 & 0x03) << 8) | byte3
        expected_length = 5 + len(data) - 1  # Header + data - 1
        assert length == expected_length

        # Check SEQ_NUM (byte4) = 1 (first frame)
        seq_num = byte4
        assert seq_num == 1

    def test_extra_parameter_passthrough(self):
        """Test that extra parameter is passed through unchanged."""
        protocol = CcsdsTctfProtocol(randomization=False, error_control=False)

        data = b"\x01\x02\x03"
        extra_data = {"metadata": "test", "count": 42}

        _, extra = protocol.write_data(data, extra_data)

        assert extra == extra_data
