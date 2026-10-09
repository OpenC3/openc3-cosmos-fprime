# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for fprime_parser.py.

The parser is a script that writes into <repo>/targets/<TARGET>, so each test
copies it into a temp directory, runs it as a subprocess against a synthetic
F Prime dictionary, and then inspects (and loads through OpenC3's
PacketConfig) the generated cmd.txt, tlm.txt and fprime_event_conversion.py.
"""

import copy
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openc3.packets.packet_config import PacketConfig

PARSER = Path(__file__).resolve().parent.parent / "lib" / "fprime_parser.py"
TARGET = "FSW"

# CCSDS primary header (48 bits) + FPRIME_APID (16) + FPRIME_OPCODE (32)
CCSDS_CMD_HEADER_BITS = 96
# FPRIME_SYNC + FPRIME_SIZE + FPRIME_PACKET_ID + FPRIME_OPCODE + FPRIME_CRC32
FPRIME_CMD_OVERHEAD_BITS = 32 * 5


def u(size):
    return {"name": f"U{size}", "kind": "integer", "size": size, "signed": False}


def i(size):
    return {"name": f"I{size}", "kind": "integer", "size": size, "signed": True}


def f(size):
    return {"name": f"F{size}", "kind": "float", "size": size}


def ref(name):
    return {"name": name, "kind": "qualifiedIdentifier"}


BOOL = {"name": "bool", "kind": "bool", "size": 8}
STRING20 = {"name": "string", "kind": "string", "size": 20}

TYPE_DEFINITIONS = [
    {
        "kind": "enum",
        "qualifiedName": "Ns.Mode",
        "representationType": u(8),
        "enumeratedConstants": [{"name": "OFF", "value": 0}, {"name": "ON", "value": 1}],
        "default": "Ns.Mode.ON",
    },
    {
        "kind": "enum",
        "qualifiedName": "Ns.Signed",
        "representationType": i(32),
        "enumeratedConstants": [{"name": "NEG", "value": -1}, {"name": "POS", "value": 1}],
        "default": "Ns.Signed.POS",
    },
    {"kind": "alias", "qualifiedName": "Ns.Count", "underlyingType": u(16)},
    {"kind": "alias", "qualifiedName": "Ns.CountAlias", "underlyingType": ref("Ns.Count")},
    {"kind": "alias", "qualifiedName": "Ns.ModeAlias", "underlyingType": ref("Ns.Mode")},
    {
        # Members intentionally listed out of index order
        "kind": "struct",
        "qualifiedName": "Ns.Point",
        "members": {
            "y": {"type": f(32), "index": 1, "annotation": "Y coord"},
            "x": {"type": f(32), "index": 0, "annotation": "X coord"},
        },
    },
    {"kind": "array", "qualifiedName": "Ns.U32Arr", "size": 3, "elementType": u(32)},
    {"kind": "array", "qualifiedName": "Ns.I8Arr", "size": 2, "elementType": i(8)},
    {"kind": "array", "qualifiedName": "Ns.F64Arr", "size": 2, "elementType": f(64)},
    {"kind": "array", "qualifiedName": "Ns.BoolArr", "size": 4, "elementType": BOOL},
    {"kind": "array", "qualifiedName": "Ns.AliasArr", "size": 2, "elementType": ref("Ns.CountAlias")},
    {"kind": "array", "qualifiedName": "Ns.ModeArr", "size": 2, "elementType": ref("Ns.Mode")},
    {"kind": "array", "qualifiedName": "Ns.ModeAliasArr", "size": 2, "elementType": ref("Ns.ModeAlias")},
    {"kind": "array", "qualifiedName": "Ns.PointArr", "size": 2, "elementType": ref("Ns.Point")},
    {"kind": "array", "qualifiedName": "Ns.Grid", "size": 2, "elementType": ref("Ns.U32Arr")},
    {
        "kind": "struct",
        "qualifiedName": "Ns.Config",
        "members": {
            "mode": {"type": ref("Ns.Mode"), "index": 0},
            "vals": {"type": ref("Ns.U32Arr"), "index": 1},
        },
    },
    # Shape of Svc.TlmPacketizer in F Prime v4 which originally crashed the
    # parser: array of (array of (struct containing enums))
    {
        "kind": "enum",
        "qualifiedName": "Fw.Enabled",
        "representationType": u(8),
        "enumeratedConstants": [{"name": "DISABLED", "value": 0}, {"name": "ENABLED", "value": 1}],
        "default": "Fw.Enabled.ENABLED",
    },
    {
        "kind": "enum",
        "qualifiedName": "Svc.RateLogic",
        "representationType": i(32),
        "enumeratedConstants": [
            {"name": "SILENCED", "value": 0},
            {"name": "EVERY_MAX", "value": 1},
            {"name": "ON_CHANGE_MIN", "value": 2},
            {"name": "ON_CHANGE_MIN_OR_EVERY_MAX", "value": 3},
        ],
        "default": "Svc.RateLogic.ON_CHANGE_MIN",
    },
    {
        "kind": "struct",
        "qualifiedName": "Svc.TlmPacketizer.GroupConfig",
        "members": {
            "enabled": {"type": ref("Fw.Enabled"), "index": 0},
            "min": {"type": u(32), "index": 3},
            "max": {"type": u(32), "index": 4},
            "rateLogic": {"type": ref("Svc.RateLogic"), "index": 2},
            "forceEnabled": {"type": ref("Fw.Enabled"), "index": 1},
        },
    },
    {
        "kind": "array",
        "qualifiedName": "Svc.TlmPacketizer.GroupConfigs",
        "size": 4,
        "elementType": ref("Svc.TlmPacketizer.GroupConfig"),
    },
    {
        "kind": "array",
        "qualifiedName": "Svc.TlmPacketizer.SectionConfigs",
        "size": 1,
        "elementType": ref("Svc.TlmPacketizer.GroupConfigs"),
    },
    {
        "kind": "array",
        "qualifiedName": "Svc.TlmPacketizer.SectionEnabled",
        "size": 1,
        "elementType": ref("Fw.Enabled"),
    },
]

# (name, type) for every type we want exercised as a command param and channel
CASES = [
    ("U8", u(8)),
    ("U64", u(64)),
    ("I16", i(16)),
    ("F32", f(32)),
    ("F64", f(64)),
    ("BOOL", BOOL),
    ("STR", STRING20),
    ("ENUM", ref("Ns.Mode")),
    ("SENUM", ref("Ns.Signed")),
    ("ALIAS", ref("Ns.CountAlias")),
    ("ENUM_ALIAS", ref("Ns.ModeAlias")),
    ("STRUCT", ref("Ns.Point")),
    ("U32_ARR", ref("Ns.U32Arr")),
    ("I8_ARR", ref("Ns.I8Arr")),
    ("F64_ARR", ref("Ns.F64Arr")),
    ("BOOL_ARR", ref("Ns.BoolArr")),
    ("ALIAS_ARR", ref("Ns.AliasArr")),
    ("ENUM_ARR", ref("Ns.ModeArr")),
    ("ENUM_ALIAS_ARR", ref("Ns.ModeAliasArr")),
    ("STRUCT_ARR", ref("Ns.PointArr")),
    ("NESTED_ARR", ref("Ns.Grid")),
    ("STRUCT_WITH_ARR", ref("Ns.Config")),
    ("SECTION_CONFIGS", ref("Svc.TlmPacketizer.SectionConfigs")),
    ("SECTION_ENABLED", ref("Svc.TlmPacketizer.SectionEnabled")),
]

# Bits each case contributes to a command (strings are fixed size in commands)
CASE_CMD_BITS = {
    "U8": 8,
    "U64": 64,
    "I16": 16,
    "F32": 32,
    "F64": 64,
    "BOOL": 8,
    "STR": 20 * 8,
    "ENUM": 8,
    "SENUM": 32,
    "ALIAS": 16,
    "ENUM_ALIAS": 8,
    "STRUCT": 64,
    "U32_ARR": 96,
    "I8_ARR": 16,
    "F64_ARR": 128,
    "BOOL_ARR": 32,
    "ALIAS_ARR": 32,
    "ENUM_ARR": 16,
    "ENUM_ALIAS_ARR": 16,
    "STRUCT_ARR": 128,
    "NESTED_ARR": 192,
    "STRUCT_WITH_ARR": 8 + 96,
    "SECTION_CONFIGS": 4 * (8 + 8 + 32 + 32 + 32),
    "SECTION_ENABLED": 8,
}


def _build_dictionary(framework_version="v4.2.2"):
    commands = [
        {
            "name": "Ns.comp.NO_ARGS",
            "commandKind": "async",
            "opcode": 0x100,
            "formalParams": [],
            "annotation": "Line one\r\nline two",
        }
    ]
    channels = []
    for index, (name, t) in enumerate(CASES):
        commands.append(
            {
                "name": f"Ns.comp.CMD_{name}",
                "commandKind": "async",
                "opcode": 0x200 + index,
                "formalParams": [{"name": "val", "type": t, "annotation": f"{name} param"}],
            }
        )
        channels.append({"name": f"Ns.comp.Tlm{name}", "id": 0x300 + index, "type": t})
    commands.append(
        {
            "name": "Ns.comp.MULTI",
            "commandKind": "async",
            "opcode": 0x400,
            "formalParams": [
                {"name": "a", "type": u(8)},
                {"name": "b", "type": ref("Ns.ModeArr")},
                {"name": "c", "type": i(32)},
            ],
        }
    )
    channels.append(
        {
            "name": "Ns.comp.Limited",
            "id": 0x500,
            "type": f(32),
            "format": "{.2f}",
            "limits": {"high": {"yellow": 10, "red": 20}, "low": {"yellow": -10, "red": -20}},
        }
    )
    channels.append({"name": "Ns.comp.Formatted", "id": 0x501, "type": u(16), "format": "{x}"})
    events = [
        {"name": "Ns.comp.NoArgs", "id": 0x600, "severity": "ACTIVITY_HI", "formalParams": [], "format": "Hello"},
        {
            "name": "Ns.comp.Scalars",
            "id": 0x601,
            "severity": "WARNING_LO",
            "formalParams": [
                {"name": "a", "type": u(16)},
                {"name": "b", "type": i(8)},
                {"name": "c", "type": f(32)},
                {"name": "d", "type": BOOL},
                {"name": "e", "type": STRING20},
            ],
            "format": "a={} b={} c={.1f} d={} e={}",
        },
        {
            "name": "Ns.comp.Complex",
            "id": 0x602,
            "severity": "ACTIVITY_LO",
            "formalParams": [
                {"name": "mode", "type": ref("Ns.ModeAlias")},
                {"name": "modes", "type": ref("Ns.ModeArr")},
                {"name": "pt", "type": ref("Ns.Point")},
            ],
            "format": "mode={} modes={} pt={}",
        },
    ]
    return {
        "metadata": {"deploymentName": "Test", "frameworkVersion": framework_version},
        "typeDefinitions": copy.deepcopy(TYPE_DEFINITIONS),
        "commands": commands,
        "events": events,
        "telemetryChannels": channels,
    }


def _run(tmp_path, dictionary=None, extra_args=(), args=None):
    """Copy the parser into tmp_path/lib and run it. Returns CompletedProcess."""
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    shutil.copy(PARSER, lib / "fprime_parser.py")
    json_path = tmp_path / "Dictionary.json"
    json_path.write_text(json.dumps(dictionary if dictionary is not None else _build_dictionary()))
    if args is None:
        args = [TARGET, str(json_path), *extra_args]
    return subprocess.run(
        [sys.executable, str(lib / "fprime_parser.py"), *args],
        capture_output=True,
        text=True,
    )


def _target_dir(tmp_path):
    return tmp_path / "targets" / TARGET


def _load_config(tmp_path):
    """Load the generated cmd/tlm definitions through OpenC3's PacketConfig.

    The Python PacketConfig doesn't run ERB, and the target's own subpacketizer
    and event conversion aren't importable here, so those lines are rewritten
    or dropped before loading.
    """
    cmd_tlm = _target_dir(tmp_path) / "cmd_tlm"
    pc = PacketConfig()
    for name in ("cmd.txt", "tlm.txt"):
        lines = []
        for line in (cmd_tlm / name).read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("SUBPACKETIZER") or stripped == "READ_CONVERSION fprime_event_conversion.py":
                continue
            lines.append(line.replace("<%= target_name %>", TARGET))
        loadable = tmp_path / f"loadable_{name}"
        loadable.write_text("\n".join(lines) + "\n")
        pc.process_file(str(loadable), TARGET)
    return pc


def _load_event_conversion(tmp_path):
    path = _target_dir(tmp_path) / "lib" / "fprime_event_conversion.py"
    spec = importlib.util.spec_from_file_location("generated_fprime_event_conversion", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("parser")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    return tmp_path


@pytest.fixture(scope="module")
def config(generated):
    return _load_config(generated)


def _cmd(config, name):
    return config.commands[TARGET][f"NS.COMP.{name}"]


def _tlm(config, name):
    return config.telemetry[TARGET][f"NS.COMP.{name}"]


def _param_names(packet):
    return [item.name for item in packet.sorted_items if not item.name.startswith(("CCSDS_", "FPRIME_", "PACKET_", "RECEIVED_"))]


class TestArguments:
    def test_no_arguments_prints_usage(self, tmp_path):
        result = _run(tmp_path, args=[])
        assert result.returncode == 1
        assert "Usage:" in result.stderr

    def test_missing_dictionary_prints_usage(self, tmp_path):
        result = _run(tmp_path, args=[TARGET])
        assert result.returncode == 1
        assert "Usage:" in result.stderr

    def test_too_many_arguments_prints_usage(self, tmp_path):
        result = _run(tmp_path, extra_args=["FPRIME", "EXTRA"])
        assert result.returncode == 1
        assert "Usage:" in result.stderr

    def test_invalid_header_prints_usage(self, tmp_path):
        result = _run(tmp_path, extra_args=["BOGUS"])
        assert result.returncode == 1
        assert "Usage:" in result.stderr
        assert not (_target_dir(tmp_path) / "cmd_tlm" / "cmd.txt").exists()

    @pytest.mark.parametrize("header", ["FPRIME", "fprime", "Fprime"])
    def test_fprime_header_override(self, tmp_path, header):
        result = _run(tmp_path, extra_args=[header])
        assert result.returncode == 0, result.stderr
        cmd = (_target_dir(tmp_path) / "cmd_tlm" / "cmd.txt").read_text()
        assert "FPRIME_SYNC" in cmd
        assert "CCSDS_VERSION" not in cmd

    @pytest.mark.parametrize("header", ["SPACE_PACKET", "space_packet"])
    def test_space_packet_header_override(self, tmp_path, header):
        result = _run(tmp_path, dictionary=_build_dictionary("v3.4.3"), extra_args=[header])
        assert result.returncode == 0, result.stderr
        cmd = (_target_dir(tmp_path) / "cmd_tlm" / "cmd.txt").read_text()
        assert "CCSDS_VERSION" in cmd
        assert "FPRIME_SYNC" not in cmd

    def test_v4_defaults_to_space_packet(self, tmp_path):
        result = _run(tmp_path, dictionary=_build_dictionary("v4.2.2"))
        assert result.returncode == 0, result.stderr
        assert "CCSDS_VERSION" in (_target_dir(tmp_path) / "cmd_tlm" / "cmd.txt").read_text()

    def test_v3_defaults_to_fprime(self, tmp_path):
        result = _run(tmp_path, dictionary=_build_dictionary("v3.4.3"))
        assert result.returncode == 0, result.stderr
        assert "FPRIME_SYNC" in (_target_dir(tmp_path) / "cmd_tlm" / "cmd.txt").read_text()


class TestGeneratedFiles:
    def test_all_files_written(self, generated):
        target = _target_dir(generated)
        assert (target / "cmd_tlm" / "cmd.txt").is_file()
        assert (target / "cmd_tlm" / "tlm.txt").is_file()
        assert (target / "lib" / "fprime_event_conversion.py").is_file()

    def test_config_loads_without_warnings(self, config):
        assert config.warnings == []

    def test_every_command_generated(self, config):
        names = set(config.commands[TARGET].keys())
        expected = {"NS.COMP.NO_ARGS", "NS.COMP.MULTI"} | {f"NS.COMP.CMD_{name}" for name, _ in CASES}
        assert expected <= names

    def test_every_channel_generated(self, config):
        names = set(config.telemetry[TARGET].keys())
        expected = {"TELEMETRY", "EVENT", "NS.COMP.LIMITED", "NS.COMP.FORMATTED"} | {
            f"NS.COMP.TLM{name}" for name, _ in CASES
        }
        assert expected <= names

    def test_annotation_newlines_removed(self, config):
        assert _cmd(config, "NO_ARGS").description == "Line one line two"


class TestCommands:
    @pytest.mark.parametrize("name", [name for name, _ in CASES])
    def test_command_bit_size(self, config, name):
        packet = _cmd(config, f"CMD_{name}")
        assert packet.defined_length_bits == CCSDS_CMD_HEADER_BITS + CASE_CMD_BITS[name]

    def test_fprime_header_command_bit_size(self, tmp_path):
        result = _run(tmp_path, extra_args=["FPRIME"])
        assert result.returncode == 0, result.stderr
        config = _load_config(tmp_path)
        for name, _ in CASES:
            packet = _cmd(config, f"CMD_{name}")
            assert packet.defined_length_bits == FPRIME_CMD_OVERHEAD_BITS + CASE_CMD_BITS[name], name

    def test_opcode_is_id(self, config):
        item = _cmd(config, "NO_ARGS").get_item("FPRIME_OPCODE")
        assert item.id_value == 0x100

    def test_scalar_params(self, config):
        assert _cmd(config, "CMD_U64").get_item("VAL").data_type == "UINT"
        assert _cmd(config, "CMD_I16").get_item("VAL").data_type == "INT"
        assert _cmd(config, "CMD_F64").get_item("VAL").data_type == "FLOAT"
        assert _cmd(config, "CMD_STR").get_item("VAL").data_type == "STRING"
        assert _cmd(config, "CMD_BOOL").get_item("VAL").states == {"FALSE": 0, "TRUE": 1}

    def test_enum_param_uses_default(self, config):
        item = _cmd(config, "CMD_ENUM").get_item("VAL")
        assert item.states == {"OFF": 0, "ON": 1}
        assert item.default == 1

    def test_signed_enum_param(self, config):
        item = _cmd(config, "CMD_SENUM").get_item("VAL")
        assert item.data_type == "INT"
        assert item.states == {"NEG": -1, "POS": 1}

    def test_alias_param_resolves(self, config):
        item = _cmd(config, "CMD_ALIAS").get_item("VAL")
        assert (item.bit_size, item.data_type) == (16, "UINT")
        assert _cmd(config, "CMD_ENUM_ALIAS").get_item("VAL").states == {"OFF": 0, "ON": 1}

    def test_struct_members_in_index_order(self, config):
        assert _param_names(_cmd(config, "CMD_STRUCT")) == ["VAL_X", "VAL_Y"]
        assert _cmd(config, "CMD_STRUCT").get_item("VAL_X").description == "X coord"

    @pytest.mark.parametrize(
        "name,bit_size,data_type,array_size",
        [
            ("U32_ARR", 32, "UINT", 96),
            ("I8_ARR", 8, "INT", 16),
            ("F64_ARR", 64, "FLOAT", 128),
            ("BOOL_ARR", 8, "UINT", 32),
            ("ALIAS_ARR", 16, "UINT", 32),
        ],
    )
    def test_primitive_array_param(self, config, name, bit_size, data_type, array_size):
        item = _cmd(config, f"CMD_{name}").get_item("VAL")
        assert (item.bit_size, item.data_type, item.array_size) == (bit_size, data_type, array_size)

    @pytest.mark.parametrize("name", ["ENUM_ARR", "ENUM_ALIAS_ARR"])
    def test_enum_array_param_expanded(self, config, name):
        packet = _cmd(config, f"CMD_{name}")
        assert _param_names(packet) == ["VAL_0", "VAL_1"]
        for item_name in ("VAL_0", "VAL_1"):
            item = packet.get_item(item_name)
            assert item.states == {"OFF": 0, "ON": 1}
            assert item.default == 1

    def test_struct_array_param_expanded(self, config):
        assert _param_names(_cmd(config, "CMD_STRUCT_ARR")) == ["VAL_0_X", "VAL_0_Y", "VAL_1_X", "VAL_1_Y"]

    def test_nested_array_param_expanded(self, config):
        packet = _cmd(config, "CMD_NESTED_ARR")
        assert _param_names(packet) == ["VAL_0", "VAL_1"]
        assert packet.get_item("VAL_0").array_size == 96

    def test_struct_with_array_param(self, config):
        packet = _cmd(config, "CMD_STRUCT_WITH_ARR")
        assert _param_names(packet) == ["VAL_MODE", "VAL_VALS"]
        assert packet.get_item("VAL_VALS").array_size == 96

    def test_tlm_packetizer_section_configs(self, config):
        packet = _cmd(config, "CMD_SECTION_CONFIGS")
        fields = ["ENABLED", "FORCEENABLED", "RATELOGIC", "MIN", "MAX"]
        assert _param_names(packet) == [f"VAL_0_{g}_{field}" for g in range(4) for field in fields]
        assert packet.get_item("VAL_0_3_RATELOGIC").default == 2
        assert packet.get_item("VAL_0_0_ENABLED").states == {"DISABLED": 0, "ENABLED": 1}

    def test_tlm_packetizer_section_enabled(self, config):
        item = _cmd(config, "CMD_SECTION_ENABLED").get_item("VAL_0")
        assert item.states == {"DISABLED": 0, "ENABLED": 1}

    def test_multiple_params_in_order(self, config):
        assert _param_names(_cmd(config, "MULTI")) == ["A", "B_0", "B_1", "C"]

    def test_command_round_trip(self, config):
        packet = _cmd(config, "CMD_SECTION_CONFIGS").clone()
        packet.restore_defaults()
        packet.write("VAL_0_2_MAX", 0xDEADBEEF)
        packet.write("VAL_0_2_RATELOGIC", "EVERY_MAX")
        assert packet.read("VAL_0_2_MAX") == 0xDEADBEEF
        assert packet.read("VAL_0_2_RATELOGIC") == "EVERY_MAX"
        assert packet.read("VAL_0_1_MAX") == 0


class TestTelemetry:
    """Channel items are named after the last segment of the channel name."""

    def test_channel_id(self, config):
        assert _tlm(config, "TLMU8").get_item("FPRIME_CHANNEL_ID").id_value == 0x300

    def test_string_channel_is_variable_length(self, config):
        packet = _tlm(config, "TLMSTR")
        assert packet.get_item("TLMSTR_LENGTH").bit_size == 32
        assert packet.get_item("TLMSTR").variable_bit_size is not None

    def test_enum_channel_states(self, config):
        assert _tlm(config, "TLMENUM").get_item("TLMENUM").states == {"OFF": 0, "ON": 1}

    def test_struct_channel_members_in_index_order(self, config):
        assert _param_names(_tlm(config, "TLMSTRUCT")) == ["TLMSTRUCT_X", "TLMSTRUCT_Y"]

    def test_primitive_array_channel(self, config):
        item = _tlm(config, "TLMU32_ARR").get_item("TLMU32_ARR")
        assert (item.bit_size, item.data_type, item.array_size) == (32, "UINT", 96)

    def test_enum_array_channel_expanded(self, config):
        packet = _tlm(config, "TLMENUM_ARR")
        assert _param_names(packet) == ["TLMENUM_ARR_0", "TLMENUM_ARR_1"]
        assert packet.get_item("TLMENUM_ARR_1").states == {"OFF": 0, "ON": 1}

    def test_struct_array_channel_expanded(self, config):
        prefix = "TLMSTRUCT_ARR"
        assert _param_names(_tlm(config, prefix)) == [f"{prefix}_0_X", f"{prefix}_0_Y", f"{prefix}_1_X", f"{prefix}_1_Y"]

    def test_nested_array_channel_expanded(self, config):
        packet = _tlm(config, "TLMNESTED_ARR")
        assert _param_names(packet) == ["TLMNESTED_ARR_0", "TLMNESTED_ARR_1"]
        assert packet.get_item("TLMNESTED_ARR_1").array_size == 96

    def test_tlm_packetizer_channels(self, config):
        fields = ["ENABLED", "FORCEENABLED", "RATELOGIC", "MIN", "MAX"]
        prefix = "TLMSECTION_CONFIGS"
        packet = _tlm(config, prefix)
        assert _param_names(packet) == [f"{prefix}_0_{g}_{field}" for g in range(4) for field in fields]
        assert _param_names(_tlm(config, "TLMSECTION_ENABLED")) == ["TLMSECTION_ENABLED_0"]

    def test_channel_decodes(self, config):
        packet = _tlm(config, "TLMSECTION_ENABLED").clone()
        packet.buffer = struct.pack(">IHBIIB", 0x300 + 23, 0, 0, 1, 2, 1)
        assert packet.read("TLMSECTION_ENABLED_0") == "ENABLED"

    def test_format_string(self, config):
        assert _tlm(config, "LIMITED").get_item("LIMITED").format_string == "%.2f"
        assert _tlm(config, "FORMATTED").get_item("FORMATTED").format_string == "%x"

    def test_limits(self, config):
        limits = _tlm(config, "LIMITED").get_item("LIMITED").limits
        assert limits.values["DEFAULT"] == [-20, -10, 10, 20]


@pytest.fixture(scope="module")
def module(generated):
    return _load_event_conversion(generated)


class TestEventConversion:
    def _call(self, module, event_id, data):
        values = {"FPRIME_EVENT_ID": event_id, "FPRIME_EVENT_DATA": data}
        packet = MagicMock()
        packet.read.side_effect = lambda name, _type, _buffer: values[name]
        return module.FprimeEventConversion().call(None, packet, b"")

    def test_events_table(self, module):
        assert set(module.EVENTS.keys()) == {0x600, 0x601, 0x602}
        assert module.EVENTS[0x601]["severity"] == "WARNING_LO"

    def test_no_args(self, module):
        assert self._call(module, 0x600, b"") == "Hello"

    def test_scalars(self, module):
        data = struct.pack(">HbfBI", 513, -3, 1.25, 1, 2) + b"hi"
        assert self._call(module, 0x601, data) == "a=513 b=-3 c=1.2 d=True e=hi"

    def test_enum_alias_array_and_struct(self, module):
        data = struct.pack(">BBBff", 1, 0, 1, 1.5, -2.0)
        result = self._call(module, 0x602, data)
        assert result == "mode=ON modes=['OFF', 'ON'] pt={'x': 1.5, 'y': -2.0}"

    def test_unknown_event(self, module):
        assert self._call(module, 0x999, b"") == "Unknown event id 2457"

    def test_short_data_reports_error(self, module):
        assert self._call(module, 0x601, b"\x00").startswith("Error formatting event Ns.comp.Scalars")
