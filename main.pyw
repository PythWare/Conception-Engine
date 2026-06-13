from __future__ import annotations

import os, sys
from pathlib import Path


def main():
    app_root = Path(__file__).resolve().parent
    os.chdir(app_root)
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    from Logic.gui import run_app

    run_app(app_root)


if __name__ == "__main__":
    main()
