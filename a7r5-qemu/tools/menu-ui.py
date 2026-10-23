#!/usr/bin/env python3
"""Mac 回环图形窗口：显示已校验原厂帧，只向本次 VM 发送固定导航键。"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LAB=Path(__file__).resolve().parent.parent
KEYS=('UP','DOWN','LEFT','RIGHT','ENTER','MENU')
HTML='''<!doctype html><meta charset="utf-8"><title>A7R5 原厂菜单 · QEMU</title>
<style>body{background:#17191c;color:#eceff4;font:16px system-ui;margin:24px auto;max-width:880px}h1{font-size:24px}main{display:flex;gap:22px;align-items:center}img{width:640px;max-width:100%;background:#000;border:1px solid #454a52}nav{display:grid;gap:10px}button{padding:12px 18px;border-radius:8px;background:#303640;border:1px solid #626b7b;color:white;font-size:16px;cursor:pointer}button:disabled{opacity:.35;cursor:wait}p{color:#b7beca;line-height:1.6}#status{min-height:48px}small{color:#a4abb6}@media(max-width:850px){main{display:block}nav{display:flex;flex-wrap:wrap;margin-top:16px}}</style>
<h1>A7R5 4.00 原厂菜单</h1><p>__RUNTIME__ · 原厂应用与资源 · AP 软件绘图 640 × 480</p>
<main><img id="frame" alt="本次原厂菜单帧"><nav>
<button data-key="UP">↑ 上</button><button data-key="DOWN">↓ 下</button>
<button data-key="LEFT">← 左</button><button data-key="RIGHT">→ 右</button>
<button data-key="ENTER">确认</button><button data-key="MENU">MENU / 返回</button>
<button id="stop">退出虚拟器</button></nav></main>
<p id="status">启动中，等待原厂菜单初始化……</p><small>方向键、Enter、Escape 对应以上按键。处理期间暂停新输入；每次操作后读取并校验新帧。菜单设置仅存在于本次虚拟机 RAM。拍摄、取景及完整 CP 硬件尚未模拟。</small>
<script>
const token='__TOKEN__';let busy=false,last=0,state='starting';const buttons=[...document.querySelectorAll('button')];
async function update(){try{let r=await fetch('/status'),s=await r.json();state=s.state;buttons.forEach(b=>b.disabled=busy||state!=='running');
document.querySelector('#status').textContent=({starting:'启动中，等待原厂菜单初始化……',running:busy?'正在处理本次输入……':'菜单可操作',busy:'原厂菜单正在处理按键并校验画面……',stopping:'正在退出本次虚拟器……',stopped:'虚拟器已退出；画面为最后一次已校验快照',failed:'已停止：'+(s.error||'请查看本次日志')})[state]||state;
if(s.sequence&&s.sequence!==last){last=s.sequence;document.querySelector('#frame').src='/frame.png?v='+last;}}
catch(e){document.querySelector('#status').textContent='本机控制入口已断开';buttons.forEach(b=>b.disabled=true);}}
async function send(action,key=null){if(busy||state!=='running')return;busy=true;update();try{const r=await fetch('/command',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({action,key})});if(!r.ok){let e=await r.json();document.querySelector('#status').textContent=e.error;}}finally{busy=false;await update();}}
buttons.filter(b=>b.dataset.key).forEach(b=>b.onclick=()=>send('key',b.dataset.key));document.querySelector('#stop').onclick=()=>send('stop');
document.addEventListener('keydown',e=>{if(e.repeat)return;let k={ArrowUp:'UP',ArrowDown:'DOWN',ArrowLeft:'LEFT',ArrowRight:'RIGHT',Enter:'ENTER',Escape:'MENU'}[e.key];if(k){e.preventDefault();send('key',k);}});update();setInterval(update,1000);
</script>'''


from emu_session import EmulatorSession as Session


def create_server(session):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,code,data,kind='application/json'):
            if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(code);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','DENY');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(data)
        def valid_host(self):
            return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
        def do_GET(self):
            if not self.valid_host():return self.respond(403,{'error':'Host 不符'})
            path=self.path.split('?',1)[0]
            if path=='/':return self.respond(200,HTML.replace('__TOKEN__',token).replace('__RUNTIME__','macOS 原生 QEMU').encode(),'text/html; charset=utf-8')
            if path=='/status':return self.respond(200,session.status())
            if path=='/frame.png':
                p=session.bridge/'frame.png'
                if p.exists():return self.respond(200,p.read_bytes(),'image/png')
            self.respond(404,{'error':'不存在'})
        def do_POST(self):
            origin=f'http://127.0.0.1:{self.server.server_port}'
            if not self.valid_host() or self.headers.get('Origin')!=origin or not secrets.compare_digest(self.headers.get('X-Session-Token',''),token):
                return self.respond(403,{'error':'本次会话校验失败'})
            if self.path!='/command':return self.respond(404,{'error':'不存在'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=128 or self.headers.get('Content-Type')!='application/json':
                    raise ValueError('请求长度或类型不符')
                result=session.command(json.loads(self.rfile.read(size)))
                self.respond(200,result)
            except (ValueError,TypeError):self.respond(400,{'error':'请求内容不符'})
            except BlockingIOError:self.respond(409,{'error':'尚未就绪或有操作正在执行'})
            except (RuntimeError,TimeoutError,FileExistsError):self.respond(503,{'error':'操作未完成，请查看本次日志；没有自动重试'})
    return ThreadingHTTPServer(('127.0.0.1',0),Handler)


def main():
    p=argparse.ArgumentParser();p.add_argument('--no-open',action='store_true');a=p.parse_args()
    s=Session();server=create_server(s)
    url=f'http://127.0.0.1:{server.server_port}'
    (s.bridge/'url.txt').write_text(url+'\n')
    print(json.dumps({'url':url,'bridge':str(s.bridge)},ensure_ascii=False),flush=True)
    if not a.no_open:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        try:s.close()
        finally:server.server_close()



if __name__=='__main__':main()
