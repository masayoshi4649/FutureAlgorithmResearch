"""役割合成の順序・ID分離と枚数枠を、人工約定だけで検査する。"""

import unittest
import numpy as np
import run_roles145 as roles


class RoleTests(unittest.TestCase):
    """三担当の同一親IDが混同されず、元配列も変更されないことを検査する。"""

    def test_roles(self):
        """人工約定の三担当合成と次正常気配・数量上限を検査する。

        引数: self(RoleTests)はテストインスタンス。
        返り値: None。失敗時にはAssertionError。
        """
        data={'quotes':dict(bid=np.array([100.,100.,110.,110.]),ask=np.array([101.,101.,111.,111.]),quote_valid=np.ones(4,bool))}
        components=[]
        for quantity in (5,3,2):
            component=np.array([[1,0,0,1,quantity,101,90,1,0,0],[3,2,0,-1,quantity,110,93,0,0,0]],float)
            original=component.copy()
            roles.saved.verify(data,component,quantity)
            components.append(component)
            np.testing.assert_array_equal(component,original)
        combined=roles.assemble(*components)
        assert len(set(combined[:,2]))==3
        checked=roles.saved.verify(data,combined,10)
        self.assertEqual(checked['max_per_side'],10)
        self.assertEqual(float(np.sum(-combined[:,3]*combined[:,4]*combined[:,5]*100)),9000.)
        with self.assertRaises(AssertionError):
            roles.saved.verify(data,combined,9)


if __name__=='__main__':
    unittest.main()
