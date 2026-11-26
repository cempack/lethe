#!/usr/bin/python3 -I
import os, sys
here = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, here if os.path.isdir(os.path.join(here, "lethe")) else "/usr/local/lib/lethe")
from lethe.cli import main
main()
