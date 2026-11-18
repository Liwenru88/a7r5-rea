"""灰阶节点保护与候选恢复有不同、明确的更新边界。"""
import numpy as np
import native_conditional_grid as grid


def test_reference_freezes_gray_nodes_candidate_can_recover_them():
    ids=np.array([[0,1],[1,2],[3,4]])
    gray=np.array([True,False,False])
    mask,protected=grid.active_nodes(ids,gray,True)
    assert set(protected)=={0,1}
    assert np.all(mask[[0,1]]==0) and np.all(mask[[2,3,4]]==1)
    free,_=grid.active_nodes(ids,gray,False)
    assert np.all(free==1)
