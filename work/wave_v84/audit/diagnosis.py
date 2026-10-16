"""損失説明に使う理由別件数と金額を、保存決済から独立に照合する。"""
from accounts import load,data
from context import *


def partition(values: np.ndarray) -> dict:
    """機能: 決済収支を利益・損失へ分ける。

    引数: values(ndarray)。返り値: 件数と会計(dict)。
    """
    return dict(脚数=len(values),利益=float(values[values>0].sum()),損失=float(-values[values<0].sum()),
        収支=float(values.sum()),黒字脚=int((values>0).sum()),赤字脚=int((values<0).sum()))


def main() -> None:
    """機能: 同幅6条件の理由別・連敗・現在値端点と約定の差を検算する。

    引数: なし。返り値: なし(None)。事後診断を取引判断へ反映しない。
    """
    source=load(WORK/'analysis/同幅6手法の損失構造.json');inputs=data.load_data()
    checks=0;positive_stop=0;examples=[]
    for model,methods in source['models'].items():
        stage='final/delay0' if model=='main' else 'ideal_fee'
        for method in methods:
            name=method['id'];ledger=load(WORK/stage/'ledgers'/f'{name}.pkl')
            for symbol,expected in method['symbols'].items():
                groups=[];endpoints=0.;runs=[]
                for key,saved in sorted(ledger.items()):
                    if key[1]!=symbol:continue
                    ts=saved['trades'];groups.append(ts);r=inputs[key];value=1000. if symbol=='TOPIX' else 10.
                    endpoints+=float(np.sum(ts[:,3]*ts[:,4]*value*(r['price'][ts[:,2].astype(int)]-r['price'][ts[:,1].astype(int)])))
                    losses=[]
                    for tr in ts:
                        if tr[10]<0:losses.append(tr)
                        elif losses:runs.append(losses);losses=[]
                    if losses:runs.append(losses)
                ts=np.concatenate(groups);analysis=expected['analysis'];checks+=1
                assert partition(ts[:,10])==analysis['全脚']
                for column,label in [(11,'新規理由'),(12,'返済理由')]:
                    for code,summary in analysis[label].items():assert partition(ts[ts[:,column]==int(code),10])==summary
                loss=analysis['連続赤字']
                assert max([0]+[len(run) for run in runs])==loss['最大連敗数']
                worst=min(runs,key=lambda run:sum(tr[10] for tr in run),default=[])
                assert sum(tr[10] for tr in worst)==loss['最大赤字区間収支'] and len(worst)==loss['最大赤字区間脚数']
                assert abs(endpoints-analysis['CurrentPrice端点進行損益'])<1e-5
                assert abs(endpoints-ts[:,9].sum()-analysis['CurrentPrice端点と約定の差'])<1e-5
    # ----------------------------------------
    # reason1は発動理由であり約定後の赤字保証ではない。F5の分岐はnetで検査する。
    for path in (WORK/'final/delay0/ledgers').glob('F5*.pkl'):
        for key,saved in load(path).items():
            ts=saved['trades'];chosen=ts[(ts[:,12]==1)&(ts[:,10]>0)];positive_stop+=len(chosen)
            if len(chosen):examples.append(dict(ID=path.stem,セッション=key[0],商品=key[1],件数=len(chosen)))
    assert positive_stop==17
    result=dict(合格=True,同幅モデル商品別検査数=checks,F5損切り発動でも料金後黒字となった脚=positive_stop,
        該当口座=examples,注記='reason1は現在値による初期逆行の発動理由。返済気配での確定損益が正ならF5は即ドテンする。凍結元説明の「損切りなら待機」は表示用説明で訂正し、計算条件は変更しない。',
        診断SHA256=digest(WORK/'analysis/同幅6手法の損失構造.json'))
    save('公開損失診断と理由名の独立照合.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='該当口座'},ensure_ascii=False))


if __name__=='__main__':main()
