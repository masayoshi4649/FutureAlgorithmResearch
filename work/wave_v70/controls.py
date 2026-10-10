"""損失枠を同じにして保険だけを外す追加診断対照。選定には使用しない。"""

import argparse
import hashlib
from pathlib import Path

import study

HERE = Path(__file__).resolve().parent


def catalog(fixed: dict) -> list[dict]:
    """機能: 元保険条件の価格・期限条件を維持し、保険だけ0の五対照を作る。

    引数: fixed(dict)。返り値: 六入口×五対照(list[dict])。
    """
    groups = [('D16','H01',['H01','H02','H04']),('D32','H03',['H03','H05']),
              ('D16H30','H06',['H06']),('D16A8W4','H07',['H07']),('D32A16W8','H08',['H08'])]
    lookup = {c['id']:c for c in fixed['条件']}
    result = []
    for source in study.SOURCES:
        for name,parent,matched in groups:
            config = dict(lookup[source+'_'+parent])
            config.update(kind=0,manager=name,id=source+'_'+name,paired=False,control=True,
                          name='同じ損失枠・期限で保険なし',group='追加原因診断',matched_Hids=[source+'_'+v for v in matched])
            result.append(config)
    return result


def freeze() -> None:
    """機能: 初回結果を見た後の診断対照として、追加条件を再生前に固定する。

    引数: なし。返り値: なし(None)。元192の固定・選定を上書きしない。
    """
    path = HERE/'追加対照の事前固定.json'
    assert not path.exists()
    fixed = study.load(HERE/'事前固定.json')
    study.save(path,dict(条件=catalog(fixed),段階='初192の後の原因診断、採用の再選定には使わない',
                         理由='元基準のstop16と保険条件stop32の差を保険の効果と混同しない。',
                         一致='source・初回・元玉stop・元玉trail・全玉stop/profit・保有期限は対応Hと同じ。kindを0として保険だけを作らない。',
                         既知性='結果を見た後の対照。未知データ検証ではない。',
                         SHA256={str(p.relative_to(study.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (HERE/'controls.py',HERE/'engine.py',HERE/'study.py',HERE/'事前固定.json',HERE/'前半選定.json')}))


def run(source: str) -> None:
    """機能: 保険を外した五対照を同じ初回列で再生し別フォルダへ保存する。

    引数: source(str)、空なら全入口。返り値: なし(None)。
    """
    extra = study.load(HERE/'追加対照の事前固定.json')
    fixed = study.load(HERE/'事前固定.json')
    ready = study.load(study.ROOT/'work/wave_v69/prepared/inputs.pkl')
    features = study.load(study.ROOT/'work/wave_v69/prepared/features.pkl')
    signals = study.load(HERE/'inputs/signals.pkl')
    schedule = study.load(HERE/'inputs/schedule.pkl')
    for config in extra['条件']:
        if source and config['source']!=source:
            continue
        target = HERE/'controls/results'/(config['id']+'.json')
        if target.exists():
            continue
        rows,ledgers = [],{}
        for key in sorted(ready):
            orders,trades,curve,counters = study.engine.simulate(*study.arguments(config,key,ready,features,signals,schedule))
            rows.append(study.account(key,ready,orders,trades,curve,counters))
            ledgers[key] = dict(orders=orders,trades=trades,counters=counters,
                               curve_hash=hashlib.sha256(curve.tobytes()).hexdigest(),paired_metadata=None)
        ledger = HERE/'controls/ledgers'/(config['id']+'.pkl')
        study.save(ledger,ledgers)
        periods = {p:{s:study.aggregate(rows,s,keys) for s in study.SYMBOLS} for p,keys in
                   [('前16',fixed['前16']),('後12',fixed['後12']),('全28',fixed['全セッション'])]}
        study.save(target,dict(config=config,rows=rows,periods=periods,ledger_SHA256=hashlib.sha256(ledger.read_bytes()).hexdigest()))
        print(config['id'],'追加診断56口座完了',flush=True)


def main() -> None:
    """機能: 保存再生のネットワークを遮断し、診断固定又は再生を実行する。

    引数: --freeze(bool)、--source(str)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--source',default='')
    args = parser.parse_args()
    study.socket.socket.connect = study.deny
    study.socket.create_connection = study.deny
    if args.freeze:
        freeze()
        print('保険の有無だけを比較する追加対照30を固定しました')
    else:
        run(args.source)


if __name__=='__main__':
    main()
