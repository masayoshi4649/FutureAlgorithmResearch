"""既存の数値表示検査と、最終画像を根が目視した記録を接続する。"""

import hashlib
import json
from pathlib import Path


def main() -> None:
    """
    機能: 全数値検査・表記修正後の差分検査・根の画像目視を一つの証跡にまとめる。
    引数: なし。固定済みの表示検査JSONと、それが指定する画像を使用する。
    返り値: None。市場の再生、予測の再採点、実注文は行わない。
    """
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    full_path = here / 'public_view/正式三候補と事後追補及び四十四条件全場表の独立表示検査.json'
    delta_path = here / 'public_view/revision4/render_v2/率差単位と反証リンクの独立差分表示検査_v2.json'
    full_bytes, delta_bytes = full_path.read_bytes(), delta_path.read_bytes()
    full, delta = json.loads(full_bytes), json.loads(delta_bytes)
    assert full['全合格'] and delta['全合格']
    assert delta['前QA_SHA256'] == hashlib.sha256(full_bytes).hexdigest()
    assert delta['公開JSON全項目同値'] and delta['正式選択不変']
    images = []
    for stage, proof in [('数値表示を含む前版', full), ('最終表記版', delta)]:
        for item in proof['画面']:
            image_path = root / item['画像']
            assert hashlib.sha256(image_path.read_bytes()).hexdigest() == item['画像_SHA256']
            images.append(dict(版=stage, path=item['画像'], SHA256=item['画像_SHA256'], 根目視済み=True))

    # ----------------------------------------
    # 上記6枚は根のview_image表示で確認済み。独立検査の目視未実施とは区別する。
    target = here / 'public_view/根の最終画像目視と独立表示検査の接続.json'
    assert not target.exists()
    evidence = dict(
        全合格=True,
        根の目視確認=True,
        独立全数値検査=dict(path=full_path.relative_to(root).as_posix(), SHA256=hashlib.sha256(full_bytes).hexdigest()),
        最終版差分検査=dict(path=delta_path.relative_to(root).as_posix(), SHA256=hashlib.sha256(delta_bytes).hexdigest()),
        最終公開_SHA256=delta['公開_SHA256'],
        画面=images,
        目視所見='暗色背景で可読。最近10場60%と全37場48.1%を近接表示。正式3候補は別章。携帯幅の表は横スクロール可能。率差は％ポイント、価格幅はpt。',
        留保='表示の正しさは予測の有効性の証拠追加ではない。',
        原入力=0, 元数値結果再読=0, 再測定=0, 金融=0, API=0,
    )
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('根の目視6枚と最終差分検査を接続しました。')


if __name__ == '__main__':
    main()
