import sys
import json
import os
import subprocess
import time
import socket
import concurrent.futures
import atexit
import winreg
import threading
import statistics
import urllib.request
from pathlib import Path
from datetime import datetime

# ==================== 0. 路径与环境 ====================
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_app_path():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.absolute()

APP_ROOT = get_app_path()
CONFIG_FILE = APP_ROOT / "config.json"
ICON_PATH = resource_path("icon.ico")
CORE_EXE_NAME = "ech-workers.exe"
CORE_PATH = APP_ROOT / CORE_EXE_NAME

# ==================== 1. 依赖库 ====================
try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                  QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                                  QComboBox, QTextEdit, QPlainTextEdit, QFrame, QGridLayout, 
                                  QSystemTrayIcon, QMenu, QStackedWidget, 
                                  QInputDialog, QMessageBox, QSizePolicy, QListView,
                                  QCheckBox)
    from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QTimer, QPoint, QSize, QObject)
    from PyQt5.QtGui import (QColor, QFont, QPainter, QBrush, QPen, QRadialGradient, QIcon)
except ImportError:
    sys.exit(1)

# ==================== 2. 全局配置 ====================
APP_TITLE = "ECH Client"
VER = "v0.15.5"

PALETTE = {
    "bg_app": "#f8fafc", "bg_sidebar": "#ffffff", "text_dark": "#1e293b", 
    "text_gray": "#64748b", "primary": "#6366f1", "primary_hover": "#4f46e5",
    "success": "#10b981", "danger": "#ef4444", "input_bg": "#ffffff", 
    "border": "#cbd5e1", "btn_bg": "#f1f5f9"
}

# ==================== 3. 进程管理 ====================
class ProcessManager:
    _current_proc = None
    _lock = threading.Lock()

    @staticmethod
    def start_process(cmd):
        with ProcessManager._lock:
            ProcessManager._kill_unsafe()
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW if sys.platform=='win32' else 0
                ProcessManager._current_proc = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    startupinfo=si, 
                    bufsize=0,
                    creationflags=0x08000000 if sys.platform=='win32' else 0
                )
                return ProcessManager._current_proc
            except Exception: return None

    @staticmethod
    def kill_current():
        with ProcessManager._lock:
            ProcessManager._kill_unsafe()

    @staticmethod
    def _kill_unsafe():
        p = ProcessManager._current_proc
        if p:
            try: p.terminate()
            except: pass
            if sys.platform == 'win32' and p.pid:
                try: subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], 
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
                except: pass
            try: p.kill()
            except: pass
            ProcessManager._current_proc = None

atexit.register(ProcessManager.kill_current)

# ==================== 4. 注册表/自启 ====================
class AutoStartManager:
    KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_KEY = "ECHWorkersClient"
    @staticmethod
    def get_command():
        if getattr(sys, 'frozen', False): return f'"{sys.executable}" -autostart'
        return f'"{sys.executable}" "{__file__}" -autostart'
    @staticmethod
    def set_autostart(enable=True):
        if sys.platform != 'win32': return
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoStartManager.KEY_PATH, 0, winreg.KEY_SET_VALUE)
            if enable: winreg.SetValueEx(key, AutoStartManager.APP_KEY, 0, winreg.REG_SZ, AutoStartManager.get_command())
            else: 
                try: winreg.DeleteValue(key, AutoStartManager.APP_KEY)
                except: pass
            winreg.CloseKey(key)
        except: pass
    @staticmethod
    def check_status():
        if sys.platform != 'win32': return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AutoStartManager.KEY_PATH, 0, winreg.KEY_READ)
            val, _ = winreg.QueryValueEx(key, AutoStartManager.APP_KEY)
            winreg.CloseKey(key); return True if val else False
        except: return False

# ==================== 5. 核心算法 ====================
class SmartSelector:
    @staticmethod
    def tcp_ping(target, port=443, timeout=1.0):
        s = None
        try:
            real_host = target
            real_port = port
            
            # 支持 IP:Port 或 Domain:Port 格式解析
            if ":" in target:
                parts = target.rsplit(":", 1)
                # 简单的 IPv4/域名 端口分离
                if len(parts) == 2 and parts[1].isdigit():
                    real_host = parts[0].strip("[]")
                    real_port = int(parts[1])
            
            ip = socket.gethostbyname(real_host)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            t0 = time.perf_counter()
            s.connect((ip, real_port))
            lat = (time.perf_counter() - t0) * 1000
            return (target, lat)
        except: 
            return (target, 99999)
        finally:
            if s: s.close()

    @staticmethod
    def pick_best(ip_text, callback_msg=None):
        raw = [l.strip() for l in ip_text.split('\n') if l.strip() and not l.strip().startswith("#")]
        if not raw: return None, 0
        if len(raw) == 1: return SmartSelector.tcp_ping(raw[0], 443, 2.0)

        if callback_msg: callback_msg.emit("正在测速...")
        candidates = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(raw), 64)) as ex:
            f_map = {ex.submit(SmartSelector.tcp_ping, ip, 443, 1.0): ip for ip in raw}
            for f in concurrent.futures.as_completed(f_map):
                try:
                    ip, lat = f.result()
                    if lat < 5000: candidates.append((ip, lat))
                except: pass
        
        if not candidates: return raw[0], 0 
        candidates.sort(key=lambda x: x[1])
        top = candidates[:5]
        if top[0][1] < 15: return top[0]

        if callback_msg: callback_msg.emit("复测稳定性...")
        scored = []
        for ip, first_lat in top:
            samples = [first_lat]
            for _ in range(3):
                _, l = SmartSelector.tcp_ping(ip, 443, 1.5)
                if l < 5000: samples.append(l)
                time.sleep(0.05)
            if not samples: continue
            avg = statistics.mean(samples)
            jit = statistics.stdev(samples) if len(samples) > 1 else 0
            scored.append((ip, avg, avg + jit * 1.5))
        
        scored.sort(key=lambda x: x[2])
        return (scored[0][0], scored[0][1]) if scored else top[0]

# ==================== 6. 配置管理 ====================
class ConfigManager:
    def __init__(self):
        self.data = {"servers": [], "current": None}; self.load()
    def load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f: self.data.update(json.load(f))
            if not self.data.get('servers'): self.add_default(); return
            dirty = False
            for s in self.data['servers']:
                if 'id' not in s: import uuid; s['id'] = str(uuid.uuid4()); dirty = True
                if 'auto_best' not in s: s['auto_best'] = True; dirty = True
            if not self.data.get('current') and self.data['servers']: self.data['current'] = self.data['servers'][0]['id']; dirty = True
            if dirty: self.save()
        except: self.add_default()
    def save(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(self.data, f, indent=2, ensure_ascii=False)
        except: pass
    def add_default(self):
        import uuid; uid = str(uuid.uuid4())
        self.data['servers'] = [{"id": uid, "name": "默认配置", "server": "", "listen": "127.0.0.1:30000", "token": "", "ip_list": "", "routing": "bypass_cn", "auto_best": True}]
        self.data['current'] = uid; self.save()
    def get_cur(self):
        for s in self.data['servers']: 
            if s['id'] == self.data['current']: return s
        if self.data['servers']: self.data['current'] = self.data['servers'][0]['id']; return self.data['servers'][0]
        return {}
    def update_cur(self, val):
        for i, s in enumerate(self.data['servers']):
            if s['id'] == val['id']: self.data['servers'][i] = val
        self.save()
    def add_new(self, name):
        import uuid; new = self.get_cur().copy(); new['id'] = str(uuid.uuid4()); new['name'] = name
        self.data['servers'].append(new); self.data['current'] = new['id']; self.save()
    def del_cur(self):
        if len(self.data['servers']) <= 1: return
        self.data['servers'] = [s for s in self.data['servers'] if s['id'] != self.data['current']]
        self.data['current'] = self.data['servers'][0]['id']; self.save()
    def rename_cur(self, n): s = self.get_cur(); s['name'] = n; self.update_cur(s)

class SingleInstance(QObject):
    signal_wake_up = pyqtSignal()
    def __init__(self, port=56789):
        super().__init__(); self.port = port; self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); self.running = False
    def check(self):
        try: self.sock.bind(('127.0.0.1', self.port)); self.sock.listen(1); self.running = True; threading.Thread(target=self._listen_loop, daemon=True).start(); return True
        except: self._notify_existing(); return False
    def _notify_existing(self):
        try: c = socket.socket(socket.AF_INET, socket.SOCK_STREAM); c.settimeout(1); c.connect(('127.0.0.1', self.port)); c.send(b'WAKE'); c.close()
        except: pass
    def _listen_loop(self):
        while self.running:
            try: c, _ = self.sock.accept(); d = c.recv(1024); c.close()
            except: break
            if d == b'WAKE': self.signal_wake_up.emit()
        self.sock.close()

# ==================== 7. 工作线程 ====================
class WorkerThread(QThread):
    msg = pyqtSignal(str, str); status_change = pyqtSignal(str); latency_result = pyqtSignal(str); geo_result = pyqtSignal(str)
    error_alert = pyqtSignal(str); finished_safe = pyqtSignal()
    
    def __init__(self, cfg): super().__init__(); self.cfg = cfg; self.running = False
    
    def run(self):
        self.running = True
        if not CORE_PATH.exists(): 
            self.msg.emit(f"❌ 核心缺失: {CORE_EXE_NAME}", "#ef4444")
            self.error_alert.emit("核心文件丢失"); self.finished_safe.emit(); return
        
        listen_addr = self.cfg.get('listen', '127.0.0.1:30000')
        if ':' in listen_addr:
             try:
                 p = int(listen_addr.split(':')[-1]); s = socket.socket(); 
                 if s.connect_ex(('127.0.0.1', p)) == 0: ProcessManager.kill_current()
                 s.close()
             except: pass
        
        ip_list = self.cfg.get('ip_list', ''); sel_ip = None
        use_auto = self.cfg.get('auto_best', True)

        if ip_list.strip():
            if use_auto:
                self.status_change.emit("...")
                best_ip, lat = SmartSelector.pick_best(ip_list, self.status_change)
                if best_ip:
                    self.msg.emit(f"✅ 优选结果: {best_ip} (Lat: {lat:.1f}ms)", "#10b981")
                    self.latency_result.emit(f"{int(lat)}ms | {best_ip}"); sel_ip = best_ip
                else: 
                    self.latency_result.emit("优选失败")
            else:
                raw = [l.strip() for l in ip_list.split('\n') if l.strip() and not l.strip().startswith("#")]
                if raw:
                    sel_ip = raw[0]
                    self.msg.emit(f"🔒 使用固定 IP: {sel_ip}", "#6366f1")
                    self.latency_result.emit(f"固定 | {sel_ip}")
                else:
                    self.latency_result.emit("列表为空")
        else: 
            self.latency_result.emit("直连模式 (Direct)")
        
        cmd = [str(CORE_PATH)]
        keys = {'-f':'server', '-l':'listen', '-token':'token', '-routing':'routing'}
        for f, k in keys.items():
            if v := self.cfg.get(k): cmd.extend([f, str(v).strip()])
        
        # [修改] 关键修正：不再剥离端口
        # 因为新的 Go 核心代码已经更新，可以正确处理 IP:Port 格式
        # 直接将用户优选出来的结果 (如 47.76.60.217:7548) 传给核心
        if sel_ip:
            cmd.extend(['-ip', sel_ip])
        
        self.status_change.emit("运行中")
        try:
            self.p = ProcessManager.start_process(cmd)
            if self.p:
                threading.Thread(target=self.check_geoip, args=(listen_addr,), daemon=True).start()
                while self.running:
                    try:
                        l = self.p.stdout.readline()
                        if not l: break
                        t = l.decode('utf-8', 'replace').strip()
                        if t: 
                            if "connected" in t.lower(): self.msg.emit(t, "#10b981")
                            elif "error" in t.lower() or "panic" in t.lower(): self.msg.emit(t, "#ef4444")
                            else: self.msg.emit(t, "#94a3b8")
                    except: break
            else: self.error_alert.emit("启动失败")
        except Exception as e: self.msg.emit(str(e), "#ef4444")
        self.running = False; self.finished_safe.emit()

    def check_geoip(self, listen_addr):
        time.sleep(5) 
        if not self.running: return

        proxy_url = f"http://{listen_addr}" if "://" not in listen_addr else listen_addr
        if "127.0.0.1" not in proxy_url and "localhost" not in proxy_url: proxy_url = "http://127.0.0.1:30000"
        
        proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]

        results = {}
        
        def fetch(url, name, parser_func):
            try:
                with opener.open(url, timeout=15) as res:
                    data = json.loads(res.read().decode())
                    results[name] = parser_func(data)
            except Exception as e:
                results[name] = "超时/失败"

        def parse_ipsb(d): return f"{d.get('country_code','')} {d.get('ip','')}"
        def parse_ipip(d): return f"{''.join(d.get('data',{}).get('location',[]))} {d.get('data',{}).get('ip','')}"
        def parse_ipinfo(d): return f"{d.get('country','')} {d.get('org','')} {d.get('ip','')}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            executor.submit(fetch, "https://api.ip.sb/geoip", "IP.SB", parse_ipsb)
            executor.submit(fetch, "https://myip.ipip.net/json", "IPIP", parse_ipip)
            executor.submit(fetch, "https://ipinfo.io/json", "IPINFO", parse_ipinfo)
        
        final_text = (
            f"IPIP: {results.get('IPIP', '--')}\n"
            f"IPSB: {results.get('IP.SB', '--')}\n"
            f"INFO: {results.get('IPINFO', '--')}"
        )
        
        self.geo_result.emit(final_text)
        self.msg.emit(f"🌍 多源检测完成:\n{final_text}", "#3b82f6")

    def stop(self): self.running = False; ProcessManager.kill_current()

# ==================== 8. UI 组件 ====================
class SidebarItem(QPushButton):
    def __init__(self, text, icon_text, parent=None):
        super().__init__(parent); self.setCheckable(True); self.setFixedHeight(45); self.setCursor(Qt.PointingHandCursor)
        self.setText(f" {icon_text}   {text}"); self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(f"""
            QPushButton {{ text-align: left; padding-left: 20px; border: none; border-radius: 6px; color: {PALETTE['text_gray']}; background: transparent; }}
            QPushButton:hover {{ background: #f1f5f9; color: {PALETTE['primary']}; }}
            QPushButton:checked {{ background: #e0e7ff; color: {PALETTE['primary']}; font-weight: bold; }}
        """)

class ToggleButton(QPushButton):
    def __init__(self, text_prefix, parent=None):
        super().__init__(parent); self.text_prefix = text_prefix; self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor); self.setMinimumHeight(45); self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.update_text(); self.clicked.connect(self.update_text); self.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.setStyleSheet(f"""
            QPushButton {{ background-color: {PALETTE['btn_bg']}; border: 1px solid {PALETTE['border']}; border-radius: 6px; color: {PALETTE['text_dark']}; padding: 5px 15px; margin: 2px; }}
            QPushButton:hover {{ border-color: {PALETTE['primary']}; }}
            QPushButton:checked {{ background-color: {PALETTE['primary']}; color: white; border-color: {PALETTE['primary']}; }}
            QPushButton:disabled {{ background-color: #f1f5f9; color: #cbd5e1; border-color: #e2e8f0; }}
        """)
    def update_text(self): self.setText(f"{self.text_prefix}: {'已开启' if self.isChecked() else '已关闭'}")

class BigPowerButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedSize(130, 130); self.setCursor(Qt.PointingHandCursor)
        self.active = False; self.hover = False; self.pulse = 0; self.pulse_dir = 1
        self.timer = QTimer(self); self.timer.timeout.connect(self.update)
    def set_active(self, val): self.active = val; self.timer.start(40) if val else self.timer.stop(); self.update()
    def enterEvent(self, e): self.hover = True; self.update()
    def leaveEvent(self, e): self.hover = False; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled(): base = QColor("#e2e8f0"); icon_c = QColor("#cbd5e1"); glow = False
        else:
            base = QColor(PALETTE['success']) if self.active else QColor(PALETTE['primary']) if self.hover else QColor("#e2e8f0")
            icon_c = QColor("white") if (self.active or self.hover) else QColor("#94a3b8")
            glow = self.active or self.hover
            if self.active: self.pulse += 2*self.pulse_dir
            if self.pulse>60 or self.pulse<0: self.pulse_dir *= -1
        if glow and self.isEnabled():
            grad = QRadialGradient(65,65,65); c=QColor(base); c.setAlpha(40+self.pulse if self.active else 30)
            grad.setColorAt(0.5,c); grad.setColorAt(1,Qt.transparent); p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen); p.drawEllipse(0,0,130,130)
        p.setBrush(base); p.drawEllipse(QPoint(65,65),50,50)
        pen = QPen(icon_c, 4, Qt.SolidLine, Qt.RoundCap); p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawArc(45,45,40,40,135*16,270*16); p.drawLine(65,38,65,65)

# ==================== 9. 主窗口 ====================
class UltraWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.cfg = ConfigManager(); self.worker = None
        self.resize(920, 620); self.setMinimumSize(850, 550); self.setWindowTitle(f"{APP_TITLE} {VER}")
        if os.path.exists(ICON_PATH): self.setWindowIcon(QIcon(ICON_PATH))
        self.init_ui(); self.load_data(); self.init_tray()
        if '-autostart' in sys.argv: self.hide(); self.toggle_run()
        else: self.show()
        
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {PALETTE['bg_app']}; }}
            QLineEdit {{ background: {PALETTE['input_bg']}; border: 1px solid {PALETTE['border']}; border-radius: 6px; padding: 0 10px; color: {PALETTE['text_dark']}; font-family: "Segoe UI"; }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['primary']}; }}
            QComboBox {{ background: {PALETTE['input_bg']}; border: 1px solid {PALETTE['border']}; border-radius: 6px; padding: 5px 10px; color: {PALETTE['text_dark']}; font-family: "Segoe UI"; min-width: 150px; }}
            QComboBox:hover {{ border: 1px solid #94a3b8; background: #fff; }}
            QComboBox:focus {{ border: 1px solid {PALETTE['primary']}; }}
            QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left-width: 0px; }}
            QComboBox::down-arrow {{ image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid {PALETTE['text_gray']}; margin-top: 2px; margin-right: 2px; }}
            QComboBox QAbstractItemView {{ border: 1px solid {PALETTE['primary']}; background: white; outline: none; padding: 5px; }}
            QComboBox QAbstractItemView::item {{ height: 32px; border-radius: 4px; margin-bottom: 2px; color: {PALETTE['text_dark']}; }}
            QComboBox QAbstractItemView::item:hover {{ background-color: #f1f5f9; color: {PALETTE['text_dark']}; }}
            QComboBox QAbstractItemView::item:selected {{ background-color: {PALETTE['primary']}; color: #ffffff; }}
            QScrollBar:vertical {{ border: none; background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: #cbd5e1; min-height: 20px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QCheckBox {{ color: {PALETTE['text_dark']}; spacing: 5px; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {PALETTE['border']}; border-radius: 4px; background: white; }}
            QCheckBox::indicator:checked {{ background: {PALETTE['primary']}; border-color: {PALETTE['primary']}; image: url(none); }}
            /* 修复 QTextEdit 样式为 QPlainTextEdit */
            QPlainTextEdit {{ background: {PALETTE['input_bg']}; border: 1px solid {PALETTE['border']}; border-radius: 6px; padding: 10px; color: {PALETTE['text_dark']}; font-family: Consolas, monospace; }}
            QPlainTextEdit:focus {{ border: 1px solid {PALETTE['primary']}; }}
        """)

    def init_ui(self):
        main = QWidget(); self.setCentralWidget(main); ml = QHBoxLayout(main); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        sb = QFrame(); sb.setFixedWidth(200); sb.setStyleSheet(f"background:{PALETTE['bg_sidebar']}; border-right: 1px solid {PALETTE['border']};")
        sl = QVBoxLayout(sb); sl.setContentsMargins(10, 25, 10, 20); sl.setSpacing(5)
        logo = QLabel(APP_TITLE); logo.setFont(QFont("Segoe UI", 15, QFont.Bold)); logo.setAlignment(Qt.AlignCenter); logo.setStyleSheet(f"color:{PALETTE['primary']}; margin-bottom: 20px;")
        sl.addWidget(logo)
        self.btns = []
        for i, (txt, ico) in enumerate([("运行状态","⚡"), ("配置管理","⚙️"), ("运行日志","📝")]):
            b = SidebarItem(txt, ico); b.clicked.connect(lambda _,x=i: self.switch_page(x))
            sl.addWidget(b); self.btns.append(b)
        sl.addStretch(); ml.addWidget(sb)
        self.pages = QStackedWidget(); ml.addWidget(self.pages); self.btns[0].setChecked(True)
        self.pages.addWidget(self.create_dash_page())
        self.pages.addWidget(self.create_conf_page())
        self.pages.addWidget(self.create_logs_page())

    def create_dash_page(self):
        p = QWidget(); l = QVBoxLayout(p); l.setAlignment(Qt.AlignCenter); l.setSpacing(25)
        
        # [修改] 增大字体
        self.lbl_st = QLabel("准备就绪"); self.lbl_st.setFont(QFont("Segoe UI", 28, QFont.Bold)); self.lbl_st.setStyleSheet(f"color:{PALETTE['text_gray']}")
        
        meta_layout = QVBoxLayout(); meta_layout.setSpacing(10)
        self.lbl_lat = QLabel(""); self.lbl_lat.setAlignment(Qt.AlignCenter); self.lbl_lat.setStyleSheet(f"color:{PALETTE['primary']}; font-weight: bold; font-size: 18px;")
        
        # [修改] 优化 Geo 显示区域，字体加大
        self.lbl_geo = QLabel("--"); 
        self.lbl_geo.setAlignment(Qt.AlignCenter); 
        self.lbl_geo.setStyleSheet(f"color:{PALETTE['text_gray']}; font-size: 13px; font-family: Consolas, monospace; line-height: 1.4;")
        self.lbl_geo.setWordWrap(True)
        
        meta_layout.addWidget(self.lbl_lat); meta_layout.addWidget(self.lbl_geo)

        self.btn_pow = BigPowerButton(); self.btn_pow.clicked.connect(self.toggle_run)
        info = QFrame(); info.setMinimumWidth(380); info.setMaximumWidth(520); info.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        info.setStyleSheet(f"background:white; border-radius:12px; border:1px solid {PALETTE['border']}; padding: 25px;")
        il = QVBoxLayout(info); il.setSpacing(15)
        h1 = QHBoxLayout(); h1.addWidget(QLabel("当前方案:", styleSheet=f"color:{PALETTE['text_gray']}; font-size:14px;")); 
        self.lbl_cur = QLabel("--"); self.lbl_cur.setStyleSheet("font-weight:bold; color:#1e293b; font-size:16px;"); h1.addWidget(self.lbl_cur); h1.addStretch()
        h_btns = QHBoxLayout(); h_btns.setSpacing(15)
        self.btn_sys = ToggleButton("系统代理"); self.btn_sys.clicked.connect(self.toggle_sys); self.btn_sys.setEnabled(False)
        self.btn_auto = ToggleButton("开机自启"); self.btn_auto.setChecked(AutoStartManager.check_status()); self.btn_auto.update_text()
        self.btn_auto.clicked.connect(lambda: AutoStartManager.set_autostart(self.btn_auto.isChecked()))
        h_btns.addWidget(self.btn_sys); h_btns.addWidget(self.btn_auto)
        il.addLayout(h1); il.addLayout(h_btns)
        l.addStretch(); l.addWidget(self.btn_pow, 0, Qt.AlignCenter); l.addWidget(self.lbl_st, 0, Qt.AlignCenter); l.addLayout(meta_layout); l.addWidget(info, 0, Qt.AlignCenter); l.addStretch()
        return p

    def create_conf_page(self):
        p = QWidget(); l = QVBoxLayout(p); l.setContentsMargins(25,25,25,25); l.setSpacing(15)
        top = QFrame(); top.setFixedHeight(50); top.setStyleSheet("background:transparent;")
        tl = QHBoxLayout(top); tl.setContentsMargins(0,0,0,0); tl.setSpacing(10)
        lbl = QLabel("选择方案:"); lbl.setStyleSheet(f"color:{PALETTE['text_gray']}; font-weight:bold;")
        self.cb_srv = QComboBox(); self.cb_srv.setFixedHeight(36); self.cb_srv.setView(QListView()); self.cb_srv.setCursor(Qt.PointingHandCursor)
        self.cb_srv.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); self.cb_srv.currentIndexChanged.connect(self.on_srv_change)
        b_add = QPushButton("+"); b_ren = QPushButton("✎"); b_del = QPushButton("×")
        for b in [b_add, b_ren, b_del]:
            b.setFixedSize(36,36); b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:white; border:1px solid {PALETTE['border']}; border-radius:6px; color:{PALETTE['text_dark']}; font-size:16px; font-weight:bold;}} QPushButton:hover{{border-color:{PALETTE['primary']}; color:{PALETTE['primary']};}}")
        b_add.clicked.connect(self.act_add); b_ren.clicked.connect(self.act_ren); b_del.clicked.connect(self.act_del)
        tl.addWidget(lbl); tl.addWidget(self.cb_srv); tl.addWidget(b_add); tl.addWidget(b_ren); tl.addWidget(b_del)
        l.addWidget(top)
        form = QWidget(); fl = QVBoxLayout(form); fl.setContentsMargins(0,0,0,0); fl.setSpacing(15)
        def mk_row(w1, w2, l1_txt, l2_txt):
            r = QHBoxLayout(); r.setSpacing(20)
            v1 = QVBoxLayout(); v1.setSpacing(6); v1.addWidget(QLabel(l1_txt, styleSheet=f"color:{PALETTE['text_gray']}; font-size:12px;")); v1.addWidget(w1)
            v2 = QVBoxLayout(); v2.setSpacing(6); v2.addWidget(QLabel(l2_txt, styleSheet=f"color:{PALETTE['text_gray']}; font-size:12px;")); v2.addWidget(w2)
            r.addLayout(v1, 1); r.addLayout(v2, 1); return r
        self.in_srv = QLineEdit(); self.in_srv.setPlaceholderText("例如: my.worker.dev"); self.in_srv.setClearButtonEnabled(True); self.in_srv.setMinimumHeight(36); self.in_srv.textChanged.connect(self.save)
        self.in_tk = QLineEdit(); self.in_tk.setPlaceholderText("可选 Token"); self.in_tk.setEchoMode(QLineEdit.PasswordEchoOnEdit); self.in_tk.setClearButtonEnabled(True); self.in_tk.setMinimumHeight(36); self.in_tk.textChanged.connect(self.save)
        fl.addLayout(mk_row(self.in_srv, self.in_tk, "Worker 域名 (-f)", "Token 密钥"))
        self.in_lst = QLineEdit(); self.in_lst.setPlaceholderText("127.0.0.1:30000"); self.in_lst.setMinimumHeight(36); self.in_lst.textChanged.connect(self.save)
        self.cb_rt = QComboBox(); self.cb_rt.setMinimumHeight(36); self.cb_rt.setView(QListView()); self.cb_rt.addItems(["智能分流 (bypass_cn)", "全局代理 (global)", "仅转发 (none)"]); self.cb_rt.setItemData(0,"bypass_cn"); self.cb_rt.setItemData(1,"global"); self.cb_rt.setItemData(2,"none"); self.cb_rt.currentIndexChanged.connect(self.save)
        fl.addLayout(mk_row(self.in_lst, self.cb_rt, "本地监听 (-l)", "路由模式"))
        
        h_ip_head = QHBoxLayout()
        lbl_ip = QLabel("优选 IP / 优选域名", styleSheet=f"color:{PALETTE['text_gray']}; font-size:12px;")
        self.chk_auto = QCheckBox("启用自动优选 (Auto Best)"); self.chk_auto.setCursor(Qt.PointingHandCursor)
        self.chk_auto.stateChanged.connect(self.save)
        h_ip_head.addWidget(lbl_ip); h_ip_head.addStretch(); h_ip_head.addWidget(self.chk_auto)

        # [修改] 更换为 QPlainTextEdit 以去除粘贴格式
        self.in_ip = QPlainTextEdit(); 
        self.in_ip.setPlaceholderText("例如: saas.sln.fan\n1.2.3.4:8443"); 
        # 样式已在 setStyleSheet 中定义
        self.in_ip.textChanged.connect(self.debounce_save)
        
        fl.addLayout(h_ip_head); fl.addWidget(self.in_ip, 1); l.addWidget(form, 1); return p

    def create_logs_page(self):
        p = QWidget(); l = QVBoxLayout(p); l.setContentsMargins(20,20,20,20)
        h = QHBoxLayout(); h.addWidget(QLabel("运行日志", font=QFont("Segoe UI",11,QFont.Bold))); h.addStretch()
        b_cp = QPushButton("复制"); b_cp.setFixedSize(60,30); b_cp.clicked.connect(lambda: (QApplication.clipboard().setText(self.log_v.toPlainText()), self.statusBar().showMessage("已复制")))
        b_cl = QPushButton("清空"); b_cl.setFixedSize(60,30); b_cl.clicked.connect(lambda: self.log_v.clear())
        for b in [b_cp, b_cl]: b.setStyleSheet(f"background:white; border:1px solid {PALETTE['border']}; border-radius:6px;")
        h.addWidget(b_cp); h.addWidget(b_cl)
        self.log_v = QTextEdit(); self.log_v.setReadOnly(True)
        self.log_v.setStyleSheet(f"background:#1e293b; color:#cbd5e1; border-radius:8px; border:none; font-family:Consolas, monospace; font-size:12px; padding:10px;")
        l.addLayout(h); l.addWidget(self.log_v); return p

    def load_data(self):
        self.cb_srv.blockSignals(True); self.cb_srv.clear(); cid = self.cfg.data['current']; sel = 0
        for i, s in enumerate(self.cfg.data['servers']):
            self.cb_srv.addItem(s['name'], s['id'])
            if s['id'] == cid: sel = i
        self.cb_srv.setCurrentIndex(sel); self.cb_srv.blockSignals(False); self.fill_form()
    
    def fill_form(self):
        s = self.cfg.get_cur(); widgets = [self.in_srv, self.in_lst, self.in_tk, self.cb_rt, self.in_ip, self.chk_auto]
        for w in widgets: w.blockSignals(True)
        self.in_srv.setText(s.get('server','')); self.in_lst.setText(s.get('listen','')); self.in_tk.setText(s.get('token',''))
        self.in_ip.setPlainText(s.get('ip_list','')); idx = self.cb_rt.findData(s.get('routing','bypass_cn')); self.cb_rt.setCurrentIndex(idx if idx>=0 else 0)
        self.chk_auto.setChecked(s.get('auto_best', True))
        self.lbl_cur.setText(s['name']); [w.blockSignals(False) for w in widgets]

    def on_srv_change(self): self.cfg.data['current'] = self.cb_srv.currentData(); self.cfg.save(); self.fill_form()
    def save(self):
        s = self.cfg.get_cur()
        s.update({
            'server':self.in_srv.text(), 
            'listen':self.in_lst.text(), 
            'token':self.in_tk.text(), 
            'ip_list':self.in_ip.toPlainText(), 
            'routing':self.cb_rt.currentData(),
            'auto_best': self.chk_auto.isChecked()
        })
        self.cfg.update_cur(s); self.statusBar().showMessage("配置已保存", 1500)
    def debounce_save(self): QTimer.singleShot(600, self.save)
    def act_add(self):
        n,ok = QInputDialog.getText(self,"新建配置","输入配置名称:"); 
        if ok and n: self.cfg.add_new(n); self.load_data()
    def act_ren(self):
        cur = self.cfg.get_cur(); n, ok = QInputDialog.getText(self, "重命名", "输入新名称:", text=cur['name'])
        if ok and n: self.cfg.rename_cur(n); self.load_data()
    def act_del(self): 
        if QMessageBox.question(self, "确认删除", "确定删除此配置方案吗？") == QMessageBox.Yes: self.cfg.del_cur(); self.load_data()
    def switch_page(self, i): self.pages.setCurrentIndex(i); [b.setChecked(idx==i) for idx,b in enumerate(self.btns)]

    def toggle_run(self):
        self.btn_pow.setEnabled(False) 
        if self.worker and self.worker.running:
            if self.btn_sys.isChecked(): self.btn_sys.click() 
            self.log("正在停止服务...", "#fbbf24")
            self.worker.stop(); self.worker.wait(); QTimer.singleShot(500, self._ui_stop)
        else:
            self.save(); s = self.cfg.get_cur()
            if not s.get('server'): 
                QMessageBox.warning(self, "提示", "请先在【配置管理】填写 Worker 域名！"); self.switch_page(1); self.btn_pow.setEnabled(True); return
            self.btn_pow.set_active(True); self.lbl_st.setText("正在启动...")
            self.log_v.clear(); self.log(">>> 初始化中...", "#94a3b8")
            self.worker = WorkerThread(s); self.worker.msg.connect(self.log)
            self.worker.status_change.connect(self.lbl_st.setText); self.worker.latency_result.connect(self.lbl_lat.setText)
            self.worker.geo_result.connect(self.lbl_geo.setText)
            self.worker.error_alert.connect(lambda m: (self.lbl_st.setText(f"❌ {m}"), self.lbl_st.setStyleSheet(f"color:{PALETTE['danger']}")))
            self.worker.finished_safe.connect(self._check_abnormal_stop); self.worker.start()
            QTimer.singleShot(1000, lambda: (self.btn_pow.setEnabled(True), self.btn_sys.setEnabled(True)))

    def _ui_stop(self):
        self.btn_pow.set_active(False); self.btn_sys.setEnabled(False)
        if "❌" not in self.lbl_st.text(): self.lbl_st.setText("已断开"); self.lbl_st.setStyleSheet(f"color:{PALETTE['text_gray']}")
        self.lbl_lat.setText(""); self.lbl_geo.setText("--"); self.btn_pow.setEnabled(True)
    def _check_abnormal_stop(self):
        if not self.worker.running: self._ui_stop()

    def toggle_sys(self):
        on = self.btn_sys.isChecked(); self.btn_sys.update_text()
        if sys.platform != 'win32': return
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_SET_VALUE)
            if on:
                l = self.in_lst.text() or "127.0.0.1:30000"; p = l if ':' in l else f"127.0.0.1:{l}"
                winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, p); winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                self.log(f"系统代理已开启 ({p})", PALETTE['success'])
            else: 
                winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, 0); self.log("系统代理已关闭", "#94a3b8")
            import ctypes; ctypes.windll.wininet.InternetSetOptionW(0,39,0,0); ctypes.windll.wininet.InternetSetOptionW(0,37,0,0)
        except: self.btn_sys.setChecked(False); self.btn_sys.update_text(); self.log("系统代理设置失败", PALETTE['danger'])

    def log(self, t, c=None): 
        if self.log_v.document().lineCount() > 1000: self.log_v.clear()
        self.log_v.append(f'<font color="{c or "#cbd5e1"}">[{datetime.now().strftime("%H:%M:%S")}] {t}</font>')
        self.log_v.verticalScrollBar().setValue(self.log_v.verticalScrollBar().maximum())

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        if os.path.exists(ICON_PATH): self.tray.setIcon(QIcon(ICON_PATH))
        else: self.tray.setIcon(self.style().standardIcon(30))
        m = QMenu(); m.addAction("显示主界面", self.showNormal); m.addAction("退出程序", self.quit_app)
        self.tray.setContextMenu(m); self.tray.show(); self.tray.activated.connect(lambda r: self.showNormal() if r in (2,3) else None)
    def quit_app(self):
        if self.worker: self.worker.stop()
        if self.btn_sys.isChecked(): self.btn_sys.click()
        ProcessManager.kill_current(); QApplication.quit()
    def closeEvent(self, e): e.ignore(); self.hide()

if __name__ == '__main__':
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    f = QFont("Segoe UI", 9)
    f.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(f)

    checker = SingleInstance(port=58123) 
    if not checker.check():
        sys.exit(0)

    w = UltraWindow()
    checker.signal_wake_up.connect(lambda: (
        w.showNormal(), w.activateWindow(), w.raise_()
    ))

    sys.exit(app.exec_())
