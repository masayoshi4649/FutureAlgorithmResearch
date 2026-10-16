"""初回活動と数量到達の母集団を、保存結果の小射影だけで比較する。"""

import hashlib
import json

import plan


def main() -> None:
    """
    機能: 公開同bytes結果を一読し、初回活動・数量二群・昼夜の率と全母数を小さく保存する。
    引数: なし。
    返り値: None。元NPZ・新出力NPZ・金融・APIを読まない。
    """
    purpose = plan.HERE / '原因分析の小射影目的.json'
    plan.write(purpose, dict(目的='初回Last代理と数量到達後の先着率を区別する。',
                            公開同bytesJSON=1, 元NPZ=0, 出力NPZ=0, 金融=0, API=0))
    target = plan.PUBLIC / '数量後の価格応答の公開集計.json'
    raw = target.read_bytes()
    expected = 'aad49e1186468c8bf069a902126c2f70d6f74a311bfe8ae03ef0978d99325d05'
    assert hashlib.sha256(raw).hexdigest() == expected
    saved = json.loads(raw.decode('utf-8'))
    selected = {}
    for symbol in ('TOPIX', 'NK225'):
        selected[symbol] = dict(totals=saved['totals'][symbol],
            raw_rows=sum(row['raw_rows'] for row in saved['rows'] if row['symbol'] == symbol),
            各場=[dict(session=row['session'],
                      medians={key: {name: value for name, value in row['groups'][key].items() if name.startswith('median_')}
                               for key in ('type1_decreased', 'type1_maintained')},
                      by_side=row['groups']['by_side'])
                 for row in saved['rows'] if row['symbol'] == symbol])
    plan.write(plan.HERE / '最初の代理方向と数量二群及び昼夜の小射影.json',
               dict(全合格=True, 出典SHA256=expected, 商品=selected, 元NPZ=0, 金融=0))
    minimal = {symbol: {name: {key: group[key] for key in ('n', 'plus', 'minus', 'unknown', 'window_end', 'rate')}
                       for name, group in selected[symbol]['totals']['all']['groups'].items()}
               for symbol in ('TOPIX', 'NK225')}
    print(json.dumps(minimal, ensure_ascii=False))


if __name__ == '__main__':
    main()
