"""完成場の終端資格と不変時計の源接続を、入力再読なしで記録する。"""

from pathlib import Path
import hashlib
import json


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 完成場の期限資格と時計列の不変接続を source の文面から確認する。
    引数: なし。
    返り値: None。大型入力、台帳、金融結果、API を読み取らない。
    """
    checks = {
        'work/e01_cross_market_20261014/engine/context.py':
            ["if finish:assert record['time_s'][-1]>=record['limit']"],
        'work/wave_v106/e01_reference/bridge.py':
            ["inputs, signals, hashes = rt['prepare'].load_inputs(verify=True)",
             'assert len(inputs) == 66'],
        'work/wave_v85/prepare.py':
            ["assert r['time_s'][-1] > r['limit']"],
        'work/wave_v48/update_20261001/replay_added_session.py':
            ["assert ready['time_s'][-1] > ready['limit']"],
        'work/wave_v91/inputs/prepare.py':
            ["time_s=ready['time_s']", "end=float(ready['limit']) + 300.",
             "limit=float(ready['limit'])"],
        'work/wave_v103/input/prepare.py':
            ["for name in ('seq', 'time_s', 'price', 'bid', 'ask')",
             "limit=record['limit']"],
        'work/wave_v104/peer/core.py':
            ["np.testing.assert_array_equal(execution_record[name], record[name]",
             "for name in ('start', 'end', 'limit', 'tick')"],
        'work/wave_v104/holdout_input/core.py':
            ['limit=self.end-300.'],
        'work/wave_v104/holdout_input/prepare.py':
            ["np.any(record['time_s'] >= record['limit'])"],
        'work/wave_v106/e01_pending_price/prices.py':
            ["record['time_s']", "limit=record['limit']"],
        'work/wave_v106/e01_trade_gate/prepare.py':
            ["record=a['normal_record']", "own=dict(symbol=symbol,record=record"],
    }
    evidence = []
    for relative, tokens in checks.items():
        saved = (ROOT / relative).read_bytes()
        source = saved.decode('utf-8-sig')
        for token in tokens:
            assert token in source, (relative, token)
        evidence.append(dict(path=relative, SHA256=hashlib.sha256(saved).hexdigest(),
                             確認文面=tokens))
    output = HERE / '完成場limit資格と旧正常時計の源接続.json'
    assert not output.exists()
    output.write_text(json.dumps(dict(全合格=True, source=evidence,
        結論='limit は正常観測の最終時刻ではなく、観測区間 end より300秒前の場内返済期限。完成場を要求する条件と旧資格は整合する。旧時間列と期限スカラーを改変せず接続している。',
        留保='end−300 という定義だけでは、任意の途中入力が期限を越えたことは証明できない。完成場 guard は必要な検査であり省略しない。今回は source の接続を確認し、実際の全33入力の終端再走査をしていない。',
        時点='根が正式一回の terminal 0 を通知した後の補足 source 監査。金融前に終端を独立再測定したという主張はしない。',
        大型入力=0, 台帳=0, 金融結果読取=0, 金融再実行=0, API=0),
        ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 源件数=len(evidence),
                         SHA256=hashlib.sha256(output.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
