"""完成した公開資料と台帳の終端を、目標未達のまま継続メモへ結ぶ。"""

import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00119_戦略の自動選択と場内黒字の再探索'


def load(path: Path) -> dict:
    """
    機能: 保存済みの小さい終了証跡を読む。
    引数: path(Path)は完成証跡。
    返り値: dict。原市場・金融結果・巨大台帳を解析しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """
    機能: 実際に視認した画像と完了反映を確認し、次回の重複を防ぐ。
    引数: なし。rootが実画像を視認した後に一度実行する。
    返り値: None。公開済み段階の会計・金融源・実装を変えない。
    """
    cover = PUBLIC / '結論と全セッション損益.html'
    cover_sha = hashlib.sha256(cover.read_bytes()).hexdigest()
    visuals = []
    for name in ('final_desktop', 'final_mobile'):
        path = BASE / 'visual' / name / '描画検査.json'
        proof = load(path)
        assert proof['source_SHA256'] == cover_sha
        assert proof['rows'] == 40 and proof['dark'] and not proof['horizontalOverflow']
        assert hashlib.sha256(Path(proof['image']).read_bytes()).hexdigest() == proof['image_SHA256']
        proof['viewed_by_root'] = True
        proof['視認内容'] = '実公開HTMLの暗色、本文の収まり、表内スクロール、結論と全40場表を確認。'
        path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        visuals.append(path.relative_to(ROOT).as_posix())
    # ----------------------------------------
    # 研究の完了記録と目標の達成を分ける。
    finished = list(BASE.glob('系列試行の完了反映とビュー同期_*.json'))
    assert len(finished) == 1
    proof = load(finished[0])
    assert proof['全合格'] and len(proof['完了ID']) == 10
    assert proof['目標達成の宣言'] is False and proof['金融再生'] == 0
    assert proof['deep検証'] and proof['閲覧データ同期']
    audit = BASE / 'v9/report_fixture/公開九段階の指紋と参照及び新旧区分の独立確認.json'
    assert hashlib.sha256(audit.read_bytes()).hexdigest() == '53f14b80b5f67a6a32802f7c188364b7b0711221d2279cc777ca9d4db301f9fa'
    path = BASE / '根の継続作業メモ.json'
    previous = load(path)
    backup = BASE / '公開前の根メモ.json'
    assert not backup.exists()
    backup.write_bytes(path.read_bytes())
    value = dict(
        状態='今回検証と公開を終了・毎場安定黒字の目標は未達',
        公開=cover.relative_to(ROOT).as_posix(), 公開SHA256=cover_sha,
        完了='初回と改善1〜7、少額E01追加再確認の九段階を公開。中断fを含む十試行を台帳へ反映。',
        暫定候補='少額E01の商品別固定設定を独立運転。二口座の場末収支を保存会計から合算。',
        全四十=dict(net=14882,black=26,red=1,inactive=13,mean=372.05,median=178,
            worst=-822,top3_removed=9204),
        追加七=dict(net=1070,black=3,red=1,inactive=3),
        限界=['低活動・微小利益。毎場黒字及び損小利大の完成解ではない。',
              '二口座合算は新金融0、共同MTM・DD・資金制約と分散効果は未検証。',
              'hは旧33保存引用と新7の入力資格変更を伴う別測定。',
              '改善は既知40場。回数を独立データ数や未知での成功へ数えない。',
              '実小型板・真受信順・実同時約定を未観測。'],
        最終改善='初期気配差込み予算の新8条件も全赤字。4改善4悪化。これ以上の新金融は今回行っていない。',
        知見='共通知見四分類へ00119の15法則と出典・実測・限界を追記。README等の最新導線を更新。',
        完了反映=finished[0].relative_to(ROOT).as_posix(),
        公開確認=audit.relative_to(ROOT).as_posix(), 実画像視認=visuals,
        注意='完成したのは今回の調査・公開。利益目標達成の宣言や実注文はしていない。')
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('九段階公開・十試行終端・実画像視認を確認。安定黒字の目標は未達として保全しました。')


if __name__ == '__main__':
    main()
