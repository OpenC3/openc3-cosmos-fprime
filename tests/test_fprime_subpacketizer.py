# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for FPrime Subpacketizer."""

from unittest.mock import patch

from openc3.packets.packet import Packet

from fprime_subpacketizer import FprimeSubpacketizer


def _make_parent(channels: bytes) -> Packet:
    parent = Packet("TGT", "PARENT")
    parent.append_item("CHANNELS", 0, "BLOCK")
    parent.write("CHANNELS", channels)
    return parent


def _make_subpacket(name: str, size_bytes: int) -> Packet:
    """Build a real Packet whose defined_length matches size_bytes."""
    sub = Packet("TGT", name)
    sub.append_item("DATA", size_bytes * 8, "BLOCK")
    return sub


class TestFprimeSubpacketizer:
    """Test suite for FPrime Subpacketizer."""

    def test_empty_channels_returns_only_parent(self):
        parent = _make_parent(b"")
        subpacketizer = FprimeSubpacketizer()

        with patch("fprime_subpacketizer.System") as mock_system:
            result = subpacketizer.call(parent)
            mock_system.telemetry.identify.assert_not_called()

        assert result == [parent]

    def test_single_subpacket(self):
        channels = b"\x01\x02\x03\x04"
        parent = _make_parent(channels)
        sub_template = _make_subpacket("SUB1", 4)
        subpacketizer = FprimeSubpacketizer()

        with patch("fprime_subpacketizer.System") as mock_system:
            mock_system.telemetry.identify.side_effect = [sub_template, None]
            result = subpacketizer.call(parent)

        assert len(result) == 2
        assert result[0].buffer == channels
        assert result[0].packet_name == "SUB1"
        assert result[-1] is parent
        mock_system.telemetry.identify.assert_called_once_with(
            channels, target_names=["TGT"], subpackets=True
        )

    def test_multiple_subpackets(self):
        channels = b"\xaa\xbb\xcc\xdd\xee\xff"
        parent = _make_parent(channels)
        sub1 = _make_subpacket("SUB1", 2)
        sub2 = _make_subpacket("SUB2", 4)
        subpacketizer = FprimeSubpacketizer()

        with patch("fprime_subpacketizer.System") as mock_system:
            mock_system.telemetry.identify.side_effect = [sub1, sub2]
            result = subpacketizer.call(parent)

        assert len(result) == 3
        assert result[0].buffer == b"\xaa\xbb"
        assert result[0].packet_name == "SUB1"
        assert result[1].buffer == b"\xcc\xdd\xee\xff"
        assert result[1].packet_name == "SUB2"
        assert result[2] is parent

        # Second identify call must receive remaining bytes after the first subpacket.
        calls = mock_system.telemetry.identify.call_args_list
        assert calls[0].args[0] == channels
        assert calls[1].args[0] == b"\xcc\xdd\xee\xff"

    def test_unidentifiable_data_stops_loop(self):
        channels = b"\x11\x22\x33\x44\x55\x66"
        parent = _make_parent(channels)
        sub1 = _make_subpacket("SUB1", 2)
        subpacketizer = FprimeSubpacketizer()

        with patch("fprime_subpacketizer.System") as mock_system:
            # First two bytes identify; the next chunk does not.
            mock_system.telemetry.identify.side_effect = [sub1, None]
            result = subpacketizer.call(parent)

        # One identified subpacket plus the parent; the unidentified tail is dropped.
        assert len(result) == 2
        assert result[0].packet_name == "SUB1"
        assert result[0].buffer == b"\x11\x22"
        assert result[1] is parent

    def test_subpackets_are_cloned(self):
        """Returned subpackets must be clones, not the shared template from identify()."""
        channels = b"\x01\x02"
        parent = _make_parent(channels)
        sub_template = _make_subpacket("SUB1", 2)
        subpacketizer = FprimeSubpacketizer()

        with patch("fprime_subpacketizer.System") as mock_system:
            mock_system.telemetry.identify.side_effect = [sub_template, None]
            result = subpacketizer.call(parent)

        assert result[0] is not sub_template
        assert result[0].buffer == channels

    def test_uses_parent_target_name(self):
        parent = _make_parent(b"\x00")
        parent_target = parent.target_name
        sub = _make_subpacket("SUB", 1)
        subpacketizer = FprimeSubpacketizer()

        with patch("fprime_subpacketizer.System") as mock_system:
            mock_system.telemetry.identify.side_effect = [sub, None]
            subpacketizer.call(parent)

        kwargs = mock_system.telemetry.identify.call_args.kwargs
        assert kwargs["target_names"] == [parent_target]
        assert kwargs["subpackets"] is True
