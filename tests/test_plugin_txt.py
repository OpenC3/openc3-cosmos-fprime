# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""The file downlink protocol must be the last READ protocol in both header modes."""

from pathlib import Path

PLUGIN = (Path(__file__).resolve().parent.parent / "plugin.txt").read_text().splitlines()


def _branch(start_marker, end_marker):
    start = next(i for i, line in enumerate(PLUGIN) if start_marker in line)
    end = next(i for i, line in enumerate(PLUGIN) if i > start and end_marker in line)
    return [line.strip() for line in PLUGIN[start + 1:end]]


def _read_protocols(lines):
    return [line for line in lines if line.upper().startswith("PROTOCOL READ")]


def test_fprime_branch():
    lines = _read_protocols(_branch("if fprime_headers == 'FPRIME'", "else"))
    assert "fprime_file_downlink_protocol.py FPRIME" in lines[-1]


def test_space_packet_branch():
    lines = _read_protocols(_branch("else", "end"))
    assert "fprime_file_downlink_protocol.py SPACE_PACKET" in lines[-1]
