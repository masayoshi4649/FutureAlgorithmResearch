"""今回の暗色HTMLを専用ブラウザ領域で描画する。"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'wave_v35'))
import html_visual_check as previous


def main() -> None:
    """機能: 汎用描画確認の出力先を今回へ限定する。

    引数: HTML名 (コマンドラインlist[str])。返り値: なし (None)。
    """
    previous.HERE = HERE
    previous.REPORT = HERE.parents[1]/'アルゴリズム調査/00032_悪化時の部分減量と回復後の数量復元'
    previous.main()


if __name__ == '__main__':
    main()
