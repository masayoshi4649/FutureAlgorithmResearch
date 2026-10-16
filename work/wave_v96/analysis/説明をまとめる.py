"""正式損益と独立原因検査だけから、短い日本語の説明を作る。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 正式会計又は独立検査済みの原因資料を読む。
    引数: path(Path)はJSONファイル。
    返り値: dict。保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明の数値根拠を現在の資料へ結びつける。
    引数: path(Path)は参照ファイル。
    返り値: str。SHA256の16進指紋。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 会計全範囲と原板原因の検査後に結論と説明を保存する。
    引数: なし。
    返り値: None。売買・会計・固定条件・参考選定を変更しない。
    """
    paths = [WORK / 'audit/全18全31の全台帳会計と3代表の独立出口及び全原板の検算.json',
             WORK / 'audit_support/同一依存定数補足による正式全1116口座及び288期間の最終受入.json',
             WORK / 'review/3正式レビューの独立原因要旨と次段の未検証仮説.json',
             WORK / 'review/10月2日日経09時34分の回復勝ち刈りと09時45分新固有損失の原板因果例.json',
             WORK / 'engine_review/後15未作成の全18前16実親会計と安定順による独立参考選定.json']
    for path in paths:
        proof = read(path)
        assert proof.get('全合格', proof.get('合格', False)), path.name
    analysis_path = HERE / '比較結果.json'
    analysis = read(analysis_path)
    summary = read(paths[2])
    assert summary['根集計SHA256'] == digest(analysis_path)
    assert summary['主'] == analysis['primary'] == 'S10_M1_UNL'
    assert summary['前16固定参考'] == analysis['selected'] == 'S10_M0_H30'
    assert summary['口座'] == 1116 and summary['商品期間群'] == 288
    for relative, expected in summary['成果SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
        paths.append(ROOT / relative)
    assert analysis['both80'] == summary['両商品金額80'] == []
    selected = analysis['results'][analysis['selected']]['periods']['全31']
    assert selected['TOPIX']['net'] == 265216 and selected['NK225']['net'] == -43456
    pair = summary['一軸の管理差と連鎖差']['S40_M0_H30→S10_M0_H30']
    assert pair['TOPIX']['同一判断符号変化']['利益→損失']['差円'] == -704000
    assert pair['NK225']['同一判断符号変化']['利益→損失']['差円'] == -451200
    floors = summary['利益床の実損益']['S10_M1_UNL']
    assert floors['TOPIX']['保護有効']['負け親'] == floors['NK225']['保護有効']['負け親'] == 0
    conclusions = [
        '今回の出口改修は、両銘柄の安定改善に届きませんでした。18表示条件（経済的に14組）で、両銘柄の金額利益80%を達成したものは0です。',
        '参考の初期0.1%版は平均・最大赤字を両銘柄で減らしましたが、黒字場数は旧17／29場からTOPIX15／29場・日経13／29場へ低下。日経の合計は−43,456円でした。',
        '原因は、回復する勝ちまで早く損切りし、空いた枠で次の負けにも入ったこと。出口を狭くするだけの改修は採用せず、入口と再参加の問題を切り分けます。'
    ]
    notes = dict(analysis['cause_notes'])
    notes.update({
        '回復勝ちを刈った金額': '初期0.4%→0.1%（保護なし・30分）で、元の負けはTOPIX50万円・日経27.2万円軽減。一方、元の勝ち8親・13親が負けになり、TOPIX70.4万円・日経45.12万円悪化しました。同じ実新規の比較です。',
        '10月2日日経の原板例': '09:34:15のショートは両市場の5分下落、両気配の下落、売り方向の板フローを確認して68630で新規。初期0.1%では09:34:52に68700で買返済し−11,552円。旧0.4%の同じ新規は10:04に68540で買返済し＋14,048円でした。早く空いた枠による09:45の新しいショートでも−11,552円。最初の逆行を方向仮説全体の失敗と扱ったことが悪化しました。',
        '利益床と入口の区別': '主の利益保護が発動した25親・24親は費用後黒字でしたが、未達の46親・52親は合計−1,554,728円・−560,704円。発動後の分類は事後診断であり、新規の勝率ではありません。発動まで待って新規すれば勝つとは推論できません。',
        '10月7日ナイトの原板例': '日経21:35:30、21:53:00、23:42:25の買いは各−13,152円。初期幅80円、利益保護開始160円に対し、実際の最大順行は40円・20円・0円でした。利益保護が働く前に、初期停止の失敗が続いた日です。',
        '中間幅の結果': '事後のS20_M2_H30は両銘柄で合計黒字ですが、TOPIXの最大赤字は旧19.0万円から23.5万円へ増加。黒字場数も旧17／17場から16／15場へ低下し、日経は最大利益日を除くと赤字です。前16の参考へ差し替えていません。',
        '執行モデルの範囲': 'ラージ先物の保存板気配を小商品の約定代理に使います。判断後の次正常気配で全量を約定させ、実小商品板・真の受信時刻・全量執行能力は今回検証していません。',
        '独立検算の範囲': '全18条件・1116口座・288商品期間、全注文と親料金及び全原板時価を独立照合。最初の返済と新診断の独立再生は主・旧対照・半利益版の3条件186口座。監査の不足定数を外部から同値補足して再実行し、固定売買コードと結果は変えていません。'
    })
    paths += [analysis_path, Path(__file__)]
    result = dict(全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
                  根集計SHA256=digest(analysis_path), 売買及び会計の変更=0,
                  conclusion=conclusions, cause_notes=notes,
                  根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
                  全31既知=True, 未見場数=0, API取得=0, 実注文=0)
    (HERE / '説明補足.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'全合格': True, '根拠数': len(result['根拠SHA256']), '結論': conclusions}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
