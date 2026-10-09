# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license. 
# See LICENSE.md file in the project root for details.

from openc3.subpacketizers.subpacketizer import Subpacketizer
from openc3.system.system import System

class FprimeSubpacketizer(Subpacketizer):
    def call(self, packet):
        # Create a list of packets to return
        packets = []

        # Read the packet item "CHANNELS" which contains all the subpackets
        channels = packet.read("CHANNELS")

        # While we still have data to process
        while len(channels) > 0:
            # Identify the next subpacket using the entire block of data
            subpacket = System.telemetry.identify(channels, target_names=[packet.target_name], subpackets=True)

            if subpacket:
                # If it identified then breakout the subpacket content based on its size
                length = self._subpacket_length(subpacket, channels)
                subpacket.buffer = channels[:length]
                subpacket = subpacket.clone()

                # Add to list of subpackets to return
                packets.append(subpacket)

                # Remove this subpacket from the block of data
                channels = channels[length:]
            else:
                # If we can't identify then just give up
                break

        # Append the parent packet so it gets processed too
        packets.append(packet)

        # Return the parent packet and subpackets
        return packets

    @staticmethod
    def _subpacket_length(subpacket, data):
        """Bytes this subpacket occupies at the start of data.

        defined_length counts variable sized items (e.g. strings) as 0 bits, so
        add the size given by each one's length item.
        """
        if subpacket.fixed_size:
            return subpacket.defined_length
        # Setting the buffer recalculates the offsets of the variable sized items
        subpacket.buffer = data
        length = subpacket.defined_length
        for item in subpacket.sorted_items:
            vbs = item.variable_bit_size
            if vbs and item.data_type != "DERIVED":
                count = subpacket.read(vbs["length_item_name"], "RAW")
                length += (count * vbs["length_bits_per_count"] + vbs["length_value_bit_offset"]) // 8
        return length
