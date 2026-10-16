"""正式全範囲検算と原因証跡を照合し、安定性の結論を短く説明する。"""

from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))

import data
import research


def evidence(name: str, expected: dict) -> tuple[Path, dict]:
    """
    機能: 完了証跡の対象・合格値と依存指紋を確認する。
    引数: name(str、95内の相対位置)、expected(dict、必須値)。
    返り値: tuple[Path,dict]は検算完了資料。新しい売買は実行しない。
    """
    path = WORK / name
    value = research.read(path)
    for key, required in expected.items():
        assert value[key] == required, (name, key)
    for key in ('SHA256', '正式結果SHA256', '根拠SHA256'):
        for relative, fingerprint in value.get(key, {}).items():
            assert data.digest(ROOT / relative) == fingerprint, (name, relative)
    if '根集計SHA256' in value:
        assert value['根集計SHA256'] == data.digest(HERE / '比較結果.json')
    if '固定SHA256' in value:
        assert value['固定SHA256'] == data.digest(WORK / '事前固定.json')
    return path, value


def main() -> None:
    """
    機能: 2356口座・608期間・全原板と原因の完了後だけ表示用説明を作る。
    引数: なし。
    返り値: None。正式損益・主・前16参考・売買条件は変更しない。
    """
    fixed = research.read(WORK / '事前固定.json')
    research.validate(fixed)
    account_path = HERE / '比較結果.json'
    result = research.read(account_path)
    assert result['条件数'] == 38 and result['primary'] == fixed['主'] == 'P3_R3_N'
    proof_specs = [
        ('audit/全38全31の新入口と四源反転及び全原板会計と安定性の独立検算.json', dict(合格=True, 人工専用=False)),
        ('engine_review/後15未作成の全38前16実親会計と安定順による独立参考選定.json', dict(全合格=True, 前16口座数=1216, 後15損益閲覧=0)),
        ('engine_review/現在P0及びJ10全62保存経済の前94との独立完全一致.json', dict(全合格=True)),
        ('review/全38条件全31の独立親会計と安定性及び一軸経路分解.json', dict(全合格=True, 口座=2356, 商品期間群=608)),
        ('review/全38の直前完了親と四源再参加及び候補時刻移動の独立原因分解.json', dict(全合格=True, 口座=2356)),
        ('review/主と事前参考及び旧追従の最悪3場原板と赤字救済及び大勝ち依存の独立反証.json', dict(全合格=True, 口座=2356)),
    ]
    proofs = [evidence(name, expected) for name, expected in proof_specs]
    full = proofs[0][1]
    assert full['検査件数']['口座'] == 2356 and full['検査件数']['商品期間集計'] == 608
    review = proofs[3][1]
    assert review['注文'] == 17398 and review['親'] == 8699
    assert review['両商品金額80'] == result['both80'] == []
    selected = result['selected']
    assert selected == 'P0_R1_S'
    values = result['results'][selected]['periods']['全31']
    stable = result['results'][selected]['stability']['全31']
    baseline = result['results']['P0_R0']['stability']['全31']
    assert all(values[s]['positive_sessions'] == 17 and values[s]['active_sessions'] == 29
               for s in ('TOPIX', 'NK225'))
    conclusion = [
        '毎セッション安定して損小利大を達成する解には未達。38条件中、両銘柄で金額利益80%を満たす条件は0でした。',
        f'前16で選んだ参考 {selected} は、両銘柄とも黒字17／取引29場。日経の最大赤字は約{baseline["NK225"]["worst_session_loss_yen"]/10000:.1f}万円→{stable["NK225"]["worst_session_loss_yen"]/10000:.1f}万円へ減りましたが、TOPIXは約{baseline["TOPIX"]["worst_session_loss_yen"]/10000:.1f}万円→{stable["TOPIX"]["worst_session_loss_yen"]/10000:.1f}万円へ増えました。',
        '両市場の5分方向が一致した時に入り、損切り後の逆方向新規だけを制限する手法です。価格観測を増やす主の改修は両赤字。両銘柄で一貫した損失抑制を確認できていません。',
    ]
    notes = dict(result['cause_notes'])
    notes.update({
        '入口の増加': 'P2_R0→P3_R0では親取引がTOPIX87→248、日経71→246へ増加。しかし同じ新規が残ったのは12・10親だけ。早い候補の発火・消費で後続の入口も入れ替わり、旧の利益入口が消え、新経路の損失が利益を上回りました。',
        '連鎖の変化': '旧の「損失後の同方向は黒字」という親群の成績は、新しい入口・再参加でも維持される法則ではありません。何を見送るかで、次に入る時刻と「どの損失の後か」が変わります。全38を実際に再生して確認しました。',
        '板の反例': '主のTOPIX 9月24日09:11:45の売りでは、両市場の5分価格は下落していましたが、相手の日経の15秒買い・売り気配は0呼値進行。相手の約定価格の下落だけでは、現在の板も同じ方向へ進んだとは判断できませんでした。',
        '正常支持でも失敗': '主の日経10月9日08:51の売りは、両価格・両気配が下落し、注文増減も売り優勢でした。それでも返済気配での最大順行は10円だけ。旧280円幅の追尾で08:57:20に43,552円損失。強い直前支持だけで次の持続を保証できず、未確証の新規へ大きな幅を許した損失も残っています。',
        '結果の範囲': '全2356口座・17398注文・8699親・608商品期間を独立照合し、最悪場の476原本点でも同じseqの3段板を確認。全31は既知で、未知場の安定性を証明した結果ではありません。',
    })
    fingerprints = {str(path.relative_to(ROOT)): data.digest(path) for path, _ in proofs}
    fingerprints.update({str(account_path.relative_to(ROOT)): data.digest(account_path),
                         str(Path(__file__).relative_to(ROOT)): data.digest(Path(__file__))})
    research.save(HERE / '説明補足.json', dict(
        全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
        根集計SHA256=data.digest(account_path), 根拠SHA256=fingerprints,
        conclusion=conclusion, cause_notes=notes, 売買及び会計の変更=0,
        目標未達=True, 全31既知=True, 主変更=False, 参考事後差替え=False, API取得=0, 実注文=0))
    print('\n'.join(conclusion), flush=True)


if __name__ == '__main__':
    main()
