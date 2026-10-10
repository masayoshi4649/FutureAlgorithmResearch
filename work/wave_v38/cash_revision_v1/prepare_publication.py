"""既存の完備確認を、固定済み974条件へ接続する準備処理。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main() -> None:
    """機能: 新しい収集・完備確認と進捗表示を作る。

    引数: なし。返り値: なし (None)。固定した売買・入力・判定を変更しない。
    """
    source=(HERE.parent/'wave_v37/assess_results.py').read_text(encoding='utf-8')
    source=source.replace('partial_', 'adaptive_').replace('主363と補助64','主206と補助768').replace('全427','全974')
    source=source.replace('value = assessment.assess(index, sessions, fixed[\'全セッション\'], verification=False)',
        "ledgers = {identifier:runner.read(runner.HERE/'ledgers'/(identifier+'.json.gz')) for identifier in assessment.PAIRED_IDS}\n    value = assessment.assess(index, sessions, fixed['全セッション'], ledgers, verification=False)")
    (HERE/'assess_results.py').write_text(source,encoding='utf-8')

    # ----------------------------------------
    source=(HERE.parent/'wave_v37/completion_guard.py').read_text(encoding='utf-8')
    start=source.index('def wave_revision(');end=source.index('def verify()',start)
    source=source[:start]+source[end:]
    source=source.replace('partial_', 'adaptive_').replace("wave_fixed = wave_revision(reference)","wave_fixed = runner.read(runner.HERE/'adaptive_wave_fixed.json')")
    source=source.replace("('',fixed['conditions'],1474),('supplementary',fixed['supplementary_conditions'],256)","('',fixed['conditions'],846),('supplementary',fixed['supplementary_conditions'],3072)")
    source=source.replace("['監査版']==2","['監査版']==1").replace('adaptive_wave_fixed_v2.json','adaptive_wave_fixed.json')
    source=source.replace('(11102,1730,3416)','(25324,3918,7792)')
    source=source.replace("provisional = assessment.assess(index,sessions,fixed['全セッション'],verification=False)","ledgers={identifier:runner.read(runner.HERE/'ledgers'/(identifier+'.json.gz')) for identifier in assessment.PAIRED_IDS}\n    provisional = assessment.assess(index,sessions,fixed['全セッション'],ledgers,verification=False)")
    source=source.replace("assessment.assess(index,sessions,fixed['全セッション'],verification=True)","assessment.assess(index,sessions,fixed['全セッション'],ledgers,verification=True)")
    source=source.replace('全条件数=363,補助条件数=64','全条件数=206,補助条件数=768').replace('全427','全974')
    source=source.replace("'全保存統計一致','全台帳配列一致','元終了以前')", "'全保存統計一致','全台帳配列一致','元終了以前','全分岐独立一致','全成熟注文独立一致','全組R超過独立一致')")
    source=source.replace("'全予算予約一致','全保存数値一致','全台帳配列一致')", "'全予算予約一致','全保存数値一致','全台帳配列一致','分岐集計独立一致','全組R超過独立一致')")
    (HERE/'completion_guard.py').write_text(source,encoding='utf-8')

    # ----------------------------------------
    path=HERE/'update_progress_index.py';source=path.read_text(encoding='utf-8')
    source=source.replace('反証を準備中','反証を実行中').replace('人工検査中','再生・独立検算中')
    source=source.replace('新しい実相場損益は未再生です。','主206条件の実データ再生を開始しました。補助768条件と独立検算を続けます。')
    source=source.replace('00033の準備','00033の進行状況')
    path.write_text(source,encoding='utf-8')
    folder=ROOT/'アルゴリズム調査/00033_復元方式の自動選択と改善8条件の反証'
    path=folder/'README.md';source=path.read_text(encoding='utf-8')
    source=source.replace('**設計・人工検査の段階です。この作業の新しい実相場損益はまだ再生していません。**',
        '**事前検査を通過し、主206条件の実データ再生を開始しました。補助768条件と全件の独立検算が完了するまで暫定です。**')
    path.write_text(source,encoding='utf-8')
    path=folder/'比較計画.html';source=path.read_text(encoding='utf-8')
    source=source.replace('新しい実相場損益は未再生','主206条件の実データ再生中').replace('人工検査中','再生・独立検算中')
    path.write_text(source,encoding='utf-8')
    print('974条件の完備確認を接続し、進行中表示へ更新。')


if __name__=='__main__':main()
