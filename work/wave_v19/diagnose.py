"""選択後の主候補について、保有時間と近い入口・出口幅を追加診断する。"""

from __future__ import annotations

import itertools
import json
import pickle
import time

import research as study


def main() -> None:
    """機能: 主候補選択を変更せず、周辺135設定の収支と大勝ち依存を確認する。

    引数: なし。返り値: なし (None)。結果依存の追加診断であり未使用評価ではない。
    """
    started = time.time()
    selected = json.loads((study.OUT / '選択結果.json').read_text(encoding='utf-8'))
    records = json.loads((study.OUT / '週比較.json').read_text(encoding='utf-8'))
    primary = next(row for row in records if row['id'] == selected['primary'])
    assert primary['id'] == 'V0800' and primary['changes'] == {'timeout_min': 360.}
    grid = list(itertools.product([.20, .25, .30], [.9, 1., 1.1], [1.75, 2., 2.25], [300., 330., 360., 390., 420.]))
    study.save('追加診断前の固定記録.json', dict(主候補=primary['id'], 条件数=len(grid),
        目的='粗い探索の上端360分が孤立した良点でないか、保有時間と入口・出口の近い数値を確認する。',
        事後性='904条件の結果を見て範囲を決めた診断。主候補と元の順位は変更しない。',
        保有分=[300,330,360,390,420], 入口ATR=[.20,.25,.30], 損切りATR=[.9,1.,1.1], 追跡ATR=[1.75,2.,2.25],
        評価='両銘柄の週黒字率、最大勝ちセッション除外後の両銘柄黒字率、全資格合格率。近傍の成績を見て新しい最良値へ置換しない。'))
    inputs = {}
    for stage in ['development', 'holdout']:
        inputs.update(pickle.loads((study.OUT.parent / 'wave_v16' / f'入力_{stage}.pkl').read_bytes()))
    original = pickle.loads((study.OUT.parent / 'wave_v17/主方向状態.pkl').read_bytes())
    spec = study.signal_variants.variant_specs()[0]
    directions = study.signal_variants.build_one(spec, inputs, original)
    output, cells = [], []
    for index, (entry, stop, trail, hold) in enumerate(grid):
        candidate = dict(id=f'D{index:03d}', signal_id='S00', family='選択後の近傍診断',
                         config=dict(primary['config'], entry_atr=entry, stop_atr=stop, main_trail=trail, timeout_min=hold))
        weeks = {}
        for symbol in study.SYMBOLS:
            rows, trades = [], []
            for session in study.SESSIONS:
                key = (session, symbol)
                result = study.engine.run(inputs[key], directions[key], candidate['config'])
                row = study.metrics.summarize(result, candidate, symbol, session)
                rows.append(row)
                cells.append(row)
                trades.append(result['trades'])
            weeks[symbol] = study.aggregate(rows, trades)
        output.append(dict(candidate, weeks=weeks,
                           both_positive=all(weeks[s]['net_yen']>0 for s in study.SYMBOLS),
                           both_drop_positive=all(weeks[s]['drop_best_session_net']>0 for s in study.SYMBOLS),
                           both_eligible=all(study.qualify(weeks[s]) for s in study.SYMBOLS)))
    study.save('追加近傍診断.json', output)
    study.save('追加近傍セッション.json', cells)
    summary = dict(primary=primary['id'], count=len(output),
                   both_positive=sum(r['both_positive'] for r in output),
                   both_drop_positive=sum(r['both_drop_positive'] for r in output),
                   both_eligible=sum(r['both_eligible'] for r in output),
                   elapsed_seconds=time.time()-started,
                   holding_only=[r['id'] for r in output if r['config']['entry_atr']==.25 and r['config']['stop_atr']==1. and r['config']['main_trail']==2.],
                   minimum_net={s:min(r['weeks'][s]['net_yen'] for r in output) for s in study.SYMBOLS},
                   minimum_drop_net={s:min(r['weeks'][s]['drop_best_session_net'] for r in output) for s in study.SYMBOLS})
    study.save('追加近傍診断の要約.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
