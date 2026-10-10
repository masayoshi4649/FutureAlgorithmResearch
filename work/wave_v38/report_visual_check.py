"""今回の暗色HTMLを専用ブラウザ領域で描画する。"""

from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'wave_v35'))
import html_visual_check as previous


def main() -> None:
    """機能: 汎用描画確認の対象を今回の成果へ限定する。

    引数: HTML名 (コマンドラインlist[str])。返り値: なし (None)。
    """
    previous.HERE=HERE
    previous.REPORT=HERE.parents[1]/'アルゴリズム調査/00033_復元方式の自動選択と改善8条件の反証'
    previous.main()


if __name__=='__main__':main()
