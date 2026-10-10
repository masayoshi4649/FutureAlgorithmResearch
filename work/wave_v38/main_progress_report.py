"""主206の計算済み比較を、未完了の独立検査と区別して表示する。"""

import report_adaptive as report


def main() -> None:
    """機能: 全補助を待つ間だけ、主6方式の暫定比較へ入口を作る。

    引数: なし。返り値: なし (None)。正式判定の存在時は上書きを拒否する。
    """
    runner=report.runner;here=runner.HERE
    assert not (here/'完備監査.json').exists()
    done=runner.read(here/'主再生の完了.json');assert done['全条件数']==206
    values=runner.read(here/'全条件の期間集計.json.gz');index={r['id']:r for r in values}
    assert len(index)==206
    chosen=[(label,index[identifier]) for label,identifier in report.COMPARISONS]
    body=['<p><a href="../index.html">調査一覧</a> ／ <a href="５分足と売買.html">5分足と売買</a> ／ <a href="比較計画.html">固定した比較計画</a></p>',
        '<h1>'+report.TITLE+'</h1><p><strong>独立監査中の暫定表示。</strong>主206条件の再計算は完了。補助768条件と全件の独立検算を実行中です。</p>',
        '<p>主案は、両市場の短期逆行で半量を減らし、その時点で長い逆行もあれば回復待ち、それ以外は120秒後から新しい有効公開で数量を戻す方式です。</p>',
        '<p>主案は黒字ですが、固定方式を明確に上回ってはいません。黒字・感度・使い分けの価値は分けて判定します。</p>',
        '<h2>全13セッション</h2>',report.previous.main_table(chosen,'all_symbols'),
        '<p>TOPIXミニ／NKマイクロ換算、初回5／10枚・片方向上限10／20枚。費用0・指定価格約定・場内返済。全13は既知データです。枚数は延べ返済枚数。</p>',
        '<details><summary>後半7セッション</summary>',report.previous.main_table(chosen,'symbols'),'</details>',
        '<details><summary>使い分けが裏目に出た例</summary><p>TOPIXでは時計復元で損失が7,000円から13,000円へ増え、NKでは回復待ちで利益が16,500円から7,500円へ減った例があります。</p><p><a href="../../work/wave_v38/分岐の反例と読み方.md">注文との対応</a></p></details>',
        '<p><a href="README.md">段階と資料案内</a></p>']
    (report.OUT/(report.TITLE+'.html')).write_text(report.style.page(report.TITLE,body),encoding='utf-8')
    readme=report.OUT/'README.md';source=readme.read_text(encoding='utf-8')
    addition='\n暫定集計は [主6方式の比較]('+report.TITLE+'.html)、注文の図解は [5分足と売買](５分足と売買.html) です。全974の検算完了前なので、正式採用の判定ではありません。\n'
    if addition not in source:readme.write_text(source+addition,encoding='utf-8')
    path=report.OUT.parent/'index.html';source=path.read_text(encoding='utf-8')
    source=source.replace('href="'+report.OUT.name+'/比較計画.html">974条件の比較計画 →','href="'+report.OUT.name+'/'+report.TITLE+'.html">主6方式の暫定比較 →')
    source=source.replace('主206条件の実データ再生を開始しました。補助768条件と独立検算を続けます。','主206条件の再計算は完了。補助768条件と全件独立検算を続けています。')
    path.write_text(source,encoding='utf-8')
    print('主206完了時点の暫定比較を表示。正式採用とは区別。')


if __name__=='__main__':main()
