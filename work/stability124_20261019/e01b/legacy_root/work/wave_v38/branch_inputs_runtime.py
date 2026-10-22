"""旧入力を読む間の検索パス変更を外へ残さず、監査済み関数をそのまま公開する。

すでに別版の注文器がsys.modulesへ登録された場合、その登録を置換しない。
呼出側はv38注文器を明示パスから読み、__file__を検査する。
"""

from __future__ import annotations

import sys

_before_path = list(sys.path)
try:
    import branch_inputs as _implementation
finally:
    sys.path[:] = _before_path

SIGNALS = _implementation.SIGNALS
CONDITIONS = _implementation.CONDITIONS
SCALES = _implementation.SCALES
initialize = _implementation.initialize
entry_artifact = _implementation.entry_artifact
entry = _implementation.entry
condition_artifact = _implementation.condition_artifact
condition = _implementation.condition
publication_valid = _implementation.publication_valid
source_bits = _implementation.source_bits
random_direction = _implementation.random_direction
directions = _implementation.directions
branch_choice = _implementation.branch_choice
