import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pytest_configure():
    # for path in ROOT.iterdir():
    #     print(path.name)

    # sys.path.insert(0, str(ROOT))
    print(sys.path)

    print("hello")


pytest_configure()
