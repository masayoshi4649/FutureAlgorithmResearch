"""保存済み全840条件だけから事前固定の独立判定を再実行する。"""
import json
from pathlib import Path
import conditional_assessment as assessment
import conditional_design as design
import conditional_runner as runner


def main() -> None:
    """機能: 全条件と初期6選択を照合し、判定を独立判定.jsonへ保存する。

    引数: なし。返り値: なし (None)。新しい売買再生・選択変更は行わない。
    """
    here = Path(__file__).resolve().parent
    fixed = assessment.freeze()
    complete = runner.read(here / '主再生の完了.json')
    assert complete['全条件数'] == 840 and complete['全入力数'] == 21840
    selected = runner.read(here / '選択固定.json')
    selection_hash = runner.digest(here / '選択固定.json')
    assert complete['選択固定SHA256'] == selection_hash
    specs = design.catalog()
    paths = [here / folder / (s['id'] + '.json.gz') for s in specs for folder in ('sessions', 'waves')]
    paths += [here / '全条件の期間集計.json.gz', here / '選択固定.json']
    hashes = {p: runner.digest(p) for p in paths}
    summaries = runner.read(here / '全条件の期間集計.json.gz')
    details = {s['id']: runner.read(here / 'sessions' / (s['id'] + '.json.gz')) for s in specs}
    waves = {s['id']: runner.read(here / 'waves' / (s['id'] + '.json.gz')) for s in specs}
    result = assessment.assess(summaries, details, waves, selected['選択'])
    assert hashes == {p: runner.digest(p) for p in paths} and assessment.freeze() == fixed
    result['独立判定固定SHA256'] = runner.digest(here / 'conditional_assessment_fixed.json')
    runner.save(here / '独立判定.json', result)
    output = {'選択': result['選択']['selected_exit_mode_id'], '主条件採用目安ID': result['主条件採用目安ID'],
        '基礎確認': result['H019運用policy']['候補基礎確認'],
        '固定A0比較': result['H019運用policy']['固定A0比較'],
        'MIN比較': result['H019運用policy']['初期A0後半MIN比較'],
        '選択固定条件の波': result['H019運用policy']['選択した固定条件の波']}
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
