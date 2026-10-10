"""五つの単純入口と四つの固定幅を、短い暗色HTMLで比較する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'アルゴリズム調査/00052_ATRを使わない単純手法'
TITLE = 'ATRなし20条件の説明と損益.html'
ENTRIES = {
    'P01': '当場最初の観測価格から上へ0.10%を越えれば買い、下へ0.10%を越えれば売る。',
    'P02': '20分平均±2標準偏差の帯を、上へ抜ければ買い、下へ抜ければ売る。',
    'P03': '前足が帯の下側外、現足が帯内へ戻れば買い。上側外から戻れば売る。',
    'P04': '現在足を除く直前20分の高値を越えれば買い、安値を割れば売る。',
    'P05': '8分EMAが21分EMAを上抜けば買い、下抜けば売る。',
}


def read(path: Path) -> dict:
    """機能: 保存された日本語JSONを読む。

    引数: path(Path)。返り値: 内容(dict)。外部通信はしない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def charts() -> dict:
    """機能: 当該場の中値1分足を表示用5分足へ集約する。

    引数: なし。返り値: 銘柄・場別の表示足(dict)。欠落分は補間しない。
    """
    features = pickle.loads((HERE / '特徴.pkl').read_bytes())
    result = {'TOPIX': {}, 'NK225': {}}
    for (session, symbol), frame in features.items():
        times = frame['bar_start'] if 'bar_start' in frame else frame['source_bar_start']
        rows = []
        for start, group in frame.groupby((times // 300).astype('int64') * 300, sort=True):
            rows.append([int(start), float(group.open.iloc[0]), float(group.high.max()),
                         float(group.low.min()), float(group.close.iloc[-1]), int(len(group))])
        result[symbol][session] = rows
    return result


def main() -> None:
    """機能: 全20条件と全約定を自己完結したHTMLへ保存する。

    引数: なし。返り値: なし(None)。売買結果から新しい条件を作らない。
    """
    results = read(HERE / '売買結果.json')
    assert len(results['methods']) == 20
    for method in results['methods']:
        for account in method['accounts']:
            assert not account['orders'] or len(account['orders'][0]) == 13
            assert not account.get('width_groups') or len(account['width_groups'][0]) == 9
            account.pop('trades', None)
    evaluation_path = HERE / '報告評価.json'
    evaluation = read(evaluation_path) if evaluation_path.exists() else {
        'headline': '五つの単純な入口を、四つの固定幅で比較しました。',
        'findings': ['条件を先に固定し、両銘柄へ同じ計算を適用しました。',
                     '下の一覧は全20条件です。初期表示は結果から選んだ確認候補です。'],
        'audit': [],
    }
    default = evaluation.get('defaultMethod', 'P03_W05')
    assert any(m['id'] == default for m in results['methods'])
    data = dict(results=results, charts=charts(), evaluation=evaluation, entries=ENTRIES, defaultMethod=default,
                selectionNote=evaluation.get('selectionNote',
                    '初期表示P03_W05は20条件の結果から選んだ確認候補です。事前の本命や未知期間検証の合格ではありません。'))
    # ----------------------------------------
    # 注文と初期幅の台帳は全件残し、返済脚の重複だけを省く。
    template = (HERE / 'report_template.html').read_text(encoding='utf8')
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    content = template.replace('__DATA__', payload)
    assert '__STYLE__' not in content and '__CHART__' not in content
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / TITLE
    path.write_text(content, encoding='utf8')
    meta = dict(主HTML=str(path), バイト数=path.stat().st_size,
                SHA256=hashlib.sha256(path.read_bytes()).hexdigest(), 初期表示=default,
                手法数=len(results['methods']), セッション数=len(results['sessions']),
                注文数=sum(len(a['orders']) for m in results['methods'] for a in m['accounts']),
                外部描画ライブラリ=0, 現在API取得数=0)
    (OUTPUT / '生成記録.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
