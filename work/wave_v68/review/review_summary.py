"""親が前半で固定した選定と順位だけを、価格感度の結果で再確認する。"""

import gzip
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def read(path: Path) -> object:
    """機能: 通常または圧縮 JSON を読み取る。

    引数: path(Path)。返り値: 内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def run() -> None:
    """機能: 親の前半固定選定を変えず、感度結果と未解決課題をまとめる。

    引数: なし。返り値: なし(None)。新たな順位や採用条件は作らない。
    """
    selection = read(WORK / '損失削減の比較と選定.json')
    sensitivity = read(HERE / '気配価格置換の集計.json')
    methods = {method['id']: method for method in sensitivity['methods']}
    completed = read(HERE / '気配価格置換の完了.json')
    assert len(methods) == 38 and completed['口座数'] == 2128
    assert all(period[symbol]['complete'] for method in methods.values()
               for period in method['periods'].values() for symbol in ('TOPIX', 'NK225'))
    identifiers = list(dict.fromkeys(['E01', 'R01'] + [item['id'] for item in selection['front_rank']]))
    focus = []
    for identifier in identifiers:
        raw = read(WORK / 'observed' / f'{identifier}.json.gz')
        method = methods[identifier]
        for period in ('前16', '後12', '全28'):
            for symbol in ('TOPIX', 'NK225'):
                metrics = method['periods'][period][symbol]
                comparison = method['対応基準比較'][period][symbol]
                focus.append(dict(id=identifier, base=method['base'], period=period, symbol=symbol,
                    raw_net=raw['periods'][period][symbol]['net'], quote_net=metrics['net'],
                    raw_campaign_loss=raw['periods'][period][symbol]['campaign_loss'],
                    quote_campaign_loss=metrics['campaign_loss'], quote_campaign_profit=metrics['campaign_profit'],
                    quote_average_losing_campaign=metrics['average_losing_campaign'],
                    quote_maximum_losing_campaign=metrics['maximum_losing_campaign'],
                    quote_settlement_max_drawdown=metrics['settlement_max_drawdown'],
                    quote_negative_sessions=metrics['negative_sessions'],
                    quote_net_without_maximum_profit_day=metrics['net_without_maximum_profit_day'],
                    comparison=comparison))
    summary = dict(全会計合格=True, 欠測注文数=0, 親の選定=selection['selected'],
        前半固定順位=[item['id'] for item in selection['front_rank']],
        後半を使った再選定=False, 重点条件=focus,
        解釈=[
            'E01_T05Xは元E01に対して両銘柄の負け組損失を減らすが、TOPIX後半では勝ち組利益も大きく減り、後半収支と場末最大下落が悪化する。',
            'E01_T05Xの気配価格感度で全28TOPIXが赤字となる。前半採用条件合格だけでは汎用的な改修を保証しない。',
            '連敗後30分休止P2Tは負け組損失合計を減らすが、負け組平均損失や最大負け組を必ずしも減らさない。連敗後の機会削減と一組の損切り改善を区別する。',
            '会計合格はアルゴリズム有効性の合格を意味しない。全28既知データであり、未見検証ではない。',
            '気配感度では発動条件・初回建値に基づく返済線・休止の勝敗判定を再計算していない。ラージ気配はmini/microの実約定保証ではない。',
            '場末最大下落は含み損を含む場内最大下落と異なる。正式な含み損評価は親の全観測時価復元を併用する。'],
        現在API取得=0, 実注文=0, 原資料変更=False)
    (HERE / '敵対的再確認の要約.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# 損失低減改修の敵対的再確認', '',
        '主評価は観測値で条件を全再生成した親のバックテスト。ここでは同じ注文列の売買価格だけをラージの最良気配へ置換し、価格感度と会計を独立に確認した。現在 API 取得・実注文・原資料変更はない。', '',
        f"38 条件・2,128 口座・{completed['注文検算数']:,} 注文・{completed['決済検算数']:,} 決済を検算し、欠測注文は 0 件。", '',
        f"前 16 場で親が選んだ条件は **{selection['selected']}**。前半固定順位の候補のみ重点確認し、後半から選び直していない。", '',
        '| 条件 | 銘柄 | 全28の観測値収支 | 全28の気配置換収支 | 負け組損失削減率 | 勝ち組利益維持率 |',
        '|---|---|---:|---:|---:|---:|']
    for item in focus:
        if item['period'] != '全28':
            continue
        comp = item['comparison']
        lines.append(f"| {item['id']} | {item['symbol']} | {item['raw_net']:,.0f}円 | {item['quote_net']:,.0f}円 | {comp['campaign_loss_reduction']*100:.1f}% | {comp['campaign_profit_retention']*100:.1f}% |")
    lines += ['', '## 判断', ''] + [f'- {text}' for text in summary['解釈']]
    lines += ['', '最初に読む資料は本書。数値は `敵対的再確認の要約.json`、全条件は `気配価格置換の集計.json`、全注文は `価格置換/*.json.gz`、検算項目と入力指紋は `気配価格置換の完了.json` の順に読む。']
    (HERE / '敵対的再確認.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('親固定の選定を変えず、重点5条件の再確認を保存しました。')


if __name__ == '__main__':
    run()
