import subprocess
import sys


def main():
    if sys.platform in ["win32", "cygwin"]:
        return 0
    else:
        cmd = ("scripts/sensitive_info_check/ip.sh", *sys.argv[1:])
    return subprocess.call(cmd)

if __name__ == "__main__":
    exit(main())
