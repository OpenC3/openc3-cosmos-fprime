# CLAUDE.md

OpenC3 COSMOS plugin for F Prime flight software (tested against F Prime 3.6, 4.2 and 4.4). The plugin is
Python (`LANGUAGE python`); `README.md` is the user-facing documentation.

## Commands

- Tests: `.venv/bin/python -m pytest tests/ -q` (CI runs the same on Python 3.12 with `pytest coverage openc3`)
- Regenerate the target: `python lib/fprime_parser.py FPRIME <Dictionary.json> [SPACE_PACKET|FPRIME]`
  - The shipped target comes from `fprime-test/RefTopologyDictionary.json` (F Prime 4.4.1 Ref + CfdpManager).
- Build the gem: `rake build VERSION=X.Y.Z`

## Layout

- `lib/fprime_parser.py` generates everything in `targets/FPRIME/cmd_tlm/` plus
  `targets/FPRIME/lib/fprime_event_conversion.py` and `fprime_dp_dictionary.py`.
  **These are generated files ("Do not edit directly")**: change the parser and regenerate, never hand-edit.
  `tests/test_generated_target.py` loads the committed output, so commit regenerated files with parser changes.
- Pure decoding modules, with no COSMOS imports so they unit-test in isolation:
  `fprime_file_assembler.py`, `fprime_dp_decoder.py`, `fprime_framing.py`, `fprime_dp_packets.py`.
  Keep them that way and standard-library only.
- COSMOS protocols: `fprime_file_downlink_protocol.py`, `fprime_subpacketizer.py`, and the `ccsds_*` protocols.
- `plugin.txt` picks the protocol chain by `fprime_headers`: `SPACE_PACKET` (F Prime 4.x, CCSDS space packets in
  TC/TM frames) or `FPRIME` (F Prime 3.x framing).
- `fprime-test/` builds a real F Prime 4.4.1 deployment in Docker for manual end-to-end testing
  (`targets/FPRIME/procedures/cfdp_test.py`); see `fprime-test/README.md`. Not run in CI.

## Rules that are easy to break

- Every wire and on-disk value is **big-endian**.
- **Never hardcode framework type widths.** Read them from the dictionary; fall back only for v3 dictionaries
  that lack the alias typedefs. `FwSizeStoreType` is U16 before 4.4.0 and U64 on unix from 4.4.0, and it sizes
  string length prefixes (commands and telemetry), array counts and the data product `DataSize`.
- F Prime `bool` is one byte, `0xFF` true / `0x00` false.
- Command string parameters are a `<NAME>_LENGTH` parameter (auto-filled, hidden) followed by a
  `VARIABLE_BIT_SIZE` string. An empty string encodes as a zero length, not padding.
- `fprime_file_downlink_protocol.py` must stay the **last READ protocol** in both header modes
  (`tests/test_plugin_txt.py`). Synthesized data product packets must come out right after the file's END
  packet, before new real telemetry.
- File handling failures (bucket down, malformed packet, oversize file) must never break the telemetry stream:
  the original packet still passes through. Downlinked file names are flattened to a bare name under the
  target's bucket folder, whatever path the spacecraft sends.
- An unknown data product record keeps the records decoded so far and sets `DECODE_OK` false; it does not raise.

## Packet descriptor 3 (APID 3) carries two different things

- Legacy `Fw::FilePacket` (FileUplink/FileDownlink): first byte after the descriptor is a type 0–3.
- CfdpManager CFDP PDUs: `00 03` descriptor then the raw PDU, whose first byte has version bits
  `(b >> 5) == 1`. These pass through as `CFDP_PDU` telemetry and must **never** reach `FileAssembler`.
- A deployment runs one or the other; F Prime routes all of APID 3 to a single component.

## CFDP

- `CFDP_PDU` command/telemetry is generated only when the dictionary has a CfdpManager **and** headers are
  `SPACE_PACKET`. Dictionaries without one, including FileDownlink's own `SendFile`, must gain no CFDP packets.
- The OpenC3 CFDP plugin and CFDP tool are used unmodified; all integration lives in this plugin plus the
  CFDP plugin's install-time configuration (documented in `README.md`).
- CfdpManager 4.4.1 limits: no PDU CRC, modular checksum only, no Class 1 closure (it never sends FIN for
  Class 1), no proxy put / remote get, 32-bit file sizes. Its Metadata PDU puts `closure_requested` at bit 7
  instead of 6; this is harmless, so there is deliberately no workaround.
- Defaults: F Prime entity (`LocalEid`) 42, COSMOS entity (`FileInDefaultDestEntityId`) 100. A File Data PDU
  at `maximum_file_segment_length` must fit one 1024-byte TC frame (29 bytes overhead).

## Conventions

- New source files start with the MIT header used in `lib/` (`# Copyright 2026 OpenC3, Inc.` ...).
- Conventional commits: `feat(parser): ...`, `fix(downlink): ...`, `test(...)`, `docs: ...`.
