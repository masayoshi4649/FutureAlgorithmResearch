"""00120を最新案内に追加し、既存の00119以下への導線を残す。"""

from pathlib import Path
import json


ROOT=Path(__file__).resolve().parents[2]
NAME='00120_段階トレーリング新規と利益玉の部分回転'
MAIN='段階トレーリングの結論と全セッション損益.html'


def prepend(path: Path, message: str) -> None:
    """
    機能: Markdownの表題直後に最新作業案内を一回だけ追加する。
    引数: path(Path)は既存案内、message(str)は位置に合う相対リンクの説明。
    返り値: None。過去00119の本文は前段の説明として残す。
    """
    text=path.read_text(encoding='utf-8')
    assert '<!--00120案内-->' not in text
    start=text.index('<!--00119案内-->')
    end=text.index('<!--00119案内終了-->')+len('<!--00119案内終了-->')
    old=text[start:end].replace('最新は','前段は',1)
    text=text[:start]+old+text[end:]
    header,tail=text.split('\n',1)
    text=header+'\n\n<!--00120案内-->\n'+message+'\n<!--00120案内終了-->\n'+tail
    path.write_text(text,encoding='utf-8')


def main() -> None:
    """
    機能: 公開後に根・調査一覧・知見の案内と最新作業カードを更新する。
    引数: なし。
    返り値: None。既存調査の金融成績は変更しない。
    """
    public=ROOT/'アルゴリズム調査'/NAME
    assert (public/MAIN).is_file() and (public/'公開目録.json').is_file()
    manifest=json.loads((public/'公開目録.json').read_text(encoding='utf-8'))
    detail=f"段階トレーリング新規と利益玉の部分回転を114条件・両商品40場で比較。両商品合計黒字は{manifest['both_net_positive']}/114。上下対称の個別回転とカバー保持を分け、残在庫と反復損失を実時刻で調べました。全条件の全場損益・改善結果・暗色在庫図を掲載しています。"
    prepend(ROOT/'README.md',f'最新は[00120：段階トレーリングの検証](アルゴリズム調査/{NAME}/{MAIN})。'+detail)
    prepend(ROOT/'アルゴリズム調査/README.md',f'最新は[00120：段階トレーリングの検証]({NAME}/{MAIN})。'+detail)
    prepend(ROOT/'アルゴリズム調査/共通/知見台帳/README.md',f'最新は[00120：段階トレーリング新規と利益玉の部分回転](../../{NAME}/README.md)。中値とLastの違い、残在庫、方向別停止の反復、約92%玉勝率と金額赤字、計算時のUID保存を法則単位で追加しました。')
    index=ROOT/'アルゴリズム調査/index.html'
    text=index.read_text(encoding='utf-8')
    assert '<!--00120開始-->' not in text
    card=f'''<!--00120開始--><article class="task latest"><div class="number">作業00120 <span class="badge">最新の検証</span></div><h2>段階トレーリング新規と利益玉の部分回転</h2><p>{detail}</p><a class="button" href="{NAME}/{MAIN}">短い結論と全場損益</a> <a href="{NAME}/改善後に残った損失.md">改善後の具体的な損失</a> <a href="{NAME}/README.md">読む順序と条件</a></article><!--00120終了-->'''
    text=text.replace('<main>','<main>\n'+card,1)
    text=text.replace('最新00119では全40場を検証。単独型と二脚合計口座を分け、合計利益だけでなく各場の安定性と実損失を確認しています。',
        '最新00120では段階トレーリングの114条件・全40場を検証。各場の損益と、残在庫・反復損失の具体箇所を確認しています。',1)
    index.write_text(text,encoding='utf-8')
    policy=ROOT/'アルゴリズム調査/調査方針.md'
    text=policy.read_text(encoding='utf-8')
    marker='## 2026年10月17日の段階トレーリング追加依頼'
    assert marker not in text
    header,tail=text.split('\n',1)
    note=f'''\n\n{marker}\n\n動く極値から3・4・5…単位で段階新規し、利益玉だけの追尾返済と空き枠再利用を上下両方向で反復する手法を検証する。3990→3993で初回、3993建玉を保有したまま3980→3984で二枚目、という未約定側の極値移動が意図。売りは鏡像。個別回転とカバーを保持した組回収を分けて測る。片方向上限TOPIXミニ10枚・日経マイクロ20枚を比較尺度として引き継ぐ。場内全返済・費用後時価を評価し、不利時の少枚数を仮定で済ませず実残枚数で確認する。利益玉だけの高勝率を安定黒字としない。00120の114条件は同じ既知40場の開発で、独立114標本や新しい市場での将来成功とはしない。\n'''
    policy.write_text(header+note+tail,encoding='utf-8')
    print('最新00120への案内と追加依頼の評価方針を保存しました。')


if __name__=='__main__':
    main()
