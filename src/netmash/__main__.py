"""
Executable package entrypoint: python -m netmash
"""

import sys
from netmash.cli import main

if __name__ == "__main__":
    sys.exit(main())
