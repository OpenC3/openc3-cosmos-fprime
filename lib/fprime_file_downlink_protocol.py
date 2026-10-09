# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""READ protocol that turns F Prime file downlinks into bucket files and data product telemetry.

Must be the LAST read protocol on the interface. Every packet passes through
unchanged. FW_PACKET_FILE packets are also reassembled; a finished file is
written to the logs bucket under <scope>/<bucket_folder>/<target>/<name>.
Finished .fdp files are decoded with the generated fprime_dp_dictionary module:
decoded/<name>.json is written and DP_HEADER / DP.<record> packets are
queued. The interface asks every protocol for cached data (a blank read) before
reading new bytes, so queued packets drain right after the file's END packet.
Protocols earlier in the chain may also hold cached packets (e.g. several packets
in one TM frame) and hand them over first; while anything is queued, those join
the back of the queue so output order always matches the order packets arrived.
"""

import importlib.util
from collections import deque
from pathlib import Path

from openc3.environment import OPENC3_LOGS_BUCKET, OPENC3_SCOPE
from openc3.interfaces.protocols.protocol import Protocol
from openc3.system.system import System
from openc3.utilities.bucket import Bucket
from openc3.utilities.logger import Logger

from fprime_dp_decoder import decode_dp, decoded_to_json
from fprime_dp_packets import build_dp_packets
from fprime_file_assembler import FileAssembler, parse_file_packet, safe_file_name
from fprime_framing import FW_PACKET_FILE, unframe

DP_EXTENSION = ".fdp"


class FprimeFileDownlinkProtocol(Protocol):
    def __init__(self, headers="SPACE_PACKET", target_name="FPRIME", bucket_folder="fprime_downlink",
                 max_file_size=104857600, allow_empty_data=None):
        # Protocol.__init__ calls reset(), which needs the assembler
        self.assembler = FileAssembler(int(max_file_size))
        super().__init__(allow_empty_data)
        self.headers = str(headers).upper()
        self.target_name = target_name
        self.bucket_folder = bucket_folder
        self.queue = deque()
        self._dictionary = None

    def reset(self):
        super().reset()
        self.queue = deque()
        self.assembler.reset()

    def read_data(self, data, extra=None):
        if len(data) == 0:
            if self.queue:
                return self.queue.popleft()
            return super().read_data(data, extra)
        pending = len(self.queue)
        # Append incoming packets before handling them, so anything synthesized
        # by this packet follows it without inserting into the middle of the queue.
        if pending:
            self.queue.append((data, extra))
        try:
            self._handle(data)
        except Exception as error:
            Logger.error(f"{self.target_name}: file downlink: {error}")
        if pending == 0:
            return (data, extra)
        # Earlier synthesized packets go first; this packet goes ahead of any it just produced
        return self.queue.popleft()

    def bucket_key(self, name):
        return f"{OPENC3_SCOPE}/{self.bucket_folder}/{self.target_name}/{name}"

    def store(self, name, body):
        Bucket.getClient().put_object(bucket=OPENC3_LOGS_BUCKET, key=self.bucket_key(name), body=body)

    def _handle(self, data):
        unframed = unframe(self.headers, data)
        if unframed is None or unframed[0] != FW_PACKET_FILE:
            return
        completed = self.assembler.feed(parse_file_packet(unframed[1]))
        if completed is not None:
            self._complete(completed)

    def _complete(self, completed):
        name = safe_file_name(completed.dest_path)
        if not completed.complete:
            self.store(f"{name}.incomplete", completed.data)
            Logger.warn(f"{self.target_name}: {name} downlinked with missing data, stored as {name}.incomplete")
            return
        if not completed.checksum_ok:
            Logger.warn(f"{self.target_name}: {name} failed its downlink checksum")
        self.store(name, completed.data)
        Logger.info(f"{self.target_name}: stored downlinked file {self.bucket_key(name)}")
        if not name.endswith(DP_EXTENSION):
            return
        dictionary = self._load_dictionary()
        if dictionary is None:
            return
        decoded = decode_dp(completed.data, dictionary.WIDTHS, dictionary.RECORDS,
                            max_decompressed_size=self.assembler.max_file_size)
        container = dictionary.CONTAINERS.get(decoded.header.container_id) if decoded.header else None
        self.store(f"decoded/{name}.json", decoded_to_json(decoded, name, container).encode())
        if decoded.error:
            Logger.warn(f"{self.target_name}: {name} decoded with error: {decoded.error}")
        if decoded.header is not None:
            packets = build_dp_packets(self.headers, decoded, name)
            skipped = len(decoded.records) - (len(packets) - 1)
            if skipped:
                Logger.warn(f"{self.target_name}: {name}: {skipped} record(s) too large to emit as telemetry; "
                            "see the .json file")
            self.queue.extend((packet, None) for packet in packets)

    def _load_dictionary(self):
        if self._dictionary is None:
            try:
                target = System.targets.get(str(self.target_name).upper())
                if target is None:
                    raise FileNotFoundError(f"target {self.target_name} not found")
                path = Path(target.dir) / "lib" / "fprime_dp_dictionary.py"
                spec = importlib.util.spec_from_file_location(f"{self.target_name}_dp_dictionary", path)
                dictionary = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(dictionary)
                self._dictionary = dictionary
            except (ImportError, OSError):
                Logger.warn(f"{self.target_name}: fprime_dp_dictionary not found; regenerate the target "
                            "with fprime_parser.py to decode data products")
                self._dictionary = False
        return self._dictionary or None
