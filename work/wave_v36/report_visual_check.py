"""比較と全損益の暗色HTMLを、独立したブラウザ領域で描画する。"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v35'))
import html_visual_check as previous


def main() -> None:
    """機能: 汎用描画確認の出力先を今回の作業へ限定して実行する。

    引数: コマンドラインのHTML名 (list[str])。返り値: なし (None)。
    """
    previous.HERE = HERE
    previous.REPORT = HERE.parents[1] / 'アルゴリズム調査/00031_出来高通過と気配維持からの方向判定'
    previous.main()


if __name__ == '__main__':
    main()
