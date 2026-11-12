#!/usr/bin/env python3
"""Repository-local wrapper for the reviewed R5 fastboot recovery entry."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
ENTRY = Path(__file__).resolve().with_name('r5_sd_recovery_impl.py')
if ENTRY.resolve() == Path(__file__).resolve():
    raise SystemExit('Recovery wrapper resolved to itself')
sys.path.insert(0, str(ENTRY.parent))
runpy.run_path(str(ENTRY), run_name='__main__')
