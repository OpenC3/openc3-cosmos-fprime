# Copyright 2026 OpenC3, Inc.
# All Rights Reserved.
#
# This file is licensed under the MIT license.
# See LICENSE.md file in the project root for details.

"""Generate the deterministic sample files served by the F Prime test container.

targets/FPRIME/procedures/cfdp_test.py regenerates the same bytes to verify
transfers, so keep the two copies of these functions identical.

Usage: python make_files.py <output_dir>
"""

import os
import sys


def small():
    return b"Hello from OpenC3 COSMOS CFDP\n"


def medium():
    return bytes(i % 251 for i in range(100_000))


def odd():
    return bytes((i * 7) % 256 for i in range(5_003))


FILES = {"small.txt": small, "medium.bin": medium, "odd.bin": odd}

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(1)
    for name, content in FILES.items():
        with open(os.path.join(sys.argv[1], name), "wb") as f:
            f.write(content())
