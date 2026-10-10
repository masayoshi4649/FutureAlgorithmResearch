"""波監査の旧原版を保持し、保存注文の管理方向2列だけ独立計算へ追加する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 改訂元と改訂先の指紋を返す。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 旧固定を上書きせず限定改訂と失敗記録を保存する。

    引数: なし。返り値: なし (None)。売買・入力・許容値・対象を変更しない。
    """
    source = HERE/'partial_wave_audit.py'
    old = source.read_bytes(); text = old.decode('utf-8')
    old_hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in (
        source, HERE/'partial_wave_fixed.json', HERE/'partial_wave_selftest.json')}
    before = '理由=names.get(int(o[6]), \'その他\'), 発注元信号=int(state[source]), 約定時信号=int(state[filled])))'
    after = '理由=names.get(int(o[6]), \'その他\'), 発注元信号=int(state[source]), 約定時信号=int(state[filled]),\n            発注元管理方向=int(state[source]), 約定時管理方向=int(state[filled])))'
    assert text.count(before) == 1; text = text.replace(before, after)
    text = text.replace('partial_wave_fixed.json', 'partial_wave_fixed_v2.json')
    text = text.replace('partial_wave_selftest.json', 'partial_wave_selftest_v2.json')
    before = "for kind in ('金額', '枚数分', '欠落', '重複約定', 'NaN'):"
    assert text.count(before) == 1
    text = text.replace(before, "for kind in ('金額', '枚数分', '欠落', '重複約定', 'NaN', '発注元管理方向欠落', '約定時管理方向改変'):")
    before = "        if kind == 'NaN': corrupted['時価損益差円'] = float('nan')"
    assert text.count(before) == 1
    text = text.replace(before, before + "\n        if kind == '発注元管理方向欠落': del corrupted['区間内新規'][0]['発注元管理方向']\n        if kind == '約定時管理方向改変': corrupted['区間内新規'][0]['約定時管理方向'] *= -1")
    text = text.replace('人工6検査・破損5拒否', '人工6検査・破損7拒否')
    text = text.replace('value = dict(全合格=True, 合成検査合格=True,', 'value = dict(監査版=2, 全合格=True, 合成検査合格=True,')
    text = text.replace("result = dict(id=spec['id'], 全合格=True,", "result = dict(id=spec['id'], 監査版=2, 全合格=True,")
    text = text.replace('value = dict(全合格=True, 条件数=len(specs),', 'value = dict(監査版=2, 全合格=True, 条件数=len(specs),')
    before = "    material = read(HERE/'partial_input_fixed.json')"
    assert text.count(before) == 1
    text = text.replace(before, "    paths.update(HERE/name for name in ('partial_wave_audit.py', 'partial_wave_fixed.json', 'partial_wave_selftest.json',\n        'partial_wave_failure_v1.json', 'partial_wave_revision_plan.json', 'build_wave_audit_v2.py'))\n" + before)
    target = HERE/'partial_wave_audit_v2.py'
    assert not target.exists(), '限定改訂版を上書きしない'
    target.write_text(text, encoding='utf-8')
    assert source.read_bytes() == old
    failure = dict(監査版=1, session_id=18818, exit_code=1,
        停止位置='H019__A0__V000/W01/TOPIX/区間内新規/0',
        種別='辞書キー集合の完全一致違反',
        独立側欠落=['発注元管理方向', '約定時管理方向'],
        原因='旧v30 order_recordsのcontext省略時保存項目を独立監査へ転記し損ねた。',
        数値比較基準緩和=False, 原版SHA256=old_hashes)
    (HERE/'partial_wave_failure_v1.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding='utf-8')
    plan = dict(改訂理由=failure['原因'], 旧監査SHA256=old_hashes,
        新監査実装SHA256=digest(target), 生成器SHA256=digest(Path(__file__)),
        失敗記録SHA256=digest(HERE/'partial_wave_failure_v1.json'),
        追加計算='発注元管理方向=state[source_row]、約定時管理方向=state[fill_row]。context省略の旧保存仕様を独立に再計算。',
        売買変更=False, 入力変更=False, 成績変更=False, 採否変更=False, 許容値変更=False, 対象変更=False,
        全主363と補助64をv2で再監査=True, v1v2混在=False,
        検査='旧6人工境界検査を維持し、2列の欠落/改変拒否を加える。全3,416波・6,832境界の全保存項目照合を維持。')
    (HERE/'partial_wave_revision_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print('原版を保持し、管理方向2列の独立再計算をv2へ追加。売買・許容・対象は不変。')


if __name__ == '__main__':
    main()
