"""非有限clockの系譜修正を、完成finite normal input33へ原NPZ再読なしで結ぶ。"""

import hashlib
import pickle

import numpy as np

import common


def run() -> None:
    """
    機能: 完成33cacheの候補時計finiteと同原seqを各一読して、修正前後の全出力同値を確認する。
    引数: なし。
    返り値: None。原NPZ66/旧E01input33を再読せず、初版Falseとsourceを保持する。
    """
    archive=common.HERE/'初版_非有限時計系譜False保持'
    original=common.read(archive/'全33場の保有中取引更新票.json')
    old=(archive/'features.py').read_text(encoding='utf-8')
    insert='    # 非有限候補clockはscalarの早期UNKNOWNと同じく、未来に依存する窓系譜を作らない。\n    up[~finite]=0;down[~finite]=0;baseline[~finite]=-1;first[~finite]=rows[~finite]+1\n'
    assert old.replace('    total=up.astype(np.int64)+down;',insert+'    total=up.astype(np.int64)+down;')==(common.HERE/'features.py').read_text(encoding='utf-8')
    for name in ('policy.py','daily.py','votes.py','prepare.py','data.py','storage.py','catalog.py','common.py'):
        assert (archive/name).read_bytes()==(common.HERE/name).read_bytes(),name
    current=common.source_hashes();art=common.read(common.HERE/'全normal票と逆票損失退出の人工検査.json')
    assert art['全合格'] and art['source_SHA256']==current
    total_rows=0;checks=[]
    for session,item in original['cache'].items():
        saved=(common.ROOT/item['path']).read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256']
        packet=pickle.loads(common.gzip.decompress(saved));assert packet['session']==session
        for symbol,a in packet['accounts'].items():
            q=a['quotes'];assert np.all(np.isfinite(q['time_s']))
            for w,v in a['votes'].items():
                assert np.all(np.isfinite(v['candidate_price_time_s']))
                np.testing.assert_array_equal(v['candidate_price_time_s'],q['time_s'])
                np.testing.assert_array_equal(v['candidate_raw_seq'],q['seq'])
                total_rows+=len(q['time_s'])
            checks.append(dict(session=session,symbol=symbol,全normal候補時計finite=True,修正分岐非適用で全出力同値=True))
    assert len(checks)==66 and common.source_hashes()==current
    proof=dict(全合格=True,scope='source差分は非有限候補時計の窓系譜/票sentinelだけ。実全normal候補時計finiteにより修正分岐は全行非適用。',
        初回FalseSHA256=common.digest(common.HERE/'非有限候補clockの系譜接頭False.json'),初版metadataSHA256=common.digest(archive/'全33場の保有中取引更新票.json'),
        元source_SHA256=original['source_SHA256'],新source_SHA256=current,照合=checks,商品窓normal行数=total_rows,
        完成新cache読取=33,原NPZ追加読取=0,旧E01input追加読取=0,金融=0,API=0)
    common.write(common.HERE/'非有限clock系譜修正と完成全33入力の同値補完.json',proof)
    value=dict(original,source_SHA256=current,原入力作成source_SHA256=original['source_SHA256'],
        初版metadata保持=True,非有限時計修正補完SHA256=common.digest(common.HERE/'非有限clock系譜修正と完成全33入力の同値補完.json'),
        追加原NPZ読取=0,追加旧input読取=0,同値補完cache読取=33,開始終端source一致=True)
    common.write(common.HERE/'全33場の保有中取引更新票.json',value)
    print('NaN候補系譜をsentinelへ、完成finite normal全33は全出力同値。原NPZ再読0。',flush=True)


if __name__=='__main__':run()
