"""手数料0会計だけの追補試験。金融データの探索は行わない。"""

import unittest
import numpy as np
import account145


class Tests(unittest.TestCase):
    """同じ原注文の集計と費用定義を検査する。"""

    def test_two_parents_with_partial_profit_and_loss(self):
        """
        機能: 部分利確後の損失も含め、2親の粗利益500円・粗損失500円を確認する。
        引数: self(Tests)。返り値: None。
        """
        rows = np.array([[1,0,0,1,2,100,1,1,0,0], [3,2,0,-1,1,110,2,0,0,0],
                         [5,4,0,-1,1,95,3,0,0,0], [7,6,1,-1,1,200,1,1,0,0],
                         [9,8,1,1,1,205,3,0,0,0]], float)
        bid, ask = np.ones(11)*99, np.ones(11)*100
        for row in rows:
            i=int(row[0])
            bid[i]=row[5] if row[3]<0 else row[5]-1
            ask[i]=row[5] if row[3]>0 else row[5]+1
        times=np.arange(11,dtype=float)
        quotes=dict(bid=bid,ask=ask,quote_valid=np.ones(11,bool))
        ready=dict(time_s=times,start=0.,session='人工_Day')
        packet=dict(session='人工_Day',inputs={('人工_Day','NK225'):ready},quotes={('人工_Day','NK225'):quotes})
        label=dict(direction='上昇',first_price=100.,final_price=205.,change=105.,final_price_time='人工',basis='人工')
        result=account145.account(rows,packet,'人工',label)
        self.assertEqual((result['profit'],result['loss'],result['net'],result['fees']), (500.,500.,0.,0.))
        self.assertEqual(result['parent_count'],2)
        self.assertEqual(result['entries'],2)
        self.assertEqual(result['quantity'],3)
        self.assertEqual(result['max_per_side'],2)
        original=rows.copy();original[:,9]=original[:,4]*385//10
        expected=account145.source.shared.prior.common.account(original,times,quotes,'人工','人工_Day','NK225')
        self.assertEqual(result['gross'],expected['gross'])
        self.assertEqual(result['net'],expected['net']+expected['fees'])
        with self.assertRaises(AssertionError):
            account145.account(original,packet,'人工',label)


if __name__=='__main__':
    unittest.main()
