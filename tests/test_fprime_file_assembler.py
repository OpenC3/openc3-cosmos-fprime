# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Tests for F Prime file packet parsing and reassembly."""

import pytest

import fprime_fixtures as fx
from fprime_file_assembler import (
    T_CANCEL,
    T_DATA,
    T_END,
    T_START,
    FileAssembler,
    cfdp_checksum,
    parse_file_packet,
    safe_file_name,
)

CONTENT = b"hello data products!"


def feed_all(assembler, raws):
    result = None
    for raw in raws:
        out = assembler.feed(parse_file_packet(raw))
        if out is not None:
            result = out
    return result


class TestParse:
    def test_start(self):
        p = parse_file_packet(fx.file_start(0, 1234, "/a/src.bin", "/b/Dp_1.fdp"))
        assert (p.type, p.sequence_index, p.file_size) == (T_START, 0, 1234)
        assert (p.source_path, p.dest_path) == ("/a/src.bin", "/b/Dp_1.fdp")

    def test_data(self):
        p = parse_file_packet(fx.file_data(3, 40, b"abc"))
        assert (p.type, p.sequence_index, p.byte_offset, p.data) == (T_DATA, 3, 40, b"abc")

    def test_end(self):
        p = parse_file_packet(fx.file_end(9, 0xDEADBEEF))
        assert (p.type, p.checksum) == (T_END, 0xDEADBEEF)

    def test_cancel(self):
        assert parse_file_packet(fx.file_cancel(4)).type == T_CANCEL

    @pytest.mark.parametrize(
        "raw",
        [b"", b"\x00\x00", fx.file_start(0, 10)[:-3], fx.file_data(1, 0, b"abcdef")[:-2], b"\x07\x00\x00\x00\x01"],
    )
    def test_truncated_or_unknown_raises(self, raw):
        with pytest.raises(ValueError):
            parse_file_packet(raw)


class TestChecksum:
    def test_partial_word_is_zero_padded(self):
        assert cfdp_checksum(b"\x01\x02\x03\x04\x05") == 0x01020304 + 0x05000000

    def test_wraps_at_32_bits(self):
        assert cfdp_checksum(b"\xff\xff\xff\xff\x00\x00\x00\x02") == 1

    def test_empty(self):
        assert cfdp_checksum(b"") == 0


class TestSafeFileName:
    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/a/b/Dp_1.fdp", "Dp_1.fdp"),
            ("../../etc/passwd", "passwd"),
            ("C:\\x\\y.bin", "y.bin"),
            ("plain.txt", "plain.txt"),
            ("", "unnamed"),
            ("..", "unnamed"),
            ("/dir/", "unnamed"),
        ],
    )
    def test_names(self, path, expected):
        assert safe_file_name(path) == expected


class TestAssembler:
    def test_in_order(self):
        done = feed_all(FileAssembler(), fx.file_transfer("/dst/x.bin", CONTENT))
        assert done.data == CONTENT
        assert done.complete and done.checksum_ok
        assert done.dest_path == "/dst/x.bin"

    def test_out_of_order_data(self):
        raws = fx.file_transfer("/dst/x.bin", CONTENT)
        raws = [raws[0], *reversed(raws[1:-1]), raws[-1]]
        done = feed_all(FileAssembler(), raws)
        assert done.data == CONTENT and done.complete

    def test_missing_chunk_is_incomplete(self):
        raws = fx.file_transfer("/dst/x.bin", CONTENT)
        del raws[2]
        done = feed_all(FileAssembler(), raws)
        assert not done.complete

    def test_bad_checksum_flagged(self):
        done = feed_all(FileAssembler(), fx.file_transfer("/dst/x.bin", CONTENT, checksum=1))
        assert done.complete and not done.checksum_ok

    def test_empty_file(self):
        done = feed_all(FileAssembler(), fx.file_transfer("/dst/empty", b""))
        assert done.data == b"" and done.complete and done.checksum_ok

    def test_cancel_discards(self):
        raws = fx.file_transfer("/dst/x.bin", CONTENT)
        raws.insert(-1, fx.file_cancel(99))
        assert feed_all(FileAssembler(), raws) is None

    def test_packets_without_start_ignored(self):
        raws = fx.file_transfer("/dst/x.bin", CONTENT)[1:]
        assert feed_all(FileAssembler(), raws) is None

    def test_new_start_abandons_previous(self):
        first = fx.file_transfer("/dst/one", CONTENT)[:-1]
        second = fx.file_transfer("/dst/two", b"second")
        done = feed_all(FileAssembler(), first + second)
        assert done.dest_path == "/dst/two" and done.data == b"second" and done.complete

    def test_data_past_end_ignored(self):
        raws = fx.file_transfer("/dst/x.bin", CONTENT)
        raws.insert(1, fx.file_data(50, len(CONTENT), b"overflow"))
        done = feed_all(FileAssembler(), raws)
        assert done.data == CONTENT and done.complete

    def test_oversize_start_rejected(self):
        assembler = FileAssembler(max_file_size=10)
        with pytest.raises(ValueError, match="max_file_size"):
            assembler.feed(parse_file_packet(fx.file_start(0, 11)))
        assert assembler.feed(parse_file_packet(fx.file_end(1, 0))) is None
