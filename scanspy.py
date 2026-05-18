from multiprocessing import freeze_support
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from scanspy.cli import main  # noqa: E402


if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
