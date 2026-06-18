#!/usr/bin/env python3
"""Compatibility shim.

Builder modules import state_dataset_common; the shared implementation lives in
state.py in this workspace.
"""

from state import *  # noqa: F401,F403
