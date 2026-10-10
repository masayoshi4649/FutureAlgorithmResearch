"""元E01の追加５場素材と独立原本監査・旧共通入力を再照合する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]


def sha(path):
    """機能: 抽出済み素材の完全性を分割ハッシュで検査する。

    引数: path(Path)。返り値: SHA256文字列(str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while part:=stream.read(4*1024*1024):value.update(part)
    return value.hexdigest()


def main():
    """機能: ５場の信号・約定系列・気配・既存原本抽出行数の整合を読み取り確認する。

    引数: なし。返り値: なし(None)。元素材・旧結果・条件は変更しない。
    """
    completed=json.loads((WORK/'prepared/抽出完了.json').read_text(encoding='utf-8'))
    independent=json.loads((HERE/'追加3場のデータと旧キャッシュの独立監査.json').read_text(encoding='utf-8'))
    expected={(r['セッション'],r['銘柄']):r for r in independent['追加原本']}
    old=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes());oldq=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    rows=[];count=old_exact=0
    for proof in completed['場別']:
        folder=WORK/'prepared'/proof['対象']
        for path,digest in proof['出力SHA256'].items():assert sha(ROOT/path)==digest
        inputs=pickle.loads((folder/'new_inputs.pkl').read_bytes());signals=pickle.loads((folder/'signals.pkl').read_bytes())
        assert set(signals)=={'entry','B00','B01'}
        for key,ready in inputs.items():
            n=len(ready['seq']);np.testing.assert_equal(len(ready['last']),n)
            assert np.all(np.diff(ready['seq'])>0) and np.all(np.diff(ready['time_s'])>=0)
            assert np.all(np.isin(signals['entry'][key],(-1,0,1))) and len(signals['entry'][key])==n
            for code in ('B00','B01'):
                a=signals[code][key]
                for name in ('direction','source_row','source_event_index'):assert len(a[name])==n
                assert np.all(np.isin(a['direction'],(-1,0,1)))
                available=a['source_row']>=0
                assert np.all(a['source_row'][available]<=np.flatnonzero(available))
            with np.load(folder/'features'/f'約定系列_{key[1]}_{key[0]}.npz') as tape:
                for name in ('seq','time_s','last'):np.testing.assert_array_equal(tape[name],ready[name])
                bid,ask,mid=tape['bid'],tape['ask'],tape['mid']
                assert np.all(np.isfinite(bid+ask)) and np.all((bid>0)&(ask>bid))
                assert np.all((tape['bid_qty']>0)&(tape['ask_qty']>0))
                np.testing.assert_array_equal(mid,(bid+ask)/2)
                if key in old:
                    for name in ('seq','time_s'):np.testing.assert_array_equal(ready[name],old[key][name])
                    for name in ('bid','ask','mid'):np.testing.assert_array_equal(tape[name],oldq[key][name])
                    old_exact+=1;match='旧wave_v60配列のseq・時計・全気配が完全一致'
                else:
                    a=expected[key]
                    assert n==a['品質']['有効入力行数'] and int(ready['seq'][0])==a['有効先頭seq'] and int(ready['seq'][-1])==a['有効末尾seq']
                    match='独立原本全文監査の有効行数・先頭末尾seqと一致'
                last=ready['last'];outside=(last<bid)|(last>ask)
                rows.append(dict(セッション=key[0],銘柄=key[1],有効行数=n,照合=match,元信号保存一致=True,
                    最終約定価格が同行売買気配の外にある行数=int(sum(outside)),同行気配外率=float(np.mean(outside)),
                    最終約定価格と気配中値の絶対差中央値=float(np.median(np.abs(last-mid)))))
            count+=n
    report=dict(結論='元E01追加５場・10口座の素材と元信号が保存SHA・独立原本監査に整合。旧２場４口座は共通入力の全seq・時計・気配が完全一致。',
        追加場数=5,口座数=len(rows),全有効行数=count,旧共通入力完全一致口座数=old_exact,口座別=rows,
        注意=['最終約定価格は同行の発注可能気配とは異なる。last指定価格の理想再生と次行bid/ask約定の再生を区別する。',
        '元信号は抽出時の既存signal_auditで切断・未来改変・反射・同秒順を合格し、その生成結果を変更せず保存した。',
        '新６原本の全文採取は先行独立監査で実行済み。ここでは保存素材へ対応する行数・seq終端・価格配列整合を確認した。'],
        コードSHA256=sha(Path(__file__)),API追加取得数=0,原本書込数=0)
    (HERE/'元E01追加5場素材の独立照合.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','追加場数','口座数','全有効行数','旧共通入力完全一致口座数')},ensure_ascii=False))


if __name__=='__main__':main()
