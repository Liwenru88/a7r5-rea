import unittest,json,struct,copy,sys
from pathlib import Path
import numpy as np
from html.parser import HTMLParser
import core,anchor_dataset,sector16,tonal_sampling
from edit_parameter_context import RuntimeColor

class PortableTests(unittest.TestCase):
    def test_defaults_and_v4_grid_export(self):
        html=(core.HERE/'static/index.html').read_text()
        class Controls(HTMLParser):
            def __init__(self):super().__init__();self.inputs={}
            def handle_starttag(self,tag,attrs):
                values=dict(attrs)
                if tag=='input' and 'id' in values:self.inputs[values['id']]=values
        controls=Controls();controls.feed(html)
        self.assertEqual(controls.inputs['wbTraining']['type'],'checkbox')
        self.assertNotIn('checked',controls.inputs['wbTraining'])
        self.assertIn('checked',controls.inputs['pcTraining'])
        entries,_=core.presets();self.assertEqual(len(entries),12)
        cfg=core.config(entries[:1]);cfg['schema']='r5-custom-filter-config/4'
        grid=np.zeros((3,5,9,9),dtype=int);grid[0,0,0,0]=-64;grid[2,4,8,8]=63
        cfg['entries'][0]['grid_5x9x9']=dict(coefficients=grid.tolist())
        blob,_,fw,v=core.compile_config(cfg)
        self.assertEqual((len(blob),fw,v),(2580,'4.23',4))
        self.assertEqual(blob[:8],b'R5CUST4\0')
        self.assertEqual(blob[128+1232:128+2447],grid.astype('i1').tobytes())
    def test_no_external_symbolic_links_or_machine_paths(self):
        root=core.ROOT
        for directory in ['web','scripts','compilers','data']:
            for p in (root/directory).rglob('*'):
                self.assertFalse(p.is_symlink(),str(p))
                if p.suffix=='.py':
                    source=p.read_text()
                    self.assertNotIn('/Users/',source)
                    # 可选 SpektraLab 素材工具显式依赖该外部软件，不是工作台启动依赖。
                    if p.relative_to(root).as_posix()!='scripts/generate_spektralab_targets.py':
                        self.assertNotIn('/Applications/',source)
