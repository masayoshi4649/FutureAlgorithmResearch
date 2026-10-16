"""全会計・未来切断・表示確認を通過した42条件を、新しい00086へ案内する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
FOLDER = '00086_二市場の状態で追従と指値反発を配分'
NAME = '二つの戦略への配分と全セッション損益.html'
OUT = ROOT/'アルゴリズム調査'/FOLDER


def read(path: Path) -> dict:
    """
    機能: 検証済み証跡を読む。
    引数: path(Path)。
    返り値: dict。保存された日本語JSON。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 成果物又は根拠の内容指紋を求める。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def main() -> None:
    """
    機能: 旧00085を保持し、新00086の短い読む順序と最新案内を公開する。
    引数: なし。
    返り値: None。基準と主の未達を隠さず、未見又は完成とは呼ばない。
    """
    old = ROOT/'アルゴリズム調査/00085_仮想成績による参加停止と再開'
    old_hashes = {str(p.relative_to(ROOT)): sha(p) for p in old.iterdir() if p.is_file()}
    audit_paths = [
        WORK/'audit/全27条件の全原板清算時価と最初約定取消及び途中返済の独立検算.json',
        WORK/'round2/audit/追加15条件の全原板気配改善と活動基準及び全親会計の独立検算.json',
        WORK/'review/追加15条件の独立会計と源稼働及び残る損失原因.json',
        WORK/'review/往復開始の短命化と逆共同方向を見逃す閾値の独立診断.json',
        WORK/'review/公開結論と約定模型及び無取引の解釈に関する独立読取.json']
    for path in audit_paths:
        assert read(path)['全合格'], path
    generated = read(HERE/'生成結果.json')
    displayed = read(HERE/'表示の独立検査.json')
    assert generated['全合格'] and displayed['全合格'] and displayed['目視確認']
    assert generated['HTML_SHA256'] == displayed['HTML_SHA256'] == sha(OUT/NAME)
    for relative, expected in generated['使用資料SHA256'].items():
        assert sha(ROOT/relative) == expected, relative
    for fixed_path in [WORK/'事前固定.json', WORK/'round2/事前固定.json']:
        fixed = read(fixed_path)
        for relative, expected in fixed['SHA256'].items():
            assert sha(ROOT/relative) == expected, relative
    analysis = read(WORK/'analysis/比較結果.json')
    assert analysis['全合格'] and analysis['条件数'] == 42
    assert analysis['both80'] == [] and analysis['all_sessions_positive'] == []
    shutil.copyfile(WORK/'analysis/比較結果.json', OUT/'公開会計.json')
    (OUT/'README.md').write_text(f'''# 00086 二市場の状態で追従と指値反発を配分

最初に **[{NAME}]({NAME})** を開いてください。初期表示は固定8：2配分、手法欄で全42条件の全30場損益を切り替えられます。

読む順序はHTMLの短い結論→全場表→必要なら折畳の源別・期間別・原因。数値の根拠は[公開会計.json](公開会計.json)です。

追従J2は両市場の5分進行・短期維持と逆OFI除外を使い、始値0.4%の追尾と30分期限で返済。反発O06は基準から8ラージ呼値に到達した片側だけ指値を予約し、1幅損切り・3幅利確します。固定配分はTOPIX8枚＋2枚、NK16枚＋4枚。状態選択は双方ERと範囲を確認して一源だけ動かす別案です。

第一段27条件は価格改善なしの悲観対照。追加15はQ=成立時の当時買ask/売bid価格、A=往復参加開始の当時価格へ基準更新、QA=両方。Qは約定仮定の修正、Aは戦略変更です。利益80%・全日黒字の解は見つかっておらず、無取引29場の主を成功扱いしません。

原本最終約定時計の代理順序とラージ板を使用。小商品実板・待ち順位・全量約定は未検証。5秒の人工追加遅延はありません。保存入力の全有効行で含み損と残玉返済料を評価し、異常気配除外行と未観測極値は補完しません。全30場は既知期間です。

再現と監査は以下を参照してください。

- [第一段27条件](../../work/wave_v90/事前固定.json)と[再生](../../work/wave_v90/research.py)。
- [追加15条件](../../work/wave_v90/round2/事前固定.json)と[再生](../../work/wave_v90/round2/research.py)。
- [全会計の独立監査](../../work/wave_v90/audit/全27条件の全原板清算時価と最初約定取消及び途中返済の独立検算.json)と[追加段の独立監査](../../work/wave_v90/round2/audit/追加15条件の全原板気配改善と活動基準及び全親会計の独立検算.json)。
- [残る損失の具体時刻](../../work/wave_v90/review/追加15条件の独立会計と源稼働及び残る損失原因.json)と[短命な往復状態](../../work/wave_v90/review/往復開始の短命化と逆共同方向を見逃す閾値の独立診断.json)。

全42条件・2,520口座を独立に検算済み。現在API取得・実注文は0件。旧00085を保持し、調査は継続中です。
''', encoding='utf-8')
    # ----------------------------------------
    # 入口の最新案内だけ更新し、過去の各作業を上書きしない。
    path = ROOT/'README.md'
    text = path.read_text(encoding='utf-8')
    line = f'最新の調査は **[00086：二市場の状態で追従と指値反発を配分](アルゴリズム調査/{FOLDER}/{NAME})** です。固定併用と状態選択の42条件・全30場を比較。[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。利益80%への調査は継続中です。'
    text, count = re.subn(r'^最新の調査は .*$', line, text, count=1, flags=re.MULTILINE)
    assert count == 1
    path.write_text(text, encoding='utf-8')
    path = ROOT/'アルゴリズム調査/README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00086案内開始-->.*?<!--00086案内終了-->\s*', '', text, flags=re.DOTALL)
    text = text.replace('**最新は00085の', '**00085の')
    first, rest = text.split('\n', 1)
    block = f'''<!--00086案内開始-->
**最新は00086の[{NAME}]({FOLDER}/{NAME})。固定配分・状態切替の42条件、全30場、古い指値仮定の修正と活動不足の原因。**

[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。利益80%への調査は継続中です。
<!--00086案内終了-->

'''
    path.write_text(first+'\n\n'+block+rest.lstrip(), encoding='utf-8')
    path = ROOT/'アルゴリズム調査/index.html'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'<!--00086開始-->.*?<!--00086終了-->\s*', '', text, flags=re.DOTALL)
    text = text.replace('class="task latest"', 'class="task"').replace('<span class="badge">最新</span>', '')
    text = re.sub(r'<p class="lead">.*?</p>', '<p class="lead">最新00086：追従と指値反発の配分・選択42条件。約定仮定を修正し、全30場の収支と安定性を比較します。</p>', text, count=1, flags=re.DOTALL)
    card = f'''\n<!--00086開始--><article class="task latest"><div class="number">作業00086 <span class="badge">最新</span></div><h2>二市場の状態で追従と指値反発を配分</h2><p>固定8：2配分と状態切替の42条件。全30場と源別寄与を掲載。両銘柄共通の安定性改善と利益80%は未達です。</p><a class="button" href="{FOLDER}/{NAME}">配分と全場損益</a> <a href="{FOLDER}/README.md">読む順序</a></article><!--00086終了-->\n'''
    assert '</header>' in text
    path.write_text(text.replace('</header>', '</header>'+card, 1), encoding='utf-8')
    for relative, expected in old_hashes.items():
        assert sha(ROOT/relative) == expected, relative
    proof = dict(全合格=True, 旧00085保持=old_hashes,
                 独立監査SHA256={str(p.relative_to(ROOT)): sha(p) for p in audit_paths},
                 公開SHA256={p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != '公開指紋.json'})
    (OUT/'公開指紋.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('00086を公開し、旧00085を保持しました。利益80%への調査は継続中です。', flush=True)


if __name__ == '__main__':
    main()
