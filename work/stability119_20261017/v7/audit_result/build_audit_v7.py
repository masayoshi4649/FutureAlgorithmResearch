"""既監査のv5会計源を保全し、v7の保存名称と二つの予定額だけ適合させる。"""

import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def main() -> None:
    """
    機能: 同じ注文・親会計を新出口の保存接口へ最小変換する。
    引数: なし。原市場・保存金融結果は読まない。
    返り値: None。新規sourceだけを所有領域に作る。
    """
    source = BASE / 'v5/audit_result/audit_result_v5.py'
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == '59c761775c765d4695e2f08a8659678134bb2ed1b1243760c69a820542a6a322'
    text = payload.decode('utf-8')
    replacements = [
        ('119v5', '119v7'), ('V5', 'V7'),
        ("'entry_delta', 'expected_center_gross'", "'entry_delta', 'cash_loss_budget'"),
        ("'hedge_error', 'expected_center_gross'", "'hedge_error', 'qualification_move_gross'"),
        ('saved: dict, close_time: float) -> dict:', 'saved: dict, close_time: float, exit_mode: int = 0) -> dict:'),
        ("[m[2], m[3], m[4], m[5], m[9], m[10], m[6], m[7]]", "[m[2], m[3], m[4], m[5], m[9] if exit_mode == 0 else m[9] / 2., m[10], m[6], m[7]]"),
        ('goal = abs(delta) * parent[12] * 10. * ref_last[0]', 'goal = (abs(delta) if exit_mode == 0 else 2. * parent[8]) * parent[12] * 10. * ref_last[0]'),
        ('[delta, goal, estimated, error]', '[delta, goal if exit_mode == 0 else goal / 2., estimated, error]'),
        ('independent_pair(arrays, quotes, saved, close_time)', "independent_pair(arrays, quotes, saved, close_time, spec['exit_mode'])"),
        ('二脚相対回帰四条件と全四十場.json', '相対的な強さの継続と残差追尾の全四十場.json'),
        ("len(result['specs']) == 4", "len(result['specs']) == 8"),
        ('160', '320'), ('4条件', '8条件'), ('四条件', '八条件'), ('四条件会計一致', '八条件会計一致'),
        ('二脚全百六十組', '二脚全三百二十組')]
    for before, after in replacements:
        if before == '四条件会計一致' and before not in text:
            continue
        assert before in text, before
        text = text.replace(before, after)
    target = HERE / 'audit_result_v7.py'
    assert not target.exists()
    target.write_text(text, encoding='utf-8')
    pure = (BASE / 'v5/audit_result/pure_accounting_v5.py').read_text(encoding='utf-8')
    pure = pure.replace('V5', 'V7').replace('engine_v5', 'engine_v7').replace('audit_result_v5', 'audit_result_v7')
    pure = pure.replace(".0002 *", ".002 *")
    pure = pure.replace("entry_end=1900., close_time=2000.)", "entry_end=1900., close_time=2000., exit_mode=0)")
    pure = pure.replace("subject.independent_pair(answer, (nq, tq), saved, 2000.)", "subject.independent_pair(answer, (nq, tq), saved, 2000., 0)\n        answer_one = engine.run_pair(nk, top, nq, tq, dict(method='ratio_mr', lookback=30, entry_end=1900., close_time=2000., exit_mode=1))\n        subject.independent_pair(answer_one, (nq, tq), dict(answer_one['summary'], legs=answer_one['leg_summary']), 2000., 1)")
    pure = pure.replace("'保存会計監査源の公開API人工接続_v2.json'", "'二退出保存会計監査源の公開API人工接続.json'")
    target_pure = HERE / 'pure_accounting_v7.py'
    assert not target_pure.exists()
    target_pure.write_text(pure, encoding='utf-8')


if __name__ == '__main__':
    main()
