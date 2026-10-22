# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""The shipped FPRIME target, generated from the fprime-test F Prime 4.4.1 + CfdpManager dictionary."""

from pathlib import Path

import pytest

from openc3.packets.packet_config import PacketConfig

ROOT = Path(__file__).resolve().parent.parent
CMD_TLM = ROOT / "targets" / "FPRIME" / "cmd_tlm"


@pytest.fixture(scope="module")
def config(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("generated_target")
    pc = PacketConfig()
    for name in ("cmd.txt", "tlm.txt"):
        lines = []
        for line in (CMD_TLM / name).read_text().splitlines():
            stripped = line.strip()
            # Not importable outside a running COSMOS target
            if stripped.startswith("SUBPACKETIZER") or stripped == "READ_CONVERSION fprime_event_conversion.py":
                continue
            lines.append(line.replace("<%= target_name %>", "FPRIME"))
        loadable = tmp_path / name
        loadable.write_text("\n".join(lines) + "\n")
        pc.process_file(str(loadable), "FPRIME")
    return pc


def test_loads_without_warnings(config):
    assert config.warnings == []


def test_cfdp_packets_present(config):
    assert "CFDP_PDU" in config.commands["FPRIME"]
    assert "CFDP_PDU" in config.telemetry["FPRIME"]


def test_ref_telemetry_packets_present(config):
    packet = config.telemetry["FPRIME"]["CDH"]
    assert packet.get_item("CCSDS_APID").id_value == 4
    assert packet.get_item("FPRIME_TLM_PACKET_ID").id_value == 1
    assert "CDHCORE_TLMSEND_GROUPCONFIGS_0_3_ENABLED" in packet.items
    version = config.telemetry["FPRIME"]["VERSION1"]
    assert version.get_item("CDHCORE_VERSION_FRAMEWORKVERSION_PAD").variable_bit_size is not None


def test_send_file_strings_use_v44_size_store(config):
    packet = config.commands["FPRIME"]["FILEHANDLINGCFDP.CFDPMANAGER.SENDFILE"]
    assert packet.get_item("SOURCEFILENAME_LENGTH").bit_size == 64
    assert packet.get_item("DESTFILENAME_LENGTH").bit_size == 64
