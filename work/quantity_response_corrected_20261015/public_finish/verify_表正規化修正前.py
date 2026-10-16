"""説明追記後の表・参照・隔離表示を完成させる。"""

from __future__ import annotations

import importlib.util
import json

import finish


def main() -> None:
    """
    機能: 既保存の説明資料と初版から表不変・補足算術・暗色広狭表示を再確認する。
    引数: なし。
    返り値: None。金融・原入力・原結果・測定sourceは変更しない。
    """
    assert not finish.PROOF.exists()
    html = (finish.HERE / '仕上げ対象HTMLの同bytes私有コピー.html').read_bytes()
    old = (finish.AUDIT / '公開HTMLの同bytes私有コピー.html').read_bytes()
    text = html.decode('utf-8')
    expected = finish.cells(text)
    assert expected == finish.cells(old.decode('utf-8'))
    assert finish.HTML.read_bytes() == html
    archive = finish.WORK / 'public_archive/表示数量を観測した後の方向応答_初版.html'
    assert archive.read_bytes() == old
    sources = finish.read_json(finish.AUDIT / '数量公開六十六集計と先着分母及び表示の独立監査.json')['source_SHA256']
    assert all(finish.sha((finish.ROOT / path).read_bytes()) == value for path, value in sources.items())
    md = finish.PUBLIC / '結論と未検証の売買.md'
    mdtext = md.read_text(encoding='utf-8')
    supplemental = finish.AUDIT / '正の公表差更新回数の一回と複数の補足算術.json'
    extra = finish.read_json(supplemental)
    numeric = []
    for symbol in ('TOPIX', 'NK225'):
        for key in ('正増1更新', '正増複数更新'):
            row = extra['集計'][symbol][key]
            assert row['resolved'] == row['plus'] + row['minus']
            ratio = row['plus'] / row['resolved']
            assert abs(ratio - row['rate']) < 1e-14
            statement = f"{row['plus']:,}／{row['resolved']:,}＝{ratio*100:.2f}%"
            assert statement in mdtext
            numeric.append(dict(symbol=symbol, group=key, plus=row['plus'], resolved=row['resolved'], rate=ratio))
    for phrase in ('因果効果', '約定回数や方向別枚数ではない', '未測定'):
        assert phrase in mdtext
    paths = (finish.HTML, md, finish.PUBLIC / 'README.md')
    link_count = sum(finish.links(path) for path in paths)
    assert '支持されませんでした' in text and '最初の活動代理だけでも' in text
    assert '停止時1＋修正版66' in text and '観測0' in text
    assert '売買成績ではありません' in text and '利益・費用回収・真の補充は未測定' in text

    # ----------------------------------------
    helper_path = finish.ROOT / 'work/wave_v52/review/verify_report.py'
    spec = importlib.util.spec_from_file_location('数量表示の隔離描画', helper_path)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.OUT = finish.PUBLIC
    renderer.VISUAL = finish.HERE / 'screens_v2'
    renderer.PROBE = '''<script>
/**
 * 機能: 表の全セル・暗色・本文幅と未定義値を隔離Chromeで検査する。
 * @param {なし} なし。
 * @returns {object} 検査件数と表示品質。
 */
function verifyQuantityDisplay(){
 const expected=__TABLE_VALUES__;
 const tables=Array.from(document.querySelectorAll('table')).map(t=>Array.from(t.rows).map(r=>Array.from(r.cells).map(c=>c.textContent.replace(/\\s+/g,' ').trim())));
 if(JSON.stringify(tables)!==JSON.stringify(expected))throw Error('表セル不一致');
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 const body=getComputedStyle(document.body).backgroundColor;
 if(body!=='rgb(13, 20, 33)')throw Error('暗色背景');
 if(/NaN|Infinity|undefined/.test(document.body.innerText))throw Error('未定義表示');
 return {全合格:true,表数:tables.length,表セル数:tables.flat(2).length,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:body};
}
try{document.body.dataset.check=JSON.stringify(verifyQuantityDisplay());}
catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}
</script>'''.replace('__TABLE_VALUES__', json.dumps(expected, ensure_ascii=False))
    clone = text.replace('<html lang="ja">', '<html lang="ja"><head>', 1)
    clone = clone.replace('</style><main>', '</style></head><body><main>', 1).replace('</main></html>', '</main></body></html>', 1)
    images = [renderer.render(clone, 'PC_1450', 1450, 1100),
              renderer.render(clone, 'モバイル_520', 520, 1000),
              renderer.render(clone, '詳細_1450', 1450, 1100,
                  '<script>document.querySelector("details").open=true;document.querySelector("details").scrollIntoView();</script>')]
    proof = dict(全合格=True, 初版HTML_SHA256=finish.sha(old), 公開HTML_SHA256=finish.sha(html),
        公開文書={str(path.relative_to(finish.ROOT)): finish.sha(path.read_bytes()) for path in paths},
        source_SHA256={str(path.relative_to(finish.ROOT)): finish.sha(path.read_bytes()) for path in
                       (finish.HERE / 'finish.py', finish.HERE / 'verify.py', helper_path)},
        測定source不変更=sources, 全表セル不変更=True, 表セル数=sum(len(r) for t in expected for r in t),
        補足算術=numeric, 補足算術_SHA256=finish.sha(supplemental.read_bytes()),
        ローカルリンク数=link_count, 画像=images, root画像目視=False,
        初回表示検査='Falseとfailed DOMを保持。検査JSの置換用文字列が未定義検査の正規表現にも置換されたため、私有QAだけ訂正。公開HTMLと測定sourceに変更なし。',
        原入力追加読=0, 原結果追加読=0, 金融=0, API=0,
        読取履歴=dict(初版原入力読=1, 初版観測=0, 修正版原入力読=66, 修正版口座=66, 独立標本増加ではない=True),
        範囲='既保存小算術による説明・全表不変・ローカル参照・隔離描画のみ。売買/因果/真補充は未検証。')
    finish.PROOF.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=True, 証跡=str(finish.PROOF), SHA256=finish.sha(finish.PROOF.read_bytes()),
                         HTML_SHA256=finish.sha(html), 画像=[row['画像'] for row in images]), ensure_ascii=False))


if __name__ == '__main__':
    main()
