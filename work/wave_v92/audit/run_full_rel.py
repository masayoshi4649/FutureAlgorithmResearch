"""凍結済み全口座検算へ、実装済み中心解除取消の独立検査だけを補足接続する。"""

from pathlib import Path

import common
import full
import protocol_rel


def main():
    """
    機能: 元の全会計・状態・最初返済検算を保ち、旧監査の取消許可漏れを別監査で補う。
    引数: なし。
    返り値: None。売買コード・注文・結果・凍結ファイルは変更しない。
    """
    fixed = full.read(common.WORK/'事前固定.json')
    for relative,digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT/relative)==digest,relative
    full.protocol = protocol_rel
    full.main()
    target = common.HERE/'全36条件全31場の回復と中心帰還及び全原板清算会計の独立検算.json'
    proof = full.read(target)
    proof['独立監査の補足'] = dict(
        理由='非持続の中心保持解除は正式center_release契約であり、旧cancel_pending又はpersistent_armだけに限る監査条件では不足。',
        条件='center_release=Trueで実際のcode26中心解除がある同じ行の取消を認める。独立25列状態の解除復元と先約定・次気配取消の順序を保つ。',
        売買実装変更=0,凍結済みコード変更=0,既存結果変更=0,
        元監査SHA256=common.sha(common.HERE/'protocol.py'))
    proof['SHA256'].update(common.fingerprint([Path(__file__),Path(protocol_rel.__file__)]))
    common.save(target.name,proof)


if __name__=='__main__':
    main()
