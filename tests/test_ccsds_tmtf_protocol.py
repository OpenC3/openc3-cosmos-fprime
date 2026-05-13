# Copyright 2025 OpenC3, Inc.
# All Rights Reserved.
#
# This file may only be used under the terms of a commercial license
# purchased from OpenC3, Inc.
#
# The development of this software was funded in-whole or in-part by MethaneSAT LLC.

"""Tests for CCSDS TMTF Protocol."""

from ccsds_randomizer import CcsdsRandomizer
from ccsds_tmtf_protocol import CcsdsTmtfProtocol


class TestCcsdsTmtfProtocol:
    """Test suite for TMTF protocol."""

    def test_single_packet_with_idle(self):
        """Test reading a single CCSDS packet followed by encapsulation idle."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_200_packets_with_idle(self):
        """Test reading 200 CCSDS packets followed by encapsulation idle."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        protocol = CcsdsTmtfProtocol(31, allow_empty_data=True)
        num_packets = 200
        data = (
            b"\x01\xf0\x00\x00\x18\x00"
            + (ccsds_packet * num_packets)
            + (b"\xe0" * (2048 - 6 - (num_packets * len(ccsds_packet))))
        )
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

        for _ in range(num_packets - 1):
            result, extra = protocol.read_data(b"")
            assert result == ccsds_packet
            assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

        result, extra = protocol.read_data(b"")
        assert result == "STOP"
        assert extra is None

    def test_large_packet_across_frames(self):
        """Test reading 1 large CCSDS packet across multiple frames."""
        ccsds_packet1 = b"\x00\x00\xc0\x00\x10\x00" + (b"\x23" * 4097)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet1[0:2042]
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)

        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x01\x01\x1f\xff" + ccsds_packet1[2042:4084]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x02\x02\x1f\xff" + ccsds_packet1[4084:4103]
        data = data + (b"\xe0" * (2048 - len(data)))
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet1
        assert extra == {"VCID": 0, "MC_FRM_CNT": 2, "VC_FRM_CNT": 2}

    def test_two_large_packets_across_vcids(self):
        """Test reading 2 large CCSDS packets across different VCIDs."""
        ccsds_packet1 = b"\x00\x00\xc0\x00\x10\x00" + (b"\x23" * 4097)
        ccsds_packet2 = b"\x00\x00\xc0\x00\x10\x00" + (b"\x45" * 4097)
        protocol = CcsdsTmtfProtocol(31)
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)

        # VCID 1 - Frame 1
        data = b"\x01\xf2\x00\x00\x18\x00" + ccsds_packet1[0:2042]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        # VCID 2 - Frame 1
        data = b"\x01\xf4\x01\x00\x18\x00" + ccsds_packet2[0:2042]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        # VCID 1 - Frame 2
        data = b"\x01\xf2\x02\x01\x1f\xff" + ccsds_packet1[2042:4084]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        # VCID 2 - Frame 2
        data = b"\x01\xf4\x03\x01\x1f\xff" + ccsds_packet2[2042:4084]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        # VCID 1 - Frame 3 (complete)
        data = b"\x01\xf2\x04\x02\x1f\xff" + ccsds_packet1[4084:4103]
        data = data + (b"\xe0" * (2048 - len(data)))
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet1
        assert extra == {"VCID": 1, "MC_FRM_CNT": 4, "VC_FRM_CNT": 2}

        # VCID 2 - Frame 3 (complete)
        data = b"\x01\xf4\x05\x02\x1f\xff" + ccsds_packet2[4084:4103]
        data = data + (b"\xe0" * (2048 - len(data)))
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet2
        assert extra == {"VCID": 2, "MC_FRM_CNT": 5, "VC_FRM_CNT": 2}

    def test_two_large_packets_same_vcid(self):
        """Test reading 2 large CCSDS packets across frames on same VCID."""
        ccsds_packet1 = b"\x00\x00\xc0\x00\x10\x00" + (b"\x23" * 4097)
        ccsds_packet2 = b"\x00\x00\xc0\x00\x10\x00" + (b"\x45" * 4097)
        protocol = CcsdsTmtfProtocol(31)
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)

        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet1[0:2042]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x01\x01\x1f\xff" + ccsds_packet1[2042:4084]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x02\x02\x18\x13" + ccsds_packet1[4084:4103]
        data = data + ccsds_packet2[0:2023]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet1
        assert extra == {"VCID": 0, "MC_FRM_CNT": 2, "VC_FRM_CNT": 2}

        data = b"\x01\xf0\x03\x03\x1f\xff" + ccsds_packet2[2023:4065]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x04\x04\x1f\xff" + ccsds_packet2[4065:4103]
        data = data + (b"\xe0" * (2048 - len(data)))
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet2
        assert extra == {"VCID": 0, "MC_FRM_CNT": 4, "VC_FRM_CNT": 4}

    def test_first_header_pointer(self):
        """Test using the first header pointer to skip invalid data."""
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        ccsds_packet2 = b"\x00\x00\xc0\x00\x10\x00" + (b"\x45" * 4097)

        data = b"\x01\xf0\x00\x00\x18\x13" + (b"\x55" * 19)
        data = data + ccsds_packet2[0:2023]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x01\x01\x1f\xff" + ccsds_packet2[2023:4065]
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

        data = b"\x01\xf0\x02\x02\x1f\xff" + ccsds_packet2[4065:4103]
        data = data + (b"\xe0" * (2048 - len(data)))
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == ccsds_packet2
        assert extra == {"VCID": 0, "MC_FRM_CNT": 2, "VC_FRM_CNT": 2}

    def test_waits_for_full_frame(self):
        """Test that protocol waits for complete frame before processing."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        data = b"\x1a\xcf\xfc\x1d" + randomizer.apply(data)

        result, extra = protocol.read_data(data[0:1024])
        assert result == "STOP"
        assert extra is None

        result, extra = protocol.read_data(data[1024:])
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_version(self):
        """Test resynchronization on bad frame version."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\xff\xff\xff\xff\xff\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_scid(self):
        """Test resynchronization on bad SCID."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\x3f\xff\xff\xff\xff\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_ocf(self):
        """Test resynchronization on bad OCF flag."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\x01\xf1\xff\xff\xff\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_shf(self):
        """Test resynchronization on bad SHF flag."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\x01\xf0\x00\x00\xff\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_sync_flag(self):
        """Test resynchronization on bad SYNC_FLAG."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\x01\xf0\x00\x00\x7f\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_pkt_order_flag(self):
        """Test resynchronization on bad PKT_ORDER_FLAG."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\x01\xf0\x00\x00\x3f\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_resync_on_bad_seg_length_id(self):
        """Test resynchronization on bad SEG_LENGTH_ID."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14))
        bad_data = (
            b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(b"\x01\xf0\x00\x00\x17\xff")
            + b"\x1a\xcf\xfc\x1d"
            + randomizer.apply(data)
        )
        result, extra = protocol.read_data(bad_data)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_only_idle_data_frames(self):
        """Test handling frames with only idle data."""
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x1f\xfe" + (b"\x55" * (2048 - 6))
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

    def test_idle_apid_packets(self):
        """Test handling packets with idle APID."""
        ccsds_packet = b"\x07\xff\xc0\x00\x00\x01\x01"
        protocol = CcsdsTmtfProtocol(31)
        data = b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 13))
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(data))
        assert result == "STOP"
        assert extra is None

    def test_single_packet_with_crc(self):
        """Test reading a single CCSDS packet from a frame with error control CRC."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        protocol = CcsdsTmtfProtocol(31, error_control=True)
        # 2048-byte frame: 6 header + packet + idle fill, ending with 2-byte CRC.
        frame_no_crc = (
            b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14 - 2))
        )
        crc = protocol.crc16.calc(frame_no_crc)
        frame = frame_no_crc + crc.to_bytes(2, "big")
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        result, extra = protocol.read_data(b"\x1a\xcf\xfc\x1d" + randomizer.apply(frame))
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

    def test_crc_mismatch_causes_resync(self):
        """Test that a frame with a corrupted CRC is discarded and the next good frame is recovered."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        protocol = CcsdsTmtfProtocol(31, error_control=True)
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)

        # Bad frame: valid header but wrong CRC bytes appended.
        bad_frame_no_crc = (
            b"\x01\xf0\x00\x00\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14 - 2))
        )
        bad_frame = bad_frame_no_crc + b"\xde\xad"  # Wrong CRC

        # Good frame: frame counters incremented (next MC_FRM_CNT = 1, VC_FRM_CNT = 1).
        good_frame_no_crc = (
            b"\x01\xf0\x01\x01\x18\x00" + ccsds_packet + (b"\xe0" * (2048 - 14 - 2))
        )
        good_crc = protocol.crc16.calc(good_frame_no_crc)
        good_frame = good_frame_no_crc + good_crc.to_bytes(2, "big")

        stream = (
            b"\x1a\xcf\xfc\x1d" + randomizer.apply(bad_frame)
            + b"\x1a\xcf\xfc\x1d" + randomizer.apply(good_frame)
        )
        result, extra = protocol.read_data(stream)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 1, "VC_FRM_CNT": 1}

    def test_multiple_packets_with_crc(self):
        """Test reading multiple CCSDS packets across two CRC-protected frames."""
        ccsds_packet = b"\x00\x00\xc0\x00\x00\x01\x01\x02"
        protocol = CcsdsTmtfProtocol(31, error_control=True, allow_empty_data=True)
        randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)

        # Two packets per frame for variety.
        frame1_no_crc = (
            b"\x01\xf0\x00\x00\x18\x00"
            + (ccsds_packet * 2)
            + (b"\xe0" * (2048 - 6 - 2 * len(ccsds_packet) - 2))
        )
        frame1 = frame1_no_crc + protocol.crc16.calc(frame1_no_crc).to_bytes(2, "big")

        frame2_no_crc = (
            b"\x01\xf0\x01\x01\x18\x00"
            + (ccsds_packet * 2)
            + (b"\xe0" * (2048 - 6 - 2 * len(ccsds_packet) - 2))
        )
        frame2 = frame2_no_crc + protocol.crc16.calc(frame2_no_crc).to_bytes(2, "big")

        stream = (
            b"\x1a\xcf\xfc\x1d" + randomizer.apply(frame1)
            + b"\x1a\xcf\xfc\x1d" + randomizer.apply(frame2)
        )

        result, extra = protocol.read_data(stream)
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

        result, extra = protocol.read_data(b"")
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 0, "VC_FRM_CNT": 0}

        result, extra = protocol.read_data(b"")
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 1, "VC_FRM_CNT": 1}

        result, extra = protocol.read_data(b"")
        assert result == ccsds_packet
        assert extra == {"VCID": 0, "MC_FRM_CNT": 1, "VC_FRM_CNT": 1}

        result, extra = protocol.read_data(b"")
        assert result == "STOP"
        assert extra is None
