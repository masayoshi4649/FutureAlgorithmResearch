"""会計の旧版同一要求だけを、限定補正済み候補との同一要求へ変える。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 旧人工試験を残し、境界改訂後の同じ824試験を準備する。

    引数: なし。返り値: なし (None)。人工経路・接続・数値検算は不変。
    """
    original=HERE/'adaptive_runner_synthetic.py'
    assert original.read_bytes()==(HERE/'cash_revision_v1'/original.name).read_bytes()
    text=original.read_text(encoding='utf-8')
    old="assert (runner.HERE/'adaptive_cash_reconstruction.py').read_bytes()==(runner.HERE.parent/'wave_v37/partial_cash_reconstruction.py').read_bytes()"
    new="assert (runner.HERE/'adaptive_cash_reconstruction.py').read_bytes()==(runner.HERE/'adaptive_cash_reconstruction_v2_candidate.py').read_bytes()"
    assert text.count(old)==1
    result=text.replace(old,new)
    assert result.replace(new,old)==text
    (HERE/'adaptive_runner_synthetic_v2.py').write_text(result,encoding='utf-8')
    print('旧会計同一assertのみ置換。同じ人工824試験を保持。')


if __name__=='__main__':main()
