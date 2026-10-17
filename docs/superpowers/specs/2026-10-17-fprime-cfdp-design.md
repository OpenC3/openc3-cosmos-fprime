# F Prime CFDP Support — Design

Date: 2026-10-17
Branch: builds on `feature/data-products`

## Intent

An operator running an F Prime **v4.4** deployment that uses `Svc/Ccsds/CfdpManager` should be able to push files to it and pull files from it through COSMOS. They use the existing OpenC3 CFDP plugin (`/Users/jmthomas/Development/openc3-cosmos-cfdp`) and the CFDP GUI tool (`openc3-cosmos-tool-cfdp`).

Today this plugin only understands the legacy `FileDownlink` file packets. F Prime 4.x's real CFDP traffic is invisible to it, and the README says so (README.md L50).

## Goals

1. **Push (COSMOS → F Prime):** a CFDP Put from the GUI's Put dialog, or `cfdp_put` in a script, delivers a file to the F Prime filesystem. It must work for Class 1 (unacknowledged) and Class 2 (acknowledged).
2. **Pull (F Prime → COSMOS):** the operator sends the dictionary-generated CfdpManager `SENDFILE` command from COSMOS. The resulting transaction appears in the CFDP GUI, and the file lands in the CFDP plugin's storage. This must also work for Class 1 and Class 2.
3. **No changes to the CFDP plugin or the GUI.** Everything is done in this plugin plus install-time configuration of the CFDP plugin (`plugin.txt` variables and MIB options).
4. **A committed, reproducible F Prime 4.4 test deployment** (Dockerfile, deployment changes, sample files) that runs the real CfdpManager. All of the above is verified against it end to end.

## Non-goals

- **Pulling from the GUI's Put dialog** (proxy put / "remote get"). CfdpManager does not implement proxy put or messages to user. The user explicitly accepted `SENDFILE` as the pull mechanism.
- **Remote directory listings, filestore requests, messages to user, Prompt, Keep Alive:** CfdpManager does not support any of them.
- **Running legacy FileUplink/FileDownlink and CfdpManager in one deployment.** F Prime's router sends all of APID 3 to a single `fileOut`, so deployments pick one. (Downlink classification below still tolerates both kinds of packet on APID 3, for robustness.)
- **Supporting F Prime v3.x CFDP.** It doesn't exist; CfdpManager is v4 only.
- **PlaybackDirectory / PollDirectory end-to-end testing.** These are ordinary dictionary commands, so they will be present, but they are not part of the acceptance test.
- **Adding a ground-side legacy FileUplink sender.**

## Anti-goals (would be failure even if CFDP "works")

- Anything that requires editing `openc3-cosmos-cfdp` or `openc3-cosmos-tool-cfdp`.
- Breaking existing behavior:
  - F Prime 3.x (`FPRIME` headers) or 4.x deployments without CfdpManager gain CFDP packets or have their protocol behavior changed.
  - Legacy FileDownlink reassembly or data-product decoding regresses.
  - The one intended exception is the string-parameter fix (§2), which corrects command encoding in both header modes.
- CFDP PDUs being fed to the legacy `FileAssembler`. That produces spurious errors or `.incomplete` files.

## Facts the design rests on (researched 2026-10-16, F Prime tag v4.4.1)

These describe how F Prime 4.4.1 CfdpManager puts PDUs on the wire.

- **Packet descriptor:** CfdpManager reuses descriptor `FW_PACKET_FILE` = 3. There is no new descriptor and no new APID.
- **Downlink:**
  - The buffer is the big-endian U16 `00 03` followed by the raw CFDP PDU.
  - ComQueue sets the APID from that U16, and SpacePacketFramer adds a 6-byte primary header with APID 3.
  - On the wire: `[SPP hdr, APID=3][00 03][CFDP PDU]`, inside TM frames.
- **Uplink:**
  - The required layout is the same: `SPP(APID 3)` with the data field `00 03` + PDU.
  - FprimeRouter sends APID 3 to `fileOut`. `CfdpManager::dataIn_handler` checks the leading U16 == 3 and strips it.
- **Telling CFDP apart from legacy file packets on APID 3:**
  - A CFDP PDU's first byte carries version = 1 in bits 7-5, so it falls in 0x20–0x3F.
  - Legacy `Fw::FilePacket` has a type byte 0–4 in the same position.
- **Supported CFDP features:**
  - Class 1 and Class 2, with Metadata, FileData, EOF, FIN, ACK and NAK.
  - **No** PDU CRC (the TX CRC flag is always 0).
  - Modular checksum only.
  - 32-bit file sizes.
  - Segment metadata is not supported.
  - Entity IDs and transaction sequence numbers are encoded at minimum width. The receiver accepts whatever widths the header declares.
- **Defaults:**
  - Parameter `LocalEid` = 42.
  - `FileInDefaultDestEntityId` = 100.
  - `OutgoingFileChunkSize` = 992.
  - `MaxPduSize` = 1024.
  - Incoming PDUs must have dest EID == `LocalEid`.
- **v4.4.1 bug:** in the Metadata PDU, F Prime encodes `closure_requested` at **bit 7** of the first body byte. CCSDS, the OpenC3 CFDP plugin (`cfdp_pdu_metadata.rb` L79-86) and F Prime devel all use **bit 6**, and bit 7 is segmentation control.
  - This turns out to be harmless; see §4.
- **Not in Ref:** CfdpManager is not in the Ref deployment. v4.4.1 ships `Svc/Subtopologies/FileHandlingCfdp` (cfdpManager + fileManager + prmDb) as a replacement for `FileHandling`.
  - That subtopology's sdd wiring example uses port names that do not exist in v4.4.1, such as `Ports_ComBufferQueue.CFDP` and `cfdpUplinkOut`.
  - In practice CfdpManager channel 0 takes over ComCcsds's FILE slots, both `Ports_ComBufferQueue.FILE` and `fileUplinkOut` / `fileUplinkReturnIn`.
  - It needs `run1Hz` from a rate group that really runs at 1 Hz.
- **No ground support anywhere:** fprime-gds does not implement CFDP.
- **CFDP plugin interface:**
  - It sends each PDU with `cmd(<cmd_info target>, <packet>, {<item> => pdu_bytes})`.
  - It receives by subscribing to the decom topic for `tlm_info` target/packet and reading a BLOCK item (which must not be HIDDEN).
  - It reads entity ID / sequence number widths and the CRC flag from each received PDU's header.

## Design

### 1. Generated `CFDP_PDU` command and telemetry packets (parser)

- **Trigger:** `fprime_parser.py` emits the packets **only when the dictionary contains CfdpManager commands**, i.e. any command whose name ends in `.SendFile` on a component of type CfdpManager. The exact detection is the builder's call, but dictionaries without CfdpManager must not gain any CFDP packets.
- **Header mode:** emit them only in `SPACE_PACKET` header mode, since CfdpManager is v4-only.

**`COMMAND <TARGET> CFDP_PDU`:**
- It uses the same CCSDS header the parser already emits for commands (version, type=1, SHF, `CCSDS_APID`, seq flags, `CCSDS_SEQ_CNT`, `CCSDS_LENGTH`). The header has:
  - `CCSDS_APID` = 3, as the ID parameter;
  - the 16-bit descriptor field = 3;
  - then `PDU` as a variable `BLOCK`.
- `CCSDS_SEQ_CNT` must exist, because `ccsds_seqcnt_protocol.py` writes it by name.
- It must pass through the existing write chain (length → seqcnt → TCTF) unchanged.

**`TELEMETRY <TARGET> CFDP_PDU`:**
- The usual CCSDS TM header, with the APID ID item = 3, then the 16-bit descriptor.
- `PDU`: a `BLOCK` covering the whole PDU, starting at the PDU's first byte and running to the end of the packet.
- An ID item covering the CFDP version bits (bits 7-5 of the PDU's first byte) = 1, so it never collides with the legacy `FILE_*` packets. Those are identified by an 8-bit `FILE_TYPE` 0–3, whose top 3 bits are 0.
- `PDU` must not be HIDDEN.
- Decoding PDU fields into separate items is **optional**. If added, keep it to a few header fields useful for debugging (direction, PDU type, source/dest EID). The builder may skip it.

**Naming:**
- The default CFDP plugin settings for this target become `cmd_info FPRIME CFDP_PDU PDU` and `tlm_info FPRIME CFDP_PDU PDU`.
- Regenerate and commit `targets/FPRIME/cmd_tlm/*` and the generated `lib` files from the test deployment's dictionary. This also fixes the currently stale committed files, which predate the data-products parser.

### 2. Fix string command parameters (parser)

`SENDFILE` takes `sourceFileName` / `destFileName` strings. Today the parser emits command strings as a fixed-size `STRING` with no length prefix (parser L197-198, and the known gap in the data-products plan). F Prime deserializes command strings as a `FwSizeStoreType` length prefix followed by the characters, so `SENDFILE` would fail today.

The fix:
- Emit command string parameters the way telemetry strings are already emitted (`emit_variable_string`): a `<NAME>_LENGTH` parameter of `size_store` bits, then a 0-bit `STRING` with `VARIABLE_BIT_SIZE <NAME>_LENGTH 8 0`.
- The length parameter should be auto-populated (COSMOS fills `VARIABLE_BIT_SIZE` length items on write) and ignored in the UI via `IGNORE_PARAMETER` or equivalent, so operators type only the string.
- **Builder to verify:** confirm with a unit test that COSMOS Python `PacketConfig` and command building honor `VARIABLE_BIT_SIZE` on command parameters. If not, fall back to another approach that produces the correct bytes.

This applies to all command string parameters, not just CfdpManager's, in **both** header modes, because the current encoding is wrong for 3.x as well. The length width comes from the dictionary's `size_store` width (the existing v3 fallback is 16 bits). *My call:* the review flagged that this conflicts with the "unchanged output" anti-goal; the anti-goal now names it as the exception. Regression tests assert that CFDP packets are absent without CfdpManager, not that `cmd.txt` is byte-identical. Remove the "string command parameters" non-goal from the README.

### 3. Downlink: keep CFDP PDUs away from the legacy file assembler

`fprime_file_downlink_protocol.py` currently feeds every descriptor-3 packet to `FileAssembler`. Change that:
- If the byte after the descriptor has version bits (7-5) == 1, the packet is a CFDP PDU.
- Pass CFDP PDUs through untouched (they are then identified as `CFDP_PDU`) and **do not** give them to the assembler.
- Legacy file packets keep working as before.
- The protocol must remain last in the READ chain.

### 4. No closure-bit workaround (dropped after reading the source)

I read the v4.4.1 source (`Svc/Ccsds/CfdpManager/Engine.cpp` L192-208, `Types/MetadataPdu.cpp` L118-180, `TransactionRx.cpp`) and found the bit-7 bug is harmless here:

- **Sending:** F Prime sets closure = 0 for Class 1 and 1 for Class 2. Class 2 always closes with a FIN regardless of the flag, so the flag means nothing there.
- **Receiving:** F Prime parses the flag but never reads it. It sends a FIN only in Class 2 (`r2SubstateSendFin`), so **Class 1 closure is not supported at all**, whatever the bit position.
- **On the COSMOS side:** the CFDP plugin reads F Prime's bit 7 as segmentation control, which it ignores on receive (`cfdp_receive_transaction.rb` always uses NOT_PRESERVED).

So there is no new protocol and no `fprime_cfdp_closure_bit_fix` variable. Instead the README (§5) must set the CFDP plugin's local-entity `transaction_closure_requested` to not requested. That stops Class 1 pushes from waiting for a FIN that F Prime will never send (the CFDP plugin defaults to CLOSURE_REQUESTED). The README should note "Class 1 closure is unsupported by CfdpManager 4.4.1".

### 5. CFDP plugin configuration (documentation only, no code change)

Add a README section ("CFDP with CfdpManager") that gives the exact install-time settings for `openc3-cosmos-cfdp` against an F Prime 4.4 target named FPRIME.

**plugin.txt variables:**
- `cfdp_cmd_target_name FPRIME`
- `cfdp_cmd_packet_name CFDP_PDU`
- `cfdp_cmd_item_name PDU`
- the same three values for `tlm`
- `source_entity_id 100` (COSMOS = F Prime's `FileInDefaultDestEntityId`)
- `destination_entity_id 42` (F Prime `LocalEid`)

**Remote-entity MIB options:**
- `crcs_required false`
- `default_checksum_type 0` (modular)
- `maximum_file_segment_length` sized so that a FileData PDU plus the 2-byte descriptor, 6-byte SPP header and TC frame overhead fits the TCTF limit (`MAX_LENGTH_VALUE` 1023, about 1016 bytes of frame data). The builder computes the exact value and verifies it on the wire.
- `protocol_version_number 1`
- default transmission mode as desired
- `ack_timer_interval` / `nak_timer_interval` / inactivity values short enough for interactive use (the 600 s defaults are too slow for testing)

**Local-entity options:**
- `crcs_required false`
- `transaction_closure_requested` set to not requested (see §4)

**Pull example:** a `SENDFILE` command, e.g. `cmd("FPRIME CFDPMANAGER.SENDFILE with CHANNELID 0, DESTID 100, CFDPCLASS CLASS_2, KEEP KEEP, PRIORITY 0, SOURCEFILENAME '/files/x.bin', DESTFILENAME 'x.bin'")`. Use the real generated names. Also say where the file lands in the CFDP plugin's storage.

**Push example:** using the GUI and `cfdp_put`.

**Pointers:** the test deployment, and the note that Class 1 closure is unsupported by CfdpManager.

Also remove the CfdpManager "not supported" line from the README.

### 6. Committed F Prime 4.4 test deployment

New top-level directory `fprime-test/`. The name is my call; the builder may pick another sensible one. It contains:

- **Dockerfile:**
  - Pins nasa/fprime at tag **v4.4.1** and builds a deployment based on Ref with CfdpManager wired in.
  - Use the `FileHandlingCfdp` subtopology in place of `FileHandling`.
  - Wire CfdpManager channel 0 into ComCcsds's FILE downlink queue slot and its uplink `fileUplinkOut`/`fileUplinkReturnIn`, plus buffer allocate/deallocate and `run1Hz` from a 1 Hz rate group.
  - The builder works out the exact v4.4.1 port names (the subtopology sdd example is wrong for 4.4.1).
  - **Must build and run on arm64** (the dev machine is Apple Silicon with Docker 29) and ideally amd64.
- **Deployment changes:** the topology/FPP diffs or files needed. Prefer the smallest diff against Ref. Copy or patch files in the Dockerfile rather than vendoring all of Ref, if practical.
- **Link:**
  - The deployment is a **TCP server on port 50000** using CCSDS space packets in TC (uplink) / TM (downlink) frames, matching the existing plugin defaults: SCID 0x44, TC VCID 1, 1024-byte TM frames, CRC on, no randomization.
  - The COSMOS interface is a TCP client to `host.docker.internal:50000`.
  - If Ref's default comm driver is a TCP client, switch it to the TCP server driver or configure it so it listens.
  - If Ref's framing defaults differ from the plugin defaults, prefer changing the deployment rather than the plugin defaults. Note any unavoidable plugin-variable differences in the README.
- **Configuration:** CfdpManager `LocalEid` stays at 42 and `FileInDefaultDestEntityId` at 100. Use short `ChannelConfig` timers where helpful for testing.
- **Files:**
  - A committed `fprime-test/files/` with a few sample files is copied into the image at `/files` for pulls: a small text file, one larger than several PDUs (e.g. ~100 KB) and one that is not a multiple of the chunk size.
  - Pushed files should be written somewhere inspectable, e.g. `/files/uplink/` or a bind mount.
- **Dictionary:** the build's JSON dictionary is extracted (documented `docker cp` or a build stage) and run through `fprime_parser.py` to regenerate `targets/FPRIME/`.
- **README / `fprime-test/README.md`:** how to build, run and point COSMOS at it.

### 7. End-to-end test

Add a COSMOS test procedure to the FPRIME target, e.g. `targets/FPRIME/procedures/cfdp_test.py`, written with `cfdp_put` and `cmd`. The builder chooses Python or Ruby to match the plugin (`LANGUAGE python`). It runs the acceptance checks below against the container.

Acceptance checks:
1. Push a multi-PDU file with Class 1, then with Class 2. The file arrives on F Prime byte-identical (checked through the container filesystem or a FileManager command).
2. Pull a multi-PDU file with `SENDFILE` Class 1, then Class 2. The transaction shows in the CFDP plugin's transactions/indications with a successful condition, and the stored file is byte-identical to the source in `fprime-test/files/`.
3. Existing telemetry channels and events still decode while transfers run.

Automated unit tests (pytest, no container):
- parser emission of `CFDP_PDU` cmd/tlm (present with CfdpManager, absent without)
- string command parameter encoding
- the downlink protocol's classification

The container-based end-to-end run is manual (documented steps), not in CI. *My call:* building F Prime in CI is slow and not asked for.

## Left to the builder

- Exact CfdpManager detection in the parser and exact packet item layouts, within the constraints above.
- Dockerfile structure, base image, and how deployment changes are applied.
- The exact `maximum_file_segment_length` and timer values.
- Whether to decode PDU header fields into telemetry items.
- Test procedure language and structure.
