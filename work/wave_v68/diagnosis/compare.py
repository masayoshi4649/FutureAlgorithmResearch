"""指定された損失低減候補だけを、基準と同じ入口の組で独立比較する。"""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent


def read(path: Path) -> dict:
    """機能: 圧縮結果を読む。

    引数: path(Path)。返り値: 結果(dict)。
    """
    return json.loads(gzip.decompress(path.read_bytes()))


def campaigns(result: dict) -> dict:
    """機能: 出口後の番号ではなく同じ入口行をキーとして組損益をまとめる。

    引数: result(dict)。返り値: 入口別の組(dict)。
    """
    output = {}
    for ledger in result['ledgers']:
        for cycle in ledger['cycles']:
            cid = int(cycle[0])
            trades = [t for t in ledger['trades'] if t['組'] == cid]
            first = trades[0]
            key = ledger['session'], ledger['symbol'], first['新規行']
            assert key not in output
            output[key] = dict(収支=sum(t['収支'] for t in trades), 利益損失前=sum(t['利益損失前'] for t in trades),
                手数料=sum(t['手数料'] for t in trades), 枚数=sum(t['枚数'] for t in trades), 方向=first['方向'],
                初回価格=first['建値'], 初回時刻=first['新規時刻'], 最終返済時刻=max(t['返済時刻'] for t in trades),
                制御理由=Counter(str(t['理由']) for t in trades),
                早期制御枚数=sum(t['枚数'] for t in trades if t['理由'] in (50,51,52)))
    return output


def account(values: list) -> dict:
    """機能: 決済集計器とは別に、組単位の利益・損失を計算する。

    引数: values(list[dict])。返り値: 会計(dict)。
    """
    return dict(組数=len(values), 利益=sum(max(r['収支'],0) for r in values), 損失=sum(max(-r['収支'],0) for r in values),
        収支=sum(r['収支'] for r in values), 勝組=sum(r['収支']>0 for r in values), 負組=sum(r['収支']<0 for r in values),
        手数料=sum(r['手数料'] for r in values), 全新規枚数=sum(r['枚数'] for r in values),
        最大組損失=max((max(-r['収支'],0) for r in values),default=0),
        早期制御組数=sum(r['早期制御枚数']>0 for r in values), 早期制御枚数=sum(r['早期制御枚数'] for r in values))


def compare(identifier: str, fixed: dict) -> dict:
    """機能: 指定された候補の効き方を前16・後12で同じ方法により分解する。

    引数: identifier(str)、fixed(dict)。返り値: 組別照合と集計(dict)。
    """
    candidate = read(SOURCE / f'observed/{identifier}.json.gz')
    base_id = candidate['variant']['base']
    original = read(SOURCE / f'observed/{base_id}.json.gz')
    before,after = campaigns(original), campaigns(candidate)
    output = dict(候補=identifier, 基準=base_id, 期間={}, 入口数=dict(共通=len(set(before)&set(after)),
        消えた=len(set(before)-set(after)), 新たに現れた=len(set(after)-set(before))),組の差=[])
    for period in ('前16','後12','全28'):
        names = fixed['全セッション'] if period == '全28' else fixed[period]
        output['期間'][period] = {}
        for symbol in ('TOPIX','NK225'):
            select = lambda key: key[0] in names and key[1] == symbol
            keys = [key for key in set(before)&set(after) if select(key)]
            dropped = [before[key] for key in set(before)-set(after) if select(key)]
            added = [after[key] for key in set(after)-set(before) if select(key)]
            a,b = account([r for k,r in before.items() if select(k)]),account([r for k,r in after.items() if select(k)])
            stored = candidate['periods'][period][symbol]
            assert abs(b['収支']-stored['net'])<1e-5
            assert abs(b['利益']-stored['campaign_profit'])<1e-5
            assert abs(b['損失']-stored['campaign_loss'])<1e-5
            pairs = Counter(('勝' if before[k]['収支']>0 else '負')+'→'+('勝' if after[k]['収支']>0 else '負') for k in keys)
            details = dict(基準=a, 改修=b, 同一入口結果=dict(pairs), 失われた入口会計=account(dropped), 新規入口会計=account(added),
                負組損失削減率=1-b['損失']/a['損失'], 勝組利益維持率=b['利益']/a['利益'],
                収支維持率=b['収支']/a['収支'], 同一入口の差=sum(after[k]['収支']-before[k]['収支'] for k in keys))
            output['期間'][period][symbol] = details
    # ----------------------------------------
    # 事後の差は説明・会計照合専用。入口・出口の条件生成には返さない。
    for key in sorted(set(before)|set(after)):
        a,b = before.get(key),after.get(key)
        if a is not None and b is not None:
            assert a['初回価格'] == b['初回価格'] and a['方向'] == b['方向']
            assert a['枚数'] == b['枚数']
        output['組の差'].append(dict(セッション=key[0],銘柄=key[1],新規行=key[2],基準=a,改修=b,
            収支差=(b['収支'] if b else 0)-(a['収支'] if a else 0)))
    return output


def main() -> None:
    """機能: 指定候補のみを照合して診断内に保存する。

    引数: --idsの候補ID列(str)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--ids',required=True)
    args=parser.parse_args()
    fixed=json.loads((SOURCE/'事前固定.json').read_text(encoding='utf8'))
    output={identifier:compare(identifier,fixed) for identifier in args.ids.split(',')}
    (HERE/'指定候補の独立比較.json').write_text(json.dumps(output,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    print('指定候補の組別照合済み',list(output),flush=True)


if __name__=='__main__':
    main()
