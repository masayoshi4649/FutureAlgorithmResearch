"""奇数部分利確の保護価格と、経済的同一なのに理由だけ違う台帳を説明する。"""

from __future__ import annotations

import json
from pathlib import Path
import pickle

import numpy as np

import protection_runner as runner

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 指定済み説明条件のK000比較を読み、NKの理由差だけを特定する。

    引数: なし。返り値: なし (None)。未指定の候補・現在データ・新しいルールを使わない。
    """
    audit = runner.read(HERE / 'selected_accounting_audit.json')
    assert audit['監査目的'] == '説明用の未採用条件'
    selected = {row['id']: row for row in audit['候補']}
    fixed = runner.read(HERE / '探索条件の固定.json')
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    summary, differences = [], []
    for signal in ('H011', 'H019'):
        for manager in ('K020', 'K040'):
            item = selected[signal + '__' + manager]
            for symbol, result in item['K000対照']['symbols'].items():
                summary.append(dict(id=item['id'], symbol=symbol, **result))
            for case in item['K000対照']['sessions']:
                if case['symbol'] != 'NK225' or case['返済台帳完全一致']:
                    continue
                assert case['金銭経路一致']
                key = (case['session'], 'NK225')
                ready = inputs[key]
                with np.load(HERE / 'directions' / f'{signal}.npz') as archive:
                    state = archive['|'.join(key)]
                results = []
                for manager_id in ('K000', manager):
                    spec = next(m for m in fixed['managers'] if m['id'] == manager_id)
                    cfg = runner.managers.make_config(spec, key[1], ready)
                    results.append(runner.engine.run(ready, state, cfg, detail=True))
                before, after = results
                assert before['orders'].shape == after['orders'].shape
                np.testing.assert_array_equal(before['orders'][:, [0, 1, 2, 3, 4, 5, 7]], after['orders'][:, [0, 1, 2, 3, 4, 5, 7]])
                np.testing.assert_array_equal(before['curve'], after['curve'])
                for old, new in zip(before['orders'], after['orders']):
                    if old[6] == new[6]:
                        continue
                    row = int(old[0])
                    differences.append(dict(id=item['id'], session=key[0], symbol=key[1], 原本行=row,
                                            seq=int(ready['seq'][row]), time_s=float(ready['time_s'][row]),
                                            枚数=int(old[4]), 約定価格=float(old[5]),
                                            元理由=int(old[6]), 元理由名=runner.engine.REASONS[int(old[6])],
                                            変更理由=int(new[6]), 変更理由名=runner.engine.REASONS[int(new[6])]))
    result = dict(説明用条件のみ=True, 再選抜=False, 現在データ使用=False, API取得数=0,
                  K000対照=summary, 理由だけの相違=differences,
                  元独立会計SHA256=runner.digest(HERE / 'selected_accounting_audit.json'),
                  探索仕様SHA256=runner.digest(HERE / '探索条件の固定.json'))
    runner.save(HERE / 'partial_rounding_diagnostic.json', result)
    lines = ['# 部分利確の整数枚数と利益保護の包含', '',
             '同じ割合の設定でも、TOPIXは5枚から2枚を利確して3枚を残し、NKは10枚から5枚を利確して5枚を残す。利確率は40%と50%であり、この差が利益保護の実効価格を変える。', '',
             '初期ATRをA、建値から最高順行までをx ATRとする。2ATRで予定どおり部分利確し、他の決済や価格飛躍がない区間では、部分利確後の組最高利益と3ATR追跡が保護する組損益は次のとおり。', '',
             '|銘柄|初回R|組最高利益|3ATR追跡での組損益|',
             '|---|---:|---:|---:|',
             '|NK10→5枚|10A|(10＋5x)A|(5x−5)A|',
             '|TOPIX5→3枚|5A|(4＋3x)A|(3x−5)A|', '',
             '**K020は2R到達後、最高利益の25%を保護する。** NKはx≥2で始動し、その範囲では既存追跡の床が割合保護以上になる。TOPIXはx≥2で始動するが、2≤x＜8/3の範囲では割合保護のほうが厳しい。', '',
             '**K040は3R到達後、最高利益の50%を保護する。** NKはx≥4で始動し、その範囲では既存追跡に含まれる。TOPIXはx≥11/3で始動し、11/3≤x＜14/3では割合保護のほうが厳しい。', '',
             'したがって3Rは「3ATR順行」の意味ではない。部分利確後は枚数を減らしているため、組全体の時価利益が3Rへ達するには追加の順行が必要になる。', '',
             'これは通常経路の代数的説明であり、全経路の約定一致保証ではない。新規約定行で大きく順行する飛び、呼値、前行の注文と1行1イベント、通過済み価格の次行成行などは別途考慮する。', '',
             '## 保存13セッションでの実際の照合', '',
             '|条件|銘柄|注文完全一致区間|金銭経路全13一致|収支差円|DD差円|',
             '|---|---|---:|---|---:|---:|']
    for row in summary:
        lines.append(f'|{row["id"]}|{row["symbol"]}|{row["注文台帳同一セッション数"]}/13|{row["全13セッション金銭経路一致"]}|{row["期間収支差円"]:+,.0f}|{row["期間DD差円"]:+,.0f}|')
    lines += ['', 'NKのK040は両入口とも全13区間で理由まで完全一致した。K020は2026-09-24ナイトの返済理由だけが変わり、時刻・価格・枚数・全時価曲線は一致した。これはstopとtrailが同値となり、旧来の価格イベント優先順で理由が変わる例である。', '',
              'TOPIXでも保護追加が一律に良いわけではない。K040はH011で改善、H019で悪化し、同じ条件でも退出後の再エントリー経路が変わる。この説明を候補再選抜や将来の利益保証には使わない。', '',
              '独立会計の結果は selected_accounting_audit.json、理由差の原本行・価格・枚数は partial_rounding_diagnostic.json に保存。現在データ・追加通信は使用していない。', '']
    (HERE / 'partial_rounding_diagnostic.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(理由だけの相違=differences), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
