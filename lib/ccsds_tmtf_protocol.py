# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license. 
# See LICENSE.md file in the project root for details.

"""
CCSDS TM Transfer Frame (TMTF) Protocol Implementation.

This module implements the CCSDS 132.0-B-2 TM Transfer Frame protocol for
extracting telemetry packets from transfer frames.
"""

from typing import Literal, cast

from openc3.config.config_parser import ConfigParser
from openc3.interfaces.protocols.burst_protocol import BurstProtocol
from openc3.packets.packet import Packet
from openc3.packets.structure import Structure
from openc3.utilities.logger import Logger
from openc3.utilities.crc import Crc16

from ccsds_randomizer import CcsdsRandomizer


class CcsdsTmtfProtocol(BurstProtocol):
    """
    CCSDS TM Transfer Frame Protocol.

    Extracts CCSDS telemetry packets from TM Transfer Frames with support for:
    - Multiple virtual channels (VCIDs)
    - Packet spanning across frames
    - Optional pseudo-randomization
    - Frame synchronization and validation
    - Encapsulation idle byte handling
    """

    MAX_FRAME_LENGTH = 2048
    ONLY_IDLE_DATA = 0x7FE
    NO_FIRST_HEADER = 0x7FF
    IDLE_APID = 0x7FF
    ENCAPSULATION_IDLE_BYTE_STRING = b"\xe0"
    MINIMUM_CCSDS_PACKET_BYTES = 7
    NUM_VIRTUAL_CHANNELS = 8

    # CCSDS packet type constants
    TELEMETRY = 0
    COMMAND = 1
    LENGTH_FIELD_OFFSET = 7

    def __init__(
        self,
        scid: int | str,
        frame_length: int | str = MAX_FRAME_LENGTH,
        randomization: bool | str = True,
        discard_leading_bytes: int | str = 0,
        sync_pattern: str = "0x1ACFFC1D",
        fill_fields: bool | str = True,
        error_control: bool = False,
        allow_empty_data: bool | None = None,
    ) -> None:
        """
        Initialize the TMTF protocol.

        Args:
            scid: Spacecraft ID (10-bit value)
            frame_length: Frame length in bytes (not including sync pattern)
            randomization: Enable pseudo-randomization
            discard_leading_bytes: Number of bytes to discard from packet data
            sync_pattern: Sync pattern as hex string (e.g., "0x1ACFFC1D")
            fill_fields: Fill required fields when writing packets
            allow_empty_data: Whether to allow empty data frames
        """
        # Initialize parent BurstProtocol
        super().__init__(
            discard_leading_bytes, sync_pattern, fill_fields, allow_empty_data
        )

        # Parse and validate parameters
        self.scid = int(str(scid), 0)
        self.frame_length = int(str(frame_length), 0)  # Does not include sync pattern
        if self.frame_length <= 0 or self.frame_length > self.MAX_FRAME_LENGTH:
            raise ValueError(f"Invalid Frame Length {self.frame_length}")
        sync_len = len(self.sync_pattern) if self.sync_pattern else 0
        self.frame_with_sync_length = self.frame_length + sync_len
        self.randomization = ConfigParser.handle_true_false(randomization)
        self.error_control = ConfigParser.handle_true_false(error_control)

        # Create header structure for frame parsing
        self.header = Structure("BIG_ENDIAN")
        self.header.append_item("VERSION", 2, "UINT")
        self.header.append_item("SCID", 10, "UINT")
        self.header.append_item("VCID", 3, "UINT")
        self.header.append_item("OCF_FLAG", 1, "UINT")
        self.header.append_item("MC_FRM_CNT", 8, "UINT", None, "BIG_ENDIAN", "TRUNCATE")
        self.header.append_item("VC_FRM_CNT", 8, "UINT", None, "BIG_ENDIAN", "TRUNCATE")
        self.header.append_item("SHF", 1, "UINT")
        self.header.append_item("SYNC_FLAG", 1, "UINT")
        self.header.append_item("PKT_ORDER_FLAG", 1, "UINT")
        self.header.append_item("SEG_LENGTH_ID", 2, "UINT")
        self.header.append_item("FIRST_HDR_PTR", 11, "UINT")

        # Create packet structure for CCSDS packet parsing
        self.packet = Packet(None, None, "BIG_ENDIAN")
        self.packet.define_item("CcsdsVersion", 0, 3, "UINT")
        self.packet.define_item("CcsdsType", 3, 1, "UINT")
        self.packet.define_item("CcsdsShf", 4, 1, "UINT")
        self.packet.define_item("CcsdsApid", 5, 11, "UINT")
        self.packet.define_item("CcsdsSeqflags", 16, 2, "UINT")
        self.packet.define_item("CcsdsSeqcnt", 18, 14, "UINT")
        self.packet.define_item("CcsdsLength", 32, 16, "UINT")

        # Create footer structure for CRC16
        self.footer = Structure("BIG_ENDIAN")
        self.footer.append_item("CRC16", 16, "UINT")

        self.randomizer = CcsdsRandomizer(CcsdsRandomizer.TM_MODE)
        self.crc16 = Crc16()

    def reset(self) -> None:
        """Reset protocol state."""
        super().reset()
        self.frame_data: list[bytes] = [b""] * self.NUM_VIRTUAL_CHANNELS
        self.packet_datas: list[tuple[bytes, dict]] = []
        self.mc_frm_cnt = -1
        self.vc_frm_cnt = [-1] * self.NUM_VIRTUAL_CHANNELS

    def handle_sync_pattern(self) -> Literal["STOP"] | None:
        """Only look for next sync pattern after returning all packets."""
        # Only look for the next sync pattern after we've returned all the packets we have
        if len(self.packet_datas) > 0:
            return None
        return super().handle_sync_pattern()  # type: ignore

    def reduce_to_single_packet(self) -> tuple[bytes | str, dict | None]:
        """
        Extract a single packet from the buffered data.

        Returns:
            Tuple of (packet_data, extra_metadata) or ("STOP", None) if more data needed,
            or ("RESYNC", extra) to trigger resynchronization
        """
        if self.interface is not None:
            self.interface_name = self.interface.name
        else:
            self.interface_name = ""

        # Return packets from earlier frames if we have them
        if len(self.packet_datas) > 0:
            packet_data, extra = self.packet_datas.pop(0)
            return (packet_data, extra)

        # Wait for enough data for the next frame
        if len(self.data) < self.frame_with_sync_length:  # type: ignore
            return ("STOP", None)

        return self._process_frame()

    def _process_frame(self) -> tuple[bytes | str, dict | None] | None:
        """
        Process a single frame from the data buffer.

        Returns:
            A result tuple if processing should stop early (RESYNC), or None to continue
        """
        extra: dict = {}

        # Reduce to frame without sync pattern
        sync_len = len(self.sync_pattern) if self.sync_pattern else 0
        frame_data = self.data[sync_len:self.frame_with_sync_length]  # type: ignore
        self.data = self.data[sync_len:]  # type: ignore

        # Derandomize if necessary
        if self.randomization:
            frame_data = self.randomizer.apply(frame_data)

        # Separate CRC if present
        if self.error_control:
            crc_data = frame_data[(len(frame_data) - 2):]
            frame_data = frame_data[:(len(frame_data) - 2)]

            # Verify CRC
            self.footer.buffer = crc_data
            crc = self.footer.read("CRC16")
            calculated_crc = self.crc16.calc(frame_data)
            if calculated_crc != crc:
                Logger.error(f"{self.interface_name}: CRC Mismatch! Expected 0x{'{:02X}'.format(calculated_crc)} vs found 0x{'{:02X}'.format(crc)}")
                return ("RESYNC", None)

        # Parse and validate frame header
        self.header.buffer = frame_data[0:6]
        frame_data = frame_data[6:]

        result = self._validate_frame_header(extra)
        if result is not None:
            return result

        vcid = extra["VCID"]
        self._update_frame_counters(vcid, extra)

        # Frame Header Validated, now remove the rest of the frame from stream
        self.data = self.data[self.frame_length:]

        # Handle first header pointer and extract packets
        first_hdr_ptr = self.header.read("FIRST_HDR_PTR")
        return self._handle_first_hdr_ptr_and_extract_packets(
            first_hdr_ptr, frame_data, vcid, extra
        )

    def _validate_frame_header(
        self, extra: dict
    ) -> tuple[bytes | str, dict | None] | None:
        """Validate frame header fields. Returns error tuple if fails, None if valid."""
        version = self.header.read("VERSION")
        if version != 0:
            Logger.error(f"{self.interface_name}: Invalid Frame Version detected! Expected 0 vs found {version}")
            return ("RESYNC", None)

        scid = self.header.read("SCID")
        if scid != self.scid:
            Logger.error(f"{self.interface_name}: Invalid SCID detected! Expected {self.scid} vs found {scid}")
            return ("RESYNC", None)

        vcid = self.header.read("VCID")
        extra["VCID"] = vcid

        ocf_flag = self.header.read("OCF_FLAG")
        if ocf_flag != 0:
            Logger.error(f"{self.interface_name}: Invalid OCF Flag detected! Expected 0 vs found {ocf_flag}")
            return ("RESYNC", None)

        shf = self.header.read("SHF")
        if shf != 0:
            Logger.error("{self.interface_name}: TM Transfer Frame Secondary Header Not Supported")
            return ("RESYNC", None)

        sync_flag = self.header.read("SYNC_FLAG")
        if sync_flag != 0:
            Logger.error(f"{self.interface_name}: Invalid Sync Flag detected! Expected 0 vs found {sync_flag}")
            return ("RESYNC", None)

        pkt_order_flag = self.header.read("PKT_ORDER_FLAG")
        if pkt_order_flag != 0:
            Logger.error(
                f"{self.interface_name}: Invalid Packet Order Flag detected! Expected 0 vs found {pkt_order_flag}"
            )
            return ("RESYNC", None)

        seg_length_id = self.header.read("SEG_LENGTH_ID")
        if seg_length_id != 3:
            Logger.error(f"{self.interface_name}: Invalid Segment Length ID detected! Expected 3 vs found {seg_length_id}")
            return ("RESYNC", None)

        return None

    def _update_frame_counters(self, vcid: int, extra: dict) -> None:
        """Update and validate frame counters."""  
        mc_frm_cnt = self.header.read("MC_FRM_CNT")
        extra["MC_FRM_CNT"] = mc_frm_cnt
        if self.mc_frm_cnt != -1:
            expected_mc_frm_cnt = (self.mc_frm_cnt + 1) % 256
            if mc_frm_cnt != expected_mc_frm_cnt:
                Logger.warn(
                    f"{self.interface_name}: Master Channel Frame Count Out of Order! "
                    f"Expected {expected_mc_frm_cnt} vs found {mc_frm_cnt}"
                )

        vc_frm_cnt = self.header.read("VC_FRM_CNT")
        extra["VC_FRM_CNT"] = vc_frm_cnt
        if self.vc_frm_cnt[vcid] != -1:
            expected_vc_frm_cnt = (self.vc_frm_cnt[vcid] + 1) % 256
            if vc_frm_cnt != expected_vc_frm_cnt:
                Logger.warn(
                    f"{self.interface_name}: Virtual Channel {vcid} Frame Count Out of Order! "
                    f"Expected {expected_vc_frm_cnt} vs found {vc_frm_cnt}"
                )

        self.mc_frm_cnt = mc_frm_cnt
        self.vc_frm_cnt[vcid] = vc_frm_cnt

    def _handle_first_hdr_ptr_and_extract_packets(
        self, first_hdr_ptr: int, frame_data: bytes, vcid: int, extra: dict
    ) -> tuple[bytes | str, dict | None] | None:
        """Handle first header pointer logic and extract packets."""
        # Handle first_hdr_ptr cases
        if first_hdr_ptr == self.ONLY_IDLE_DATA:
            if len(self.frame_data[vcid]) > 0:
                Logger.error(f"{self.interface_name}: Expected More Data for VCID {vcid} but received Only Idle Data!")
                self.frame_data[vcid] = b""
            return ("RESYNC", None)
        elif first_hdr_ptr == self.NO_FIRST_HEADER:
            if len(self.frame_data[vcid]) <= 0:
                Logger.error(f"{self.interface_name}: Expected Previous Data for VCID {vcid} but had none!")
                return ("RESYNC", None)
        elif first_hdr_ptr == 0:
            if len(self.frame_data[vcid]) > 0:
                Logger.error(f"{self.interface_name}: Unexpected Previous Data for VCID {vcid}!")
                self.frame_data[vcid] = b""
        else:
            if len(self.frame_data[vcid]) <= 0:
                Logger.warn(f"{self.interface_name}: No Previous Data for VCID {vcid}!")
                frame_data = frame_data[first_hdr_ptr:]

        frame_data = self.frame_data[vcid] + frame_data
        return self._extract_packets_from_frame(frame_data, vcid, extra)

    def _extract_packets_from_frame(
        self, frame_data: bytes, vcid: int, extra: dict
    ) -> tuple[bytes | str, dict | None] | None:
        """Extract all CCSDS packets from the frame data."""
        while len(frame_data) > 0:
            # Drop all the encapsulation Idle bytes
            if frame_data[0:1] == self.ENCAPSULATION_IDLE_BYTE_STRING:
                frame_data = frame_data[1:]
                continue

            # Make sure we have enough bytes for a complete packet
            if len(frame_data) < self.MINIMUM_CCSDS_PACKET_BYTES:
                self.frame_data[vcid] = frame_data
                break

            # Validate packet
            self.packet.buffer = frame_data[0:6]
            version = self.packet.read("CcsdsVersion")
            if version != 0:
                Logger.error(f"{self.interface_name}: Invalid Packet Version detected! Expected 0 vs found {version}")
                if len(self.packet_datas) > 0:
                    return self.packet_datas.pop(0)
                return ("RESYNC", None)
            pkt_type = self.packet.read("CcsdsType")
            if pkt_type != self.TELEMETRY:
                Logger.error("{self.interface_name}: Unexpected Command Found in TM Transfer Frame!")
                if len(self.packet_datas) > 0:
                    return self.packet_datas.pop(0)
                return ("RESYNC", None)
            length = self.packet.read("CcsdsLength")
            length = length + self.MINIMUM_CCSDS_PACKET_BYTES # Length 0 = 7 bytes

            # Make sure we have enough bytes for the specific complete packet
            if len(frame_data) < length:
                self.frame_data[vcid] = frame_data
                break

            # Have a complete packet - Extract it from the frame data
            packet_data = frame_data[:length]
            frame_data = frame_data[length:]

            apid = self.packet.read("CcsdsApid")
            if apid == self.IDLE_APID:
                continue
            else:
                self.packet_datas.append((packet_data, extra.copy()))

        if len(self.packet_datas) > 0:
            packet_data, extra = self.packet_datas.pop(0)
            return (packet_data, extra)

        return ("RESYNC", None)
