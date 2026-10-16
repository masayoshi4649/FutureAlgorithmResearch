"""一読済み診断だけから、根が掲載できる短い損失理由を作る。"""

from collections import Counter

import tools


def run() -> None:
    """
    機能: 全変更場の実測と限界を短い表・説明へまとめる。
    引数: なし。一読済みの診断、小結果、金融前固定の小 JSON だけを読む。
    返り値: None。大型入力、台帳、金融本体は再読・再生しない。
    """
    proof, proof_sha = tools.read(tools.HERE / 'P1L8全変更場の票と原seq及び実親入替の診断.json')
    small, small_sha = tools.read(tools.HERE / 'P1L8の小結と全変更場.json')
    fixed, fixed_sha = tools.read(tools.SOURCE / '金融事前固定.json')
    cid = small['条件']; old = fixed['baseline'][cid]['symbols']; new = small['symbols']
    counts = {}; rows = []
    for symbol in ('TOPIX', 'NK225'):
        group = [s for s in proof['scenes'] if s['symbol'] == symbol]
        removed, added, common = [], [], []
        for s in group:
            for p in s['全実親の対応']:
                (removed if p['変更'] == '消えた旧親' else added if p['変更'] == '新たな親' else common).append(p)
        counts[symbol] = dict(変更場=len(group), 消えた旧実親=len(removed),
            消えた旧勝ち親=sum(p['旧実親']['収支'] > 0 for p in removed),
            消えた旧負け親=sum(p['旧実親']['収支'] < 0 for p in removed),
            新実親=len(added), 新勝ち親=sum(p['新実親']['収支'] > 0 for p in added),
            新負け親=sum(p['新実親']['収支'] < 0 for p in added),
            分母='同枚数・同出口比較で、実親 cid 集合が変化した親。全33場の勝率ではない。')
    for s in proof['scenes']:
        rows.append(dict(session=s['session'], symbol=s['symbol'], 旧収支=s['旧会計']['収支'],
            新収支=s['新会計']['収支'], 差=s['五寄与']['収支変化'], 寄与5={k:s['五寄与'][k] for k in tools.FIVE},
            消えた旧実親=[p['旧実親'] for p in s['全実親の対応'] if p['変更'] == '消えた旧親'],
            新実親=[p['新実親'] for p in s['全実親の対応'] if p['変更'] == '新たな親']))
    metrics = {s:dict(旧=old[s], 新=new[s], 利益の減少=old[s]['利益'] - new[s]['利益'],
        損失の減少=old[s]['損失'] - new[s]['損失'], 収支差=new[s]['収支'] - old[s]['収支']) for s in ('TOPIX','NK225')}
    output = dict(全合格=True, 結論='既知と二票以上は情報の十分さの条件であり、方向の優位を保証しない。'
        '旧負けを消しても、旧勝ち消失と後参加・場停止の変化を含めると TOPIX は999円だけ改善、NKは1780円悪化した。',
        TOPIXの等式='40,836円の旧損失回避−16,083円の旧勝ち消失−23,754円の新参加純損失＝999円改善。',
        TOPIX新参加の内訳='−7,918円−20,418円＋4,582円＝−23,754円。',
        変更全場=rows, 親の分母=counts, 全33の安定性=metrics,
        source=[dict(path=(tools.HERE/'P1L8全変更場の票と原seq及び実親入替の診断.json').relative_to(tools.ROOT).as_posix(),
                     pointer='/scenes',sha256=proof_sha),
                dict(path=(tools.HERE/'P1L8の小結と全変更場.json').relative_to(tools.ROOT).as_posix(),pointer='/symbols',sha256=small_sha),
                dict(path=(tools.SOURCE/'金融事前固定.json').relative_to(tools.ROOT).as_posix(),pointer='/baseline/'+cid+'/symbols',sha256=fixed_sha)],
        追加金融再生=0, 大型資料再読=0, API=0,
        未確定=['少票は既知でも判断材料が少ない。未知は情報資格の不足であり、逆方向や損失予告とは限らない。',
            '新参加の balance は+0.10、−0.20、−1/7。今回は強同方向を要求しない中間案なので、明確な順行優位を示す参加ではない。',
            'さらに入口を絞るとこの新負けを消せるとは限らない。今回の旧勝ち消失が反証で、後続運転を含めた別対照が必要。',
            '黒字場数、全場中央値、上位3場除外だけで判断を逆転させない。金額80%や平均損小利大は両銘柄とも未達。'])
    sha = tools.write('P1L8で40836円回避が999円改善に留まった理由.json', output)
    text = '''# 40,836円の旧損失を避けても、改善が999円だった理由

TOPIXでは旧負け40,836円を避けた一方、旧勝ち16,083円を消し、新しい参加で差し引き23,754円を失いました。**40,836−16,083−23,754＝999円**です。共通親の出口変更は0円で、公開時の採否と後参加・場停止が原因です。

時刻はすべて保存された**価格代理時計のJST**です。同じ秒でも別normal行・原seqの次気配で約定しています。

|場・商品|旧→新収支|変わった取引|
|---|---:|---|
|9/21デイ・NK|+1,780→0円|11:55:04の買い65000を、既知1票で拒否。旧は11:58:43に65020で返済していた。|
|9/21ナイト・TOPIX|+3,165→−20,836円|20:31:24の買い4105は既知0票で拒否し、旧勝ち16,083円を失う。旧は21:03:08に利益停止。新は翌01:20:21に買い4112.5、01:21:12に4111で返済し、7,918円を追加損失。|
|9/24ナイト・TOPIX|−20,418→−20,418円|18:31:27の買い4056を未知で拒否。新は翌00:21:43に売り4061.5へ入り、00:24:05に4065.5で返済。別親で同じ20,418円を失った。|
|10/7ナイト・TOPIX|−20,418→+4,582円|18:20:44の売り4154を既知0票で拒否。新は翌00:02:15に買い4138、00:13:18に4139で返済し、25,000円改善。|

新しいTOPIXの3親は**1勝・2敗**でした。9/21は20票・方向釣合い+0.10、9/24は5票・−0.20、10/7は7票・−1/7で、二票以上かつ強い逆票ではないという条件を満たしていました。ただし、これは「明確にその方向へ進む」ことを確認した条件ではありません。

旧負けを拒否すると旧口座の早期損失停止が消え、後の候補へ参加できます。旧勝ちを拒否すると利益停止も消え、後の負けへ参加する場合があります。したがって、**旧取引を単に除外した結果を改善額とみなせません**。

TOPIXの黒字29場・赤字4場は不変で、最大場損失は20,418円から20,836円へ増えました。金額利益割合は61.56%、平均利益4,249円に対して平均損失15,918円です。NKは勝ち1場を無取引へ変え、金額収支は1,780円悪化しました。両銘柄共通の安定した損小利大を達成した改善とはいえません。

根拠：[全変更場の公開票・原seq・実注文](P1L8全変更場の票と原seq及び実親入替の診断.json)、[全33場の小結](P1L8の小結と全変更場.json)、[新規金融の結果](../finance/結果.json)。新旧4場・8台帳と入力4cacheだけを各一読し、追加金融・原板・原NPZ・APIは0です。これは既知データの対照原因であり、未見の成功確率ではありません。
'''
    path = tools.HERE/'P1L8の変更場と小改善の理由.md'; assert not path.exists()
    path.write_text(text, encoding='utf-8', newline='\n')
    print(sha, flush=True)


if __name__ == '__main__': run()
