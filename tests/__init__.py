"""Test package: put the tree root on sys.path so the tests can
import the qwkhnd package however they are run."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
