# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

# End-to-end CFDP test against the fprime-test F Prime 4.4.1 + CfdpManager container.
# Requires the OpenC3 CFDP plugin installed with the settings in this plugin's README
# ("CFDP with CfdpManager"): COSMOS entity 100, F Prime entity 42.

import time
import zlib

from cfdp import cfdp_indications, cfdp_put, cfdp_subscribe
from openc3.script import (
    cmd,
    get_packets,
    get_target_file,
    put_target_file,
    set_line_delay,
    subscribe_packets,
    wait,
    wait_packet,
)
from openc3.script.suite import Group, Suite

FPRIME_ENTITY = 42
COSMOS_ENTITY = 100
TARGET = "FPRIME"
CFDP_DIR = "CFDP/tmp"  # The CFDP plugin's default root_path within targets_modified
SEND_FILE = "FILEHANDLINGCFDP.CFDPMANAGER.SENDFILE"
TIMEOUT = 120


# Keep these identical to fprime-test/make_files.py, which wrote the files in the container
def medium():
    return bytes(i % 251 for i in range(100_000))


def odd():
    return bytes((i * 7) % 256 for i in range(5_003))


def fprime_crc32(data):
    # FileManager.CalculateCrc reports CRC-32 without the final XOR, i.e. ~zlib.crc32
    return zlib.crc32(data) ^ 0xFFFFFFFF


def unique(name):
    # The CFDP plugin renames received files that already exist, so never reuse a name
    stem, ext = name.rsplit(".", 1)
    return f"{stem}_{int(time.time() * 1000)}.{ext}"


def wait_for_event(subscription, text, timeout=TIMEOUT):
    end = time.time() + timeout
    while time.time() < end:
        subscription, packets = get_packets(subscription)
        for packet in packets:
            message = str(packet.get("FPRIME_EVENT_MESSAGE", ""))
            if text in message:
                return message
        wait(0.5)
    raise AssertionError(f"No {TARGET} event containing '{text}' within {timeout}s")


def wait_for_receive(continuation, destination_file_name, timeout=TIMEOUT):
    """Wait for the CFDP plugin to finish receiving a file F Prime sent with SendFile."""
    end = time.time() + timeout
    transaction_id = None
    while time.time() < end:
        indications, continuation = cfdp_indications(continuation=continuation)
        for indication in indications:
            if indication.get("indication_type") == "Metadata-Recv" and str(
                indication.get("destination_file_name", "")
            ).endswith(destination_file_name):
                transaction_id = indication["transaction_id"]
            if transaction_id and indication.get("transaction_id") == transaction_id and (
                indication.get("indication_type") == "Transaction-Finished"
            ):
                return indication
        wait(0.5)
    raise AssertionError(f"Receive of {destination_file_name} did not finish within {timeout}s")


def wait_for_finished(continuation, transaction_id, timeout=TIMEOUT):
    end = time.time() + timeout
    while time.time() < end:
        indications, continuation = cfdp_indications(continuation=continuation)
        for indication in indications:
            if indication.get("transaction_id") == transaction_id and (
                indication.get("indication_type") == "Transaction-Finished"
            ):
                return indication
        wait(0.5)
    raise AssertionError(f"Transaction {transaction_id} did not finish within {timeout}s")


class CfdpManagerGroup(Group):
    def setup(self):
        set_line_delay(0)
        put_target_file(f"{CFDP_DIR}/medium.bin", medium())

    def _push(self, transmission_mode):
        destination = f"/files/uplink/{unique('medium.bin')}"
        events = subscribe_packets([[TARGET, "EVENT"]])
        _, indication = cfdp_put(
            destination_entity_id=FPRIME_ENTITY,
            source_file_name="medium.bin",
            destination_file_name=destination,
            transmission_mode=transmission_mode,
            timeout=TIMEOUT,
        )
        assert indication["condition_code"] == "NO_ERROR", indication
        # Class 1 completes when EOF is sent, so give F Prime a moment to close the file
        wait(2)
        cmd(f"{TARGET} FILEHANDLINGCFDP.FILEMANAGER.CALCULATECRC with FILENAME '{destination}'")
        wait_for_event(events, f"{destination} has CRC value 0x{fprime_crc32(medium()):x}")

    def _pull(self, cfdp_class):
        destination = unique("odd.bin")
        continuation = cfdp_subscribe()
        cmd(
            f"{TARGET} {SEND_FILE} with CHANNELID 0, DESTID {COSMOS_ENTITY}, CFDPCLASS {cfdp_class}, "
            f"KEEP KEEP, PRIORITY 0, SOURCEFILENAME '/files/odd.bin', DESTFILENAME '{destination}'"
        )
        indication = wait_for_receive(continuation, destination)
        assert indication["condition_code"] == "NO_ERROR", indication
        assert get_target_file(f"{CFDP_DIR}/{destination}").read() == odd()

    def test_push_class1(self):
        self._push("UNACKNOWLEDGED")

    def test_push_class2(self):
        self._push("ACKNOWLEDGED")

    def test_pull_class1(self):
        self._pull("CLASS_1")

    def test_pull_class2(self):
        self._pull("CLASS_2")

    def test_telemetry_still_flows(self):
        continuation = cfdp_subscribe()
        transaction_id = cfdp_put(
            destination_entity_id=FPRIME_ENTITY,
            source_file_name="medium.bin",
            destination_file_name=f"/files/uplink/{unique('medium.bin')}",
            transmission_mode="ACKNOWLEDGED",
            timeout=None,
        )
        # wait_packet returns False on timeout rather than raising
        assert wait_packet(TARGET, "EVENT", 1, 10), "No events while a CFDP transfer was running"
        assert wait_packet(TARGET, "REF.SYSTEMRESOURCES.CPU", 1, 10), "No channels while a CFDP transfer was running"
        indication = wait_for_finished(continuation, transaction_id)
        assert indication["condition_code"] == "NO_ERROR", indication


class CfdpManagerSuite(Suite):
    def __init__(self):
        super().__init__()
        self.add_group(CfdpManagerGroup)
