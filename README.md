# OpenC3 COSMOS FPrime Plugin

See the [OpenC3](https://openc3.com) documentation for all things OpenC3.

This plugin provides the code necessary to quickly get COSMOS talking with a FPrime based system.
Note that this plugin must be copied from source and configured for your specific FPrime system before installing.

This supports and has been tested against FPrime 3.6, FPrime 4.2 and FPrime 4.4. It probably will work with other
versions as well.

Note that this plugin expects your topology should be setup as a TCP/IP Server so that COSMOS can connect to it.

## Getting Started

1. Locate the .json data dictionary from your FPrime project. It should be under the build-artifacts folder.
2. From the root folder of the plugin, run: python lib/fprime_parser.py FPRIME /path/to/your/Dictionary.json
3. Build the plugin: rake build VERSION=1.0.0

## Installing into OpenC3 COSMOS

1. Go to the OpenC3 Admin Tool, Plugins Tab
1. Click the install button and choose your plugin.gem file
1. Fill out plugin parameters
1. Click Install

## Communication Stacks

The `fprime_headers` plugin variable selects the protocol chain to match your topology's communication
subtopology:

| `fprime_headers` | FPrime subtopology | On the wire |
|------------------|--------------------|-------------|
| `SPACE_PACKET` (default) | `ComCcsds.Subtopology` (FPrime 4.x) | CCSDS Space Packets in TC (uplink) and TM (downlink) transfer frames |
| `SPACE_PACKET_ONLY` | `ComCcsds.SpacePacket` (FPrime 4.x) | Bare CCSDS Space Packets, no transfer frames |
| `FPRIME` | `ComFprime.Subtopology` (FPrime 3.x and 4.x) | FPrime's own framing |

The FPrime-side defaults the plugin assumes are SCID 0x44, TC VCID 1, and 1024-byte TM frames with a CRC
and no randomization.

- **TM packet spanning** (FPrime 4.4, `ComCcsdsConfig.Aggregator.enablePacketSpanning`) is supported
  with no plugin setting. The TM frame protocol reassembles packets split across frames using the First
  Header Pointer, whether spanning is on or off. When COSMOS connects partway through a spanned packet, it
  skips quietly to the next packet start. A lost frame (a gap in the virtual channel frame count) discards
  the partial packet rather than joining it to unrelated data.
- **`SPACE_PACKET_ONLY`:** FPrime pads every send to the TM data field size with idle packets
  (APID 0x7FF), and the plugin drops them. FPrime's frameless uplink has no frame accumulator, so each
  TCP read must hold exactly one Space Packet. Commands sent one at a time work, but a fast burst such
  as a CFDP uplink can coalesce in TCP, and FPrime drops all but the first packet of each read. Use
  `SPACE_PACKET` for CFDP uplink.
- **SDLS and AOS:** FPrime 4.4's SDLS components (`ComCcsdsSdls`, clear text or AES-256-GCM) and its AOS
  framer and deframer are not supported by this plugin. The OpenC3 CCSDS protocols plugin, available to
  COSMOS Enterprise customers, implements SDLS and AOS framing.

## Telemetry

`fprime_parser.py` generates definitions for both of F Prime's telemetry components, so the target works
whichever one your topology uses.

- **TlmChan** (APID 1): each downlinked channel becomes its own packet. The packet is named after the full
  channel name (`Ref.typeDemo.ScalarU8Ch`) and its item after the short name (`ScalarU8Ch`).
- **TlmPacketizer** (APID 4): each packet in the dictionary's `telemetryPacketSets` (the topology's
  `telemetry packets` block) becomes a packet with that name, such as `CDH`. It is identified by its packet
  ID. Each member channel is an item named after the full channel name, with dots replaced by underscores
  (`Ref_typeDemo_ScalarU8Ch`), because channels from different components can share a short name.
  - **Strings:** TlmPacketizer gives every channel its maximum serialized size, so each string is followed
    by a `<item>_PAD` item that holds its unused bytes.
  - **Multiple packet sets:** if the dictionary has more than one, packet names get the set name as a
    prefix (`RefPackets.CDH`). The parser warns, because their packet IDs can overlap.
  - **Name clashes:** a packet name that clashes with another generated packet stops the parser with an
    error.
  - **What COSMOS ignores:** packet groups and send levels only control when packets are sent, so they
    don't affect the definitions. Channels in the `omit` list are never sent in packets.

## File Downlink and Data Products

Every file downlinked by the FPrime `FileDownlink` component (e.g. `SendFile`, or `DpCatalog` transmitting
data products) is reassembled and written to the COSMOS logs bucket at
`<SCOPE>/fprime_downlink/<TARGET>/<file name>`. Browse them with Bucket Explorer. The `FILE_START`,
`FILE_DATA`, `FILE_END` and `FILE_CANCEL` packets are also available as telemetry.

- Transfers with missing data are stored as `<file name>.incomplete`.
- Data product files (`.fdp`) are decoded using the `records` and `containers` in your dictionary. A
  `decoded/<file name>.json` with the decoded header and records is written under the same target folder,
  keeping generated JSON separate from downlinked files, and a `DP_HEADER`
  packet plus one `DP.<record name>` packet per record are emitted, timestamped with the container's time tag.
  `DP_HEADER` reports `HEADER_CRC_OK`, `DATA_CRC_OK` and `DECODE_OK`.
- Compressed data products (`DpCompressProc`, FPrime 4.4+) are decompressed before decoding.
- Array records whose elements are structs, enums or strings appear in telemetry as a raw `VALUE` block;
  the `.json` file has the decoded values.
- Re-run `fprime_parser.py` whenever your flight dictionary changes. Record definitions and framework type
  widths (notably `FwSizeStoreType`, which is U64 starting with FPrime 4.4) come from it.
- Files are reassembled in memory, up to 100 MiB by default. To change this, append the bucket folder and
  the size in bytes to the `fprime_file_downlink_protocol.py` lines in `plugin.txt`, e.g.
  `... <%= fprime_target_name %> fprime_downlink 524288000`.
  The same limit bounds the total decompressed record stream. Decoding a data product holds every value
  in memory too (roughly 10x the product size for large
  arrays), so keep very large products, such as images, to a few tens of MiB or lower `max_file_size`.
- FPrime 4 `CfdpManager` transfers also use the file APID. They are passed through to the OpenC3 CFDP plugin
  (see below) and are not reassembled here.

## CFDP with CfdpManager

FPrime 4.4's `Svc/Ccsds/CfdpManager` speaks CCSDS CFDP (Class 1 and Class 2). With a dictionary that
contains a CfdpManager, `fprime_parser.py` also generates a `CFDP_PDU` command and telemetry packet. Each
carries one raw CFDP PDU on APID 3 behind the `00 03` packet descriptor, which is what CfdpManager sends
and expects. The [OpenC3 CFDP plugin](https://github.com/OpenC3/openc3-cosmos-cfdp) and the
[CFDP tool](https://github.com/OpenC3/openc3-cosmos-tool-cfdp) then work unmodified.

### Installing the CFDP plugin

When installing `openc3-cosmos-cfdp`, set these variables (assuming the target is named `FPRIME`):

| Variable | Value |
|----------|-------|
| `cfdp_cmd_target_name` / `cfdp_tlm_target_name` | `FPRIME` |
| `cfdp_cmd_packet_name` / `cfdp_tlm_packet_name` | `CFDP_PDU` |
| `cfdp_cmd_item_name` / `cfdp_tlm_item_name` | `PDU` |
| `source_entity_id` | `100`, the COSMOS entity (CfdpManager's `FileInDefaultDestEntityId`) |
| `destination_entity_id` | `42`, CfdpManager's `LocalEid` |

MIB settings are `OPTION` lines in the CFDP plugin's plugin.txt, not install variables, and most of them
are not in the shipped file. While installing (or upgrading) the CFDP plugin, open the plugin.txt editor.
Replace the four `OPTION source_entity_id` / `tlm_info` / `destination_entity_id` / `cmd_info` lines with the
block below, and leave the `root_path` and later lines as they are. Each option applies to the entity ID
declared most recently above it, so the order matters.

```
  # Local (COSMOS) entity: accept PDUs without a CRC, never ask for Class 1 closure
  OPTION source_entity_id <%= source_entity_id %>
  OPTION tlm_info <%= cfdp_tlm_target_name %> <%= cfdp_tlm_packet_name %> <%= cfdp_tlm_item_name %>
  OPTION crcs_required false
  OPTION transaction_closure_requested CLOSURE_NOT_REQUESTED
  # Remote (F Prime CfdpManager) entity: send PDUs without a CRC
  OPTION destination_entity_id <%= destination_entity_id %>
  OPTION cmd_info <%= cfdp_cmd_target_name %> <%= cfdp_cmd_packet_name %> <%= cfdp_cmd_item_name %>
  OPTION crcs_required false
  OPTION default_checksum_type 0
  OPTION protocol_version_number 1
  OPTION entity_id_length 0
  OPTION sequence_number_length 3
  OPTION maximum_file_segment_length 960
  OPTION ack_timer_interval 5
  OPTION nak_timer_interval 5
  OPTION check_interval 5
  OPTION cmd_delay 0.01
```

Why these options:

- **No PDU CRC:** CfdpManager does not support PDU CRCs. `crcs_required false` appears twice on purpose:
  on the local entity it stops COSMOS rejecting received PDUs that have no CRC, and on the remote entity it
  stops COSMOS adding CRCs to the PDUs it sends.
- **Modular checksum:** it only does the modular file checksum (type 0).
- **No closure:** it never sends a Finished PDU for Class 1, so closure must not be requested.
- **Segment length:** `maximum_file_segment_length` keeps a File Data PDU, plus its space packet header,
  descriptor and TC frame overhead, within one 1024-byte TC frame. The overhead is 29 bytes, so the most
  that fits is 995.
- **Timers:** the defaults are 600 s, which is too slow for interactive use, so they are shortened.
- **Rate limit:** `cmd_delay` paces outgoing PDUs. CfdpManager queues each uplinked PDU on its component queue and asserts
  (FATAL) if that queue overflows. Over TCP nothing else limits the rate, so a fast burst can crash the flight software.
  Size the delay and the CfdpManager queue depth for your link.

### Pushing a file to FPrime

Use the CFDP tool's Put dialog, or a script:

```python
from cfdp import cfdp_put
cfdp_put(destination_entity_id=42, source_file_name="medium.bin",
         destination_file_name="/files/uplink/medium.bin", transmission_mode="ACKNOWLEDGED")
```

`source_file_name` is relative to the CFDP plugin's `root_path`.

### Pulling a file from FPrime

CfdpManager doesn't support CFDP proxy put (the CFDP tool's "remote entity" get). Send its `SendFile`
command instead:

```python
cmd("FPRIME FILEHANDLINGCFDP.CFDPMANAGER.SENDFILE with CHANNELID 0, DESTID 100, CFDPCLASS CLASS_2, "
    "KEEP KEEP, PRIORITY 0, SOURCEFILENAME '/files/medium.bin', DESTFILENAME 'medium.bin'")
```

The transaction appears in the CFDP tool, and the file is written under the CFDP plugin's `root_path`.

### Not supported by CfdpManager (FPrime 4.4.1)

- Class 1 closure (Finished PDUs)
- proxy put / remote get, directory listings, filestore requests and messages to user
- PDU CRCs
- non-modular checksums
- files of 4 GiB or more

Your deployment's TM aggregator must fit CfdpManager's packets. With the default ComCcsds configuration
(1024-byte TM frames, no packet spanning), only space packets of 1009 bytes or less fit. CfdpManager's
default `OutgoingFileChunkSize` of 992 makes 1011-byte packets, and FPrime asserts on the first full File
Data PDU. Either enable `ComCcsdsConfig.Aggregator.enablePacketSpanning` (this plugin reassembles spanned
packets), or set `OutgoingFileChunkSize` to 984 or less.

A deployment also can't run FileUplink/FileDownlink alongside CfdpManager, because FPrime routes all of
APID 3 to one component.

`fprime-test/` builds an FPrime 4.4.1 Ref deployment with CfdpManager for testing; see
[fprime-test/README.md](fprime-test/README.md). `targets/FPRIME/procedures/cfdp_test.py` is an end-to-end
test against it.

## Contributions

By submitting a Contribution, you agree to the following terms:

1. **Grant of License**: You hereby grant to OpenC3, Inc. a perpetual, irrevocable, worldwide, royalty-free, fully paid-up, non-exclusive, sublicensable, and transferable license to use, reproduce, prepare derivative works of, publicly display, publicly perform, distribute, sublicense, sell, and otherwise exploit your Contribution and any derivative works thereof, for any purpose whatsoever, without restriction or obligation to you.

2. **Grant of Patent License**: You hereby grant to OpenC3, Inc. a perpetual, irrevocable, worldwide, royalty-free, fully paid-up, non-exclusive, sublicensable, and transferable patent license to make, have made, use, offer to sell, sell, import, and otherwise transfer your Contribution, where such license applies only to those patent claims licensable by you that are necessarily infringed by your Contribution alone or by combination of your Contribution with the Software.

3. **Representation of Authority**: You represent that you are legally entitled to grant the above licenses. If your employer has rights to intellectual property you create, you represent that you have received permission to make the Contribution on behalf of your employer, or that your employer has waived such rights for your Contribution.

4. **Representation of Originality**: You represent that each Contribution is your original creation and that you have the right to grant the licenses herein. You will identify any third-party licenses or restrictions associated with any part of your Contribution.

5. **No Obligation**: You acknowledge that OpenC3, Inc. is under no obligation to accept, use, or include any Contribution.

6. **No Expectation of Compensation**: Contributions are provided voluntarily. You have no expectation of compensation, royalties, or other payment for any Contribution, regardless of how OpenC3, Inc. uses it.

Contributing is easy.

1. Fork the project
2. Create a feature branch
3. Make your changes
4. Submit a pull request

This protects both you and us and you retain full rights to any code you write.

## License

This OpenC3 plugin is released under the MIT License. See [LICENSE.txt](LICENSE.txt)
