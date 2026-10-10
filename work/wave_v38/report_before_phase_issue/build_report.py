"""全固定条件の数表と、簡潔な独立判定報告を組み立てる。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 既存の表示関数だけを継承し、今回の説明と比較へ接続する。

    引数: なし。返り値: なし (None)。探索条件と経済判定は変更しない。
    """
    old=(HERE.parent/'wave_v37/report_partial.py').read_text(encoding='utf-8')
    money=old[old.index('def money_tables('):old.index('def main()')]
    money=money.replace('全427','全974').replace('主309・診断54・補助64','主206・補助768')
    destination=HERE/'report_adaptive.py'
    text=(HERE/'report_header.txt').read_text(encoding='utf-8')+money+(HERE/'report_body.txt').read_text(encoding='utf-8')
    destination.write_text(text,encoding='utf-8')
    print('974条件の表示生成器を作成。結果や採否は変更しない。')


if __name__=='__main__':main()
