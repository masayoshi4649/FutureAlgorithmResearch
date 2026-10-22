"""初回登録の形式不備を保存し、経済実装不変のまま正しい目録形式へ接続する。"""

import difflib
import plan119 as plan


def main() -> None:
    """
    機能: 登録前validateでの停止を保全し、入力目録・実装指紋の形式だけを修正する。
    引数: なし。保全済み初版と現源を比較する。
    返り値: None。経済六源・市場・金融結果を変更しない。
    """
    archive = plan.HERE / 'registration_archive/v1'
    old = plan.read(archive / '正式固定.json')['source_SHA256']
    current = plan.sources()
    changed = [key for key in current if current[key] != old[key]]
    assert changed == ['work/stability119_20261017/plan119.py']
    failed = plan.read(archive / '正式登録の全出力.json')
    assert failed['終了コード'] == 1 and "KeyError: 'input_manifests'" in failed['stderr']
    assert not (plan.HERE / 'measurement').exists()
    difference = ''.join(difflib.unified_diff((archive / 'plan119.py').read_text(encoding='utf-8').splitlines(True),
        (plan.HERE / 'plan119.py').read_text(encoding='utf-8').splitlines(True)))
    for name in ('正式固定.json', '試行計画.json', '正式照合の全出力.json', '正式登録の全出力.json', '実測前の人工検査.json'):
        path = plan.HERE / name
        assert path.read_bytes() == (archive / name).read_bytes()
        path.unlink()
    plan.write(plan.HERE / '登録形式だけの修正証跡.json', dict(全合格=True,
        初回停止='台帳validateがdata.input_manifestsとimplementationのpath→SHAを要求。書込前に停止。',
        差分=difference, 他経済六源不変=True, 初回登録に金融なし=True, source_SHA256=current,
        原市場=0, 新金融=0, API=0))
    print('初回登録不備を保全。変更は目録形式だけ、経済源と市場未読状態は不変。')


if __name__ == '__main__':
    main()
