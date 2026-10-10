"""主案を固定し、共通の境界反応と初期リスク当たりの効率を報告する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'アルゴリズム調査/00051_銘柄共通の境界反応とリスク効率'
TITLE = '共通原理とリスク効率の検証.html'


def read(path: Path) -> dict:
    """機能: 保存済み日本語JSONを読む。

    引数: path(Path)。返り値: 内容(dict)。外部通信はしない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def charts() -> dict:
    """機能: 当場の確定1分中値足を、表示用5分足へ集約する。

    引数: なし。返り値: 銘柄・場ごとのOHLCと構成分数(dict)。
    欠測を補間せず、取引条件を再計算しない。
    """
    with (HERE / '特徴.pkl').open('rb') as stream:
        features = pickle.load(stream)
    result = {'TOPIX': {}, 'NK225': {}}
    for (session, symbol), frame in features.items():
        rows = []
        for start, group in frame.groupby((frame.bar_start // 300).astype('int64') * 300, sort=True):
            rows.append([int(start), float(group.open.iloc[0]), float(group.high.max()),
                         float(group.low.min()), float(group.close.iloc[-1]), int(len(group))])
        result[symbol][session] = rows
    return result


def main() -> None:
    """機能: 固定14条件と全注文を自己完結した暗色HTMLへ保存する。

    引数: なし。返り値: なし(None)。事後順位で主案を差し替えない。
    """
    results = read(HERE / '売買結果.json')
    assert len(results['methods']) == 14
    assert any(m['id'] == 'S3_T' for m in results['methods'])
    for method in results['methods']:
        for account in method['accounts']:
            assert not account['orders'] or len(account['orders'][0]) == 13
            assert not account.get('risk_groups') or len(account['risk_groups'][0]) == 11
            account.pop('trades', None)
    evaluation_path = HERE / '報告評価.json'
    evaluation = read(evaluation_path) if evaluation_path.exists() else {
        'headline': '主案S3_Tを、両市場で同じ条件のまま検証。',
        'findings': ['境界への反応、供給と活動の確認、失敗線、出口を成績の計算前に固定しました。',
                     '同じ規則を使えることと、両市場で利益が出ることを分けて判定します。'],
        'audit': [],
    }
    data = dict(results=results, charts=charts(), evaluation=evaluation,
                policies={'F': '境界の外に2本連続で定着した側だけを追う。',
                          'R': '境界を越えた後、内側へ戻った失敗だけを逆へ取る。',
                          'S': '同じ突破事象で、定着又は失敗の最初の確認に従う。'},
                gates={'0': '価格だけ', '1': '供給の変化を確認', '2': '出来高の活動を確認', '3': '供給と出来高を確認'})
    # ----------------------------------------
    # 全注文とR台帳を残し、重複した返済脚だけを省く。
    template = (HERE / 'report_template.html').read_text(encoding='utf8')
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    content = template.replace('__DATA__', payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / TITLE
    path.write_text(content, encoding='utf8')
    meta = dict(主HTML=str(path), バイト数=path.stat().st_size,
                SHA256=hashlib.sha256(path.read_bytes()).hexdigest(), 主案='S3_T',
                手法数=len(results['methods']), セッション数=len(results['sessions']),
                注文数=sum(len(a['orders']) for m in results['methods'] for a in m['accounts']),
                外部描画ライブラリ=0, 現在API取得数=0)
    (OUTPUT / '生成記録.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
