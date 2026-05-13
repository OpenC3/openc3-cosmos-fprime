import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

os.environ["OPENC3_NO_STORE"] = "1"