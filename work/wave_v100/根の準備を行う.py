"""価格上限の比較へ根の不変会計と保存検査を接続する。"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v99'


def main() -> None:
    """
    機能: 所有している根コードだけを新作業へ複写し、価格上限診断を保存へ接続する。
    引数: なし。
    返り値: None。旧作業及び他担当の実装は変更しない。
    """
    names = ('data.py', 'accounting.py', 'research.py', 'analysis/assemble.py',
             'analysis/入口価格と取り逃しを分ける.py', '根台帳の保存往復を確かめる.py',
             'root_preflight/selection.py', 'root_preflight/selection_small.py',
             'root_preflight/real_prefixes.py')
    for name in names:
        path = HERE / name
        assert not path.exists(), name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (OLD / name).read_text(encoding='utf-8')
        text = text.replace('正式99', '正式100').replace('不変保存入力98の読取99', '不変保存入力98の読取100')
        if name == 'research.py':
            text = text.replace('現在支持二源・四時計政策・二入口・二既定出口', '四価格上限・二支持源・二入口・二既定出口')
            text = text.replace("prior_path = HERE.parent / 'wave_v98/事前固定.json'", "prior_path = HERE.parent / 'wave_v99/事前固定.json'")
            text = text.replace("'全34人工と支持源政策', '旧十八対照全1116とnull経済'", "'全34人工と価格上限政策', '旧十対照全620とnull経済'")
            text = text.replace("for relative, expected in plan['設計根拠SHA256'].items():", "for relative, expected in read(HERE / '結果前の設計根拠.json')['設計根拠SHA256'].items():")
            marker = "    # ----------------------------------------\n    if prepared is not None:\n        answer['wait_input_SHA256']"
            block = "    # ----------------------------------------\n    # 価格上限の判断状態と実約定の上限超過を分けて保存する。\n    cap = output['entry_cap_state_trace']\n    answer.update(entry_cap_state_changes=changes(cap),\n                  entry_cap_state_columns=output['entry_cap_state_columns'],\n                  entry_cap_state_SHA256=hashlib.sha256(cap.tobytes()).hexdigest(),\n                  entry_cap_parent_diagnostics=output['entry_cap_parent_diagnostics'],\n                  entry_cap_parent_columns=output['entry_cap_parent_columns'])\n"
            assert marker in text
            text = text.replace(marker, block + marker)
            text = text.replace("HERE / 'セッション安定性の事前評価.json']", "HERE / 'セッション安定性の事前評価.json', HERE / '結果前の設計根拠.json']")
        elif name == 'analysis/assemble.py':
            text = text.replace('二支持源・四時計政策・二入口・二出口', '四判断価格上限・二支持源・二入口・二出口')
        elif name == '根台帳の保存往復を確かめる.py':
            text = text.replace('99明示人工LP素材の読取', '100明示人工LP素材の読取')
            text = text.replace("('watch_state', 'trend_exit_state', 'entry_policy_state')", "('watch_state', 'trend_exit_state', 'entry_policy_state', 'entry_cap_state')")
            text = text.replace("'trend_parent_diagnostics', 'entry_policy_events')", "'trend_parent_diagnostics', 'entry_policy_events', 'entry_cap_parent_diagnostics')")
            text = text.replace("assert saved['entry_policy_state_columns']", "assert saved['entry_cap_state_columns'] == output['entry_cap_state_columns']\n            assert saved['entry_cap_parent_columns'] == output['entry_cap_parent_columns']\n            assert saved['entry_policy_state_columns']")
            # 元候補時の有利な価格と押し回復の差を、半W以内にする。
            text = text.replace("event[95] = 1", "event[99] = 1")
            text = text.replace('全34人工の根台帳と支持源及び待機出口診断の保存往復', '全34人工の根台帳と価格上限及び支持源待機出口診断の保存往復')
        elif name == 'root_preflight/real_prefixes.py':
            text = text.replace("'entry_policy_state_trace')", "'entry_policy_state_trace', 'entry_cap_state_trace')")
            text = text.replace("('A0_X3', 'L0_C1_A7_X3', 'L1_C1_A7_X3', 'L1_C2_A7_X3', 'L1_C3_A7_X3', 'L1_C1_A1_X1')", "('A0_X3', 'P0_L1_C1_A1_X1', 'P05_L1_C1_A7_X3', 'P1_L1_C1_A1_X1', 'P2_L0_C1_A7_X3', 'P1_L1_C1_A7_X3')")
            text = text.replace("    assert counts['gap休止を含む接頭'] > 0\n", '')
            text = text.replace('六代表の実接頭と支持源及び自己相手未来の不変', '六代表の実接頭と価格上限支持源及び自己相手未来の不変')
        path.write_text(text, encoding='utf-8')
    # ----------------------------------------
    stable = json.loads((OLD / 'セッション安定性の事前評価.json').read_text(encoding='utf-8'))
    stable.update(固定時点='100の34条件の正式新損益前。',
                  主の扱い='P1_L1_C1_A1_X1の事前主を、前16参考又は全31の事後診断へ差し替えない。',
                  入口の追加評価='元候補から判断価格までの不利幅、拒否後の経路と実約定超過を別に記録。同候補建値差・旧勝負の消失・新固有親・活動減少を分ける。')
    path = HERE / 'セッション安定性の事前評価.json'
    assert not path.exists()
    path.write_text(json.dumps(stable, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('根の会計・保存・評価を100へ接続しました。新正式損益は未実行です。', flush=True)


if __name__ == '__main__':
    main()
