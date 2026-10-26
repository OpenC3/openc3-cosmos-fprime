# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

# End-to-end telemetry test against the fprime-test container, built either way:
#   TLM_SEND=chan        TlmChan: one channelized packet per channel (APID 1)
#   TLM_SEND=packetizer  TlmPacketizer: the RefPackets telemetry packets (APID 4)
# The mode is detected at startup. Each test sets values with Ref commands and checks
# them in whichever packet carries the channel in that mode.
#
# Script Runner continues after an error by default, so a raise inside a polling loop would not
# leave the loop: every loop here ends on its own deadline and the raise comes after it.

import time

from openc3.script import cmd, get_tlm_cnt, set_line_delay, tlm, wait, wait_check
from openc3.script.exceptions import SkipScript
from openc3.script.suite import Group, Suite

TARGET = "FPRIME"
TIMEOUT = 10
CONNECT_TIMEOUT = 60

# RefPackets packet IDs, from Ref/Top/RefPackets.fppi
PACKET_IDS = {"CDH": 1, "TYPEDEMO": 20, "VERSION1": 22, "VERSION_CUSTOM1": 28}

SCALARS = {"I8": -5, "I16": -300, "I32": -70000, "I64": -5000000000, "U8": 200, "U16": 60000,
           "U32": 4000000000, "U64": 9000000000, "F32": 1.5, "F64": -2.25}

mode = None


def detect_mode():
    """'chan' if channelized TELEMETRY packets arrive, 'packet' if RefPackets packets do.

    Retries for CONNECT_TIMEOUT so the suite can start while the interface is still (re)connecting,
    e.g. straight after the plugin is installed or upgraded."""
    end = time.time() + CONNECT_TIMEOUT
    while time.time() < end:
        chan = get_tlm_cnt(TARGET, "TELEMETRY")
        packet = get_tlm_cnt(TARGET, "CDH")
        try:
            # Changes CommandsDispatched, which both TlmChan and TlmPacketizer (CDH, group 1) send
            cmd(f"{TARGET} CDHCORE.CMDDISP.CMD_NO_OP")
        except Exception as error:  # Interface not connected yet; errors arrive as various types over JSON-RPC
            print(f"Waiting for {TARGET}: {error}")
            wait(2)
            continue
        attempt_end = min(end, time.time() + TIMEOUT)
        while time.time() < attempt_end:
            if get_tlm_cnt(TARGET, "CDH") > packet:
                return "packet"
            if get_tlm_cnt(TARGET, "TELEMETRY") > chan:
                return "chan"
            wait(0.2)
    raise AssertionError(f"No {TARGET} telemetry within {CONNECT_TIMEOUT}s; is the fprime-test container connected?")


class Channel:
    """Where an F Prime channel shows up in COSMOS in the current mode."""

    def __init__(self, name, packet):
        self.name = name
        self.packet = packet  # RefPackets packet that carries it

    def packet_name(self):
        return (self.packet if mode == "packet" else self.name).upper()

    def item(self, suffix=""):
        # Channelized items use the channel's short name, packet items its full name
        item = self.name.replace(".", "_") if mode == "packet" else self.name.split(".")[-1]
        return f"{TARGET} {self.packet_name()} {item}{suffix}".upper()

    def update(self, command):
        """Send command, then wait for a fresh packet carrying this channel."""
        count = get_tlm_cnt(TARGET, self.packet_name())
        cmd(command)
        if mode == "packet":
            cmd(f"{TARGET} CDHCORE.TLMSEND.SEND_PKT with ID {PACKET_IDS[self.packet]}, SECTION REALTIME")
        end = time.time() + TIMEOUT
        while get_tlm_cnt(TARGET, self.packet_name()) <= count and time.time() < end:
            wait(0.1)
        if get_tlm_cnt(TARGET, self.packet_name()) <= count:
            raise AssertionError(f"{self.packet_name()} not received within {TIMEOUT}s")


COMMANDS_DISPATCHED = Channel("CdhCore.cmdDisp.CommandsDispatched", "CDH")
GROUP_CONFIGS = Channel("CdhCore.tlmSend.GroupConfigs", "CDH")
FRAMEWORK_VERSION = Channel("CdhCore.version.FrameworkVersion", "VERSION1")
PROJECT_VERSION = Channel("CdhCore.version.ProjectVersion", "VERSION1")
CUSTOM_VERSION = Channel("CdhCore.version.CustomVersion01", "VERSION_CUSTOM1")
SCALAR_STRUCT = Channel("Ref.typeDemo.ScalarStructCh", "TYPEDEMO")
CHOICE_PAIR = Channel("Ref.typeDemo.ChoicePairCh", "TYPEDEMO")


class TlmGroup(Group):
    def setup(self):
        global mode
        set_line_delay(0)
        mode = detect_mode()
        if mode == "packet":
            print("Telemetry mode: TlmPacketizer (RefPackets telemetry packets, APID 4)")
            # Send groups 1-3; Ref's packets go up to group 3
            cmd(f"{TARGET} CDHCORE.TLMSEND.SET_LEVEL with LEVEL 3")
        else:
            print("Telemetry mode: TlmChan (channelized telemetry, APID 1)")

    def test_command_counter(self):
        # Wait on the value, not a packet count: telemetry lags commands by a TlmChan tick plus an
        # aggregator flush, and the packet count and current value don't update together.
        # Right after the plugin is installed the value is None until detect_mode's NO_OP lands.
        end = time.time() + TIMEOUT
        while (before := tlm(COMMANDS_DISPATCHED.item())) is None and time.time() < end:
            wait(0.2)
        if before is None:
            raise AssertionError(f"No {COMMANDS_DISPATCHED.item()} value within {TIMEOUT}s")
        cmd(f"{TARGET} CDHCORE.CMDDISP.CMD_NO_OP")
        if mode == "packet":
            cmd(f"{TARGET} CDHCORE.TLMSEND.SEND_PKT with ID {PACKET_IDS['CDH']}, SECTION REALTIME")
        wait_check(f"{COMMANDS_DISPATCHED.item()} > {before}", TIMEOUT)

    def test_version_strings(self):
        FRAMEWORK_VERSION.update(f"{TARGET} CDHCORE.VERSION.VERSION with VERSION_TYPE ALL")
        framework = tlm(FRAMEWORK_VERSION.item())
        assert framework.startswith("v4.4.1"), framework
        assert tlm(FRAMEWORK_VERSION.item("_LENGTH")) == len(framework)
        # In a packet, ProjectVersion follows FrameworkVersion's unused bytes
        wait_check(f"{PROJECT_VERSION.item()} != ''", TIMEOUT)

    def test_string_inside_struct(self):
        if mode != "packet":
            # Ref registers no custom versions, so CustomVersion01 is never written and TlmChan never
            # sends it; SEND_PKT sends the packet's default contents
            raise SkipScript("TlmPacketizer only")
        CUSTOM_VERSION.update(f"{TARGET} CDHCORE.VERSION.VERSION with VERSION_TYPE CUSTOM")
        # version_status follows the variable length version_value string
        assert tlm(CUSTOM_VERSION.item("_VERSION_STATUS")) in ("OK", "FAILURE")

    def test_scalar_struct(self):
        params = ", ".join(f"SCALAR_INPUT_{name} {value}" for name, value in SCALARS.items())
        SCALAR_STRUCT.update(f"{TARGET} REF.TYPEDEMO.SEND_SCALARS with {params}")
        for name, value in SCALARS.items():
            wait_check(f"{SCALAR_STRUCT.item('_' + name)} == {value}", TIMEOUT)

    def test_enum_struct(self):
        CHOICE_PAIR.update(f"{TARGET} REF.TYPEDEMO.CHOICE_PAIR with CHOICES_FIRSTCHOICE RED, CHOICES_SECONDCHOICE BLUE")
        wait_check(f"{CHOICE_PAIR.item('_FIRSTCHOICE')} == 'RED'", TIMEOUT)
        wait_check(f"{CHOICE_PAIR.item('_SECONDCHOICE')} == 'BLUE'", TIMEOUT)

    def test_packetizer_group_levels(self):
        if mode != "packet":
            raise SkipScript("TlmPacketizer only")
        # SET_LEVEL 3 in setup enabled every group of the REALTIME section
        GROUP_CONFIGS.update(f"{TARGET} CDHCORE.TLMSEND.SET_LEVEL with LEVEL 3")
        for group in range(4):
            wait_check(f"{GROUP_CONFIGS.item(f'_0_{group}_ENABLED')} == 'ENABLED'", TIMEOUT)


class TlmSuite(Suite):
    def __init__(self):
        super().__init__()
        self.add_group(TlmGroup)
