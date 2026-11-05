"""Check actual solver callback progress and high-resolution sensor geometry."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import core
import sys
sys.path.insert(0,str(core.RESEARCH/'vendor/fit_eval_python312'))
from scipy.optimize import least_squares
from photo_preview import preview_coordinates,apply_rows
from training_progress import TrainingProgress,read_progress,read_trace


class LiveProgressTests(unittest.TestCase):
    def test_4k_geometry_and_bounded_color_batches(self):
        xs,ys=preview_coordinates(SimpleNamespace(crop_width=9504,crop_height=6336,crop_left_margin=32,crop_top_margin=20))
        self.assertEqual((len(xs),len(ys)),(3840,2560))
        self.assertTrue(np.all(np.diff(xs)>0) and np.all(np.diff(ys)>0))
        self.assertGreaterEqual(xs.min()-4,32)
        self.assertLess(xs.max()+4,32+9504)
        self.assertEqual((xs[0],ys[0]),(40,28))
        rgb=np.random.default_rng(1).random((19,11,3));sizes=[]
        def transform(x):sizes.append(len(x));return x*.37+.06
        np.testing.assert_array_equal(apply_rows(rgb,transform),rgb*.37+.06)
        self.assertEqual(sizes,[8,8,3])

    def test_actual_scipy_progress_does_not_change_result(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'progress.json';p=TrainingProgress(path,2);snapshots=[]
            original=p.update
            def update(**v):original(**v);snapshots.append(read_progress(path))
            with patch.object(p,'update',side_effect=update):
                actual=p.solve(least_squares,'test',lambda x:x*x-2,[4.],max_nfev=20)
            expected=least_squares(lambda x:x*x-2,[4.],max_nfev=20)
            np.testing.assert_array_equal(actual.x,expected.x)
            self.assertEqual(actual.nfev,expected.nfev)
            self.assertTrue(any(x['iteration']>0 for x in snapshots))
            self.assertEqual(read_progress(path)['evaluations'],actual.nfev)
            self.assertEqual(read_progress(path)['round'],1)
            self.assertFalse(path.with_suffix('.tmp').exists())
            trace_path=path.with_suffix('.jsonl')
            trace=read_trace(trace_path,0)
            events=trace['events']
            self.assertGreater(len(events),1)
            self.assertTrue(all(event['solver']=='CPU least_squares' for event in events))
            self.assertEqual(events[-1]['current'],actual.cost)
            self.assertTrue(all(a['best']>=b['best'] for a,b in zip(events,events[1:])))
            p.solve(least_squares,'second',lambda x:x-1,[3.],max_nfev=1)
            self.assertEqual(read_progress(path)['round'],2)
            self.assertEqual(read_progress(path)['evaluations'],1)
            newer=read_trace(trace_path,trace['offset'])
            self.assertEqual([event['stage'] for event in newer['events']],['second'])
            self.assertEqual(newer['events'][0]['best'],2.0)
            with trace_path.open('ab') as stream:
                stream.write(b'{"kind":')
            self.assertEqual(read_trace(trace_path,newer['offset']),dict(offset=newer['offset'],events=[]))
            self.assertIsNone(read_progress(Path(t)/'missing.json'))

    def test_compression_reports_all_real_candidate_rounds(self):
        from grid_distillation import compress
        base=np.array([[.1,.2,.3],[.6,.5,.4]])
        events=[]
        grid,audit=compress(base,np.ones(2),lambda rgb:rgb,np.eye(3),probe_side=3,sweeps=0,progress=lambda **v:events.append(v))
        self.assertEqual([v['round']for v in events],[1,2,3])
        self.assertTrue(all(v['total_rounds']==3 for v in events))
        self.assertEqual(len(audit['candidates']),3)
        np.testing.assert_array_equal(grid,np.zeros((405,3)))

    def test_grid_loss_can_start_before_any_solver_iteration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'grid_progress.json'
            tracker=TrainingProgress(path,3)
            tracker.update(stage='浮点网格',round=1,loss_sample=('MPS FISTA',0,.25,.25))
            tracker.update(stage='整数网格',integer_round=dict(sweep=1,applied_moves=3))
            loss, integer=read_trace(path.with_suffix('.jsonl'),0)['events']
            self.assertEqual((loss['kind'],loss['iteration'],loss['current']),('loss',None,.25))
            self.assertEqual((integer['kind'],integer['applied_moves']),('integer',3))
