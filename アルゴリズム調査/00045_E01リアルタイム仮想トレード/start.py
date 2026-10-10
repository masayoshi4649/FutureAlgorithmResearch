#!/usr/bin/env python3
"""Windows・Linux共通でE01の仮想トレードを開始する。実注文は行わない。"""

from __future__ import annotations

import sys
import traceback


def main(argv: list[str] | None = None) -> int:
    """機能: 起動引数を仮想売買へ渡し、異常時は原因と終了コードを残す。

    引数: argv(list[str]|None)。Noneならコマンドライン引数を使用する。
    返り値: 仮想売買の終了コード(int)。例外が起きた場合は1。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8', errors='backslashreplace')

    # ----------------------------------------
    # 作業ディレクトリを変えず、相対保存先は呼出元を基準にする。
    try:
        from papertrade.runtime import main as run

        code = run(argv)
    except Exception as error:
        print('仮想トレードを停止しました: ' + str(error), file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    if code:
        print(f'仮想トレードが終了コード {code} で停止しました。稼働記録.csvを確認してください。',
              file=sys.stderr, flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
