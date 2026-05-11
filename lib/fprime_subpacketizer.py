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
                # If it identified then breakout the subpacket content based on fixed size
                # (like the FIXED protocol)
                subpacket.buffer = channels[:subpacket.defined_length]
                subpacket = subpacket.clone()

                # Add to list of subpackets to return
                packets.append(subpacket)

                # Remove this subpacket from the block of data
                channels = channels[subpacket.defined_length:]
            else:
                # If we can't identify then just give up
                break

        # Append the parent packet so it gets processed too
        packets.append(packet)

        # Return the parent packet and subpackets
        return packets