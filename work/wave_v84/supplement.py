"""前半の少数取引でのみ両銘柄黒字だった条件を、主選定と分離して点検する。"""
from pathlib import Path
import research

HERE = Path(__file__).resolve().parent


def main():
    """
    機能: 前半で両銘柄黒字・取引不足だった全条件を追加固定して再生する。
    引数: なし。
    返り値: None。主選定・事前固定・既存の14代表は変更しない。
    """
    fixed = research.read(research.FIXED)
    research.validate_fixed(fixed)
    selected = research.read(HERE / '前半選定.json')
    candidates = []
    for config in fixed['catalog']:
        result = research.read(HERE / 'train/results' / (config['id'] + '.json'))
        metrics = result['periods']['対象']
        if all(m['net'] > 0 for m in metrics.values()) and config['id'] not in selected['selected']:
            assert any(m['cycles'] < 20 or m['active_sessions'] < 8 for m in metrics.values())
            candidates.append(config)
    record = dict(
        条件=candidates,
        位置づけ='主代表の実結果を見た後に追加した探索的参考。候補IDの選定は前16だけから行う。主代表は差し替えない。',
        選び方='前16で両銘柄の手数料後収支が黒字だが、20取引又は8取引場の最低数で主選定から落ちた条件を全件採用。後14の損益を読む前に追加固定。',
        採用を証明しない理由='少数取引の参考であり、主結果や未知データによる検証として扱わない。',
        code_SHA256=dict(fixed['code_SHA256'], supplement=research.data.digest(Path(__file__))),
        主選定SHA256=research.data.digest(HERE / '前半選定.json'))
    target = HERE / 'supplement/追加固定.json'
    if target.exists():
        assert research.read(target) == record
    else:
        research.save_json(target, record)
    inputs = research.data.load_data(verify=True)
    research.batch(candidates, inputs, fixed['全30'], fixed, HERE / 'supplement/final', 2)
    research.batch(candidates, inputs, fixed['全30'], fixed, HERE / 'supplement/ideal_fee', 2, 'ideal_fee')


if __name__ == '__main__':
    main()
