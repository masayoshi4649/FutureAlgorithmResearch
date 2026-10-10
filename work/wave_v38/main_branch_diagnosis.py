"""主206だけで計算できる対応差を記録し、補助未完了の採否は宣言しない。"""

import adaptive_runner as runner
import adaptive_assessment as assessment


def main() -> None:
    """機能: 固定4方式の同じ元組で、選んだ方式と反対方式の差を集計する。

    引数: なし。返り値: なし (None)。乱数評価と正式採否は全補助後に行う。
    """
    fixed=runner.prepare()
    done=runner.read(runner.HERE/'主再生の完了.json');assert done['全条件数']==206
    ledgers={identifier:runner.read(runner.HERE/'ledgers'/(identifier+'.json.gz')) for identifier in assessment.PAIRED_IDS}
    pairs=assessment.branch_pairs(ledgers,fixed['全セッション'])
    output=[]
    for names,label in ((fixed['全セッション'],'全13'),(fixed['後半7セッション'],'後7')):
        for symbol in runner.SYMBOLS:
            for layer in ('逆方向','その他'):
                selected=[p for p in pairs if p['session'] in names and p['symbol']==symbol and p['層']==layer]
                output.append(dict(期間=label,銘柄=symbol,層=layer,元組数=len(selected),
                    選択差円=sum(p['選択差円'] for p in selected),選択差R=sum(p['選択差R'] for p in selected),
                    差が正=sum(p['選択差円']>1e-6 for p in selected),差が負=sum(p['選択差円'] < -1e-6 for p in selected),
                    差が同値=sum(abs(p['選択差円'])<=1e-6 for p in selected)))
    runner.save(runner.HERE/'主のみの分岐診断.json',dict(主再生完了=True,独立監査完了扱い=False,
        補助未完了の暫定=True,正式採否なし=True,対応元組数=len(pairs),層別=output,対応元組=pairs))
    for row in output:print(row)


if __name__=='__main__':main()
