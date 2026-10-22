"""提案の五ポイント追尾と三ポイント段間隔を部品別に固定する。"""

from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'stability120_20261017'))
from catalog120 import settings


def specifications() -> list[dict]:
    """
    機能: 既存対照と新たな三条件を数値閲覧前に定義する。
    引数: なし。
    返り値: list[dict]は新三条件の固定幅と再準備方式。
    """
    return [
        dict(id='G1_T5_SLOT',name='利確幅だけ5pt',spacing=1.,trail=5.,reset_after_profit=False),
        dict(id='G3_T5_SLOT',name='3pt間隔・段数を維持',spacing=3.,trail=5.,reset_after_profit=False),
        dict(id='G3_T5_RESET',name='提案：3pt間隔・利確後3ptから',spacing=3.,trail=5.,reset_after_profit=True),
    ]
