"""固定导航控制面板；候选事件不会直接进入输入层。"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QGridLayout, QPushButton, QVBoxLayout, QTabWidget,
                               QScrollArea, QLabel, QHBoxLayout, QComboBox)
from input_registry import InputRegistry
from control_actions import DIALS,ACTION_SPECS,MODES


class ControlPanel(QWidget):
    activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.registry = InputRegistry.load()
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        navigation = QWidget()
        tabs.addTab(navigation, '菜单导航')
        layout = QGridLayout(navigation)
        self.buttons = {}
        self.action_buttons = {}
        for key, label, row, col in (
            ('UP', '↑ 上', 0, 1), ('LEFT', '← 左', 1, 0), ('ENTER', '确认', 1, 1),
            ('RIGHT', '右 →', 1, 2), ('DOWN', '↓ 下', 2, 1), ('MENU', 'MENU / 返回', 3, 0)):
            button = QPushButton(label)
            button.setObjectName('control_' + key)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False, key=key: self.activated.emit(key))
            layout.addWidget(button, row, col, 1, 3 if key == 'MENU' else 1)
            self.buttons[key] = button
            self.action_buttons[key] = button
        for col,(key,label) in enumerate((('FN','Fn 快捷菜单'),('DISP','DISP 显示'),('PLAYBACK','回放'))):
            button=QPushButton(label)
            button.setObjectName('control_'+key)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda checked=False,key=key:self.activated.emit(key))
            layout.addWidget(button,4,col)
            self.buttons[key]=button
            self.action_buttons[key]=button
        for col,key in enumerate(('C1','C2','C3')):
            button=QPushButton(key+' 自定义键');button.setObjectName('control_'+key)
            button.setMinimumHeight(36);button.setToolTip(self.registry.controls[key]['limitations'])
            button.clicked.connect(lambda checked=False,key=key:self.activated.emit(key))
            layout.addWidget(button,5,col);self.buttons[key]=button;self.action_buttons[key]=button
        self.mode_label=QLabel('虚拟模式拨盘 · 需完成首次设置')
        layout.addWidget(self.mode_label,6,0,1,3)
        self.mode_select=QComboBox()
        for mode in MODES:self.mode_select.addItem('自动' if mode=='AUTO' else mode,mode)
        self.mode_button=QPushButton('切换模式')
        self.mode_button.setObjectName('control_MODE_DIAL')
        self.mode_button.clicked.connect(lambda:self.activated.emit('MODE_'+self.mode_select.currentData()))
        layout.addWidget(self.mode_select,7,0);layout.addWidget(self.mode_button,7,1,1,2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        physical = QWidget()
        items = QVBoxLayout(physical)
        self.physical_buttons = {}
        group = None
        for row in self.registry.controls.values():
            if row['id'] in self.buttons or row['id']=='MODE_DIAL':
                continue
            if row['group'] != group:
                group = row['group']
                label = QLabel(group)
                label.setStyleSheet('font-weight:600;padding-top:10px')
                items.addWidget(label)
            if row['id']=='JOYSTICK':
                items.addWidget(QLabel('摇杆 · 菜单五向'))
                pad=QWidget();grid=QGridLayout(pad)
                for direction,label,r,c in (('UP','↑',0,1),('LEFT','←',1,0),('CENTER','中心',1,1),('RIGHT','→',1,2),('DOWN','↓',2,1)):
                    action='JOYSTICK_'+direction;button=QPushButton(label)
                    button.setObjectName('control_'+action);button.setEnabled(False)
                    button.clicked.connect(lambda checked=False,action=action:self.activated.emit(action))
                    grid.addWidget(button,r,c);self.action_buttons[action]=button
                    if direction=='CENTER':self.physical_buttons[row['id']]=button
                items.addWidget(pad)
            elif row['id'] in DIALS:
                items.addWidget(QLabel(row['label']+' · 每次一格'))
                directions=QHBoxLayout()
                for suffix,label in (('LEFT','↶ 反向'),('RIGHT','↷ 正向')):
                    action=row['id']+'_'+suffix
                    button=QPushButton(label);button.setObjectName('control_'+action)
                    button.setEnabled(False);button.setToolTip(row['limitations'])
                    button.clicked.connect(lambda checked=False,action=action:self.activated.emit(action))
                    directions.addWidget(button);self.action_buttons[action]=button
                items.addLayout(directions)
            else:
                suffix=' · 待实现' if row['behavior_status']!='pass' else ''
                button = QPushButton(row['label']+suffix)
                button.setObjectName('control_'+row['id'])
                button.setEnabled(False)
                button.setToolTip(row['limitations'])
                button.clicked.connect(lambda checked=False, control=row['id']: self.activated.emit(control))
                items.addWidget(button)
                if row['id'] in ACTION_SPECS:self.action_buttons[row['id']]=button
            explanation = QLabel(row['limitations'])
            explanation.setWordWrap(True)
            explanation.setStyleSheet('font-size:11px;color:#888')
            items.addWidget(explanation)
            if row['id'] not in self.physical_buttons:self.physical_buttons[row['id']] = button
        items.addStretch()
        scroll.setWidget(physical)
        tabs.addTab(scroll, '全部机身控制')
        self.setMinimumWidth(300)

    def set_available(self, available, context='menu', mode=None):
        mode_ready=available and self.registry.available('MODE_DIAL',context) and mode in MODES
        self.mode_button.setEnabled(mode_ready);self.mode_select.setEnabled(mode_ready)
        self.mode_label.setText('虚拟模式拨盘 · 当前 '+('自动' if mode=='AUTO' else mode) if mode_ready else '虚拟模式拨盘 · 需拍摄信息页显示模式标志')
        for key, button in self.buttons.items():
            button.setEnabled(available and self.registry.available(key, context))
        for key, button in self.physical_buttons.items():
            if key not in DIALS:button.setEnabled(available and self.registry.available(key, context))
            if key=='C4':
                button.setText('C4 · 在相机上设置' if context=='setup_on_camera' else 'C4 · 触摸操作开关' if context=='shooting_ready' else 'C4 / 删除 · 菜单帮助')
        for action,button in self.action_buttons.items():
            control=ACTION_SPECS[action][0]
            button.setEnabled(available and self.registry.available(control,context))
