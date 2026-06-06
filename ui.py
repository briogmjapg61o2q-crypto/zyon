from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar, QGridLayout,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_OS = platform.system()

# ── Color Palette ──────────────────────────────────────────────────────────────
class C:
    BG        = "#0a0a0f"
    PANEL     = "#0d0d14"
    PANEL2    = "#111118"
    BORDER    = "#1e1e2e"
    BORDER_B  = "#2d2d4a"
    PRI       = "#7b7bff"
    PRI_DIM   = "#4a4a99"
    PRI_GHO   = "#13132a"
    ACC       = "#a855f7"
    ACC2      = "#c084fc"
    GREEN     = "#4ade80"
    GREEN_D   = "#22c55e"
    RED       = "#f87171"
    MUTED_C   = "#f87171"
    TEXT      = "#e2e8f0"
    TEXT_DIM  = "#64748b"
    TEXT_MED  = "#94a3b8"
    WHITE     = "#f1f5f9"
    DARK      = "#07070d"
    BAR_BG    = "#0d0d1a"
    CYAN      = "#22d3ee"
    YELLOW    = "#facc15"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

# ── System Metrics ─────────────────────────────────────────────────────────────
class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.disk = 0.0
        self.net_up   = 0.0
        self.net_down = 0.0
        self.tmp  = 0.0
        self._net_prev = psutil.net_io_counters()
        self._net_t    = time.time()
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while True:
            self._update()
            time.sleep(2)

    def _update(self):
        try:
            self.cpu  = psutil.cpu_percent(interval=None)
            vm        = psutil.virtual_memory()
            self.mem  = vm.percent
            self.mem_used = vm.used
            self.mem_total = vm.total
            dk = psutil.disk_usage("/")
            self.disk = dk.percent
            self.disk_used  = dk.used
            self.disk_total = dk.total
            now = psutil.net_io_counters()
            t2  = time.time()
            dt  = max(t2 - self._net_t, 0.1)
            self.net_up   = (now.bytes_sent - self._net_prev.bytes_sent) / dt / 1e6
            self.net_down = (now.bytes_recv - self._net_prev.bytes_recv) / dt / 1e6
            self._net_prev = now
            self._net_t    = t2
            self.tmp = self._get_temp()
        except Exception:
            pass

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return -1.0
            for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
                if key in temps and temps[key]:
                    return temps[key][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        return -1.0

    def snapshot(self) -> dict:
        return {
            "cpu": self.cpu, "mem": self.mem,
            "mem_used": getattr(self, "mem_used", 0),
            "mem_total": getattr(self, "mem_total", 1),
            "disk": getattr(self, "disk", 0),
            "disk_used": getattr(self, "disk_used", 0),
            "disk_total": getattr(self, "disk_total", 1),
            "net_up": self.net_up, "net_down": self.net_down,
            "tmp": self.tmp,
        }

_metrics = _SysMetrics()

# ── Animated Ring Canvas (center) ─────────────────────────────────────────────
class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._wave_data  = [0.0] * 40

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _step(self):
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.10 if self.speaking else 0.45):
            if self.speaking:
                self._tgt_scale = random.uniform(1.05, 1.12)
                self._tgt_halo  = random.uniform(140, 180)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo  = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.007)
                self._tgt_halo  = random.uniform(45, 65)
            self._last_t = now

        sp = 0.35 if self.speaking else 0.13
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        speeds = [1.2, -0.8, 1.8] if self.speaking else [0.5, -0.3, 0.8]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.72
        spd = 4.0 if self.speaking else 1.8
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.06 if self.speaking else 0.02):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.25:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.27
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.8, 2.2),
                math.sin(ang) * random.uniform(0.8, 2.2) - 0.4, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.026]
            for p in self._particles if p[4] > 0
        ]

        # wave update
        for i in range(len(self._wave_data) - 1):
            self._wave_data[i] = self._wave_data[i+1]
        if self.speaking:
            self._wave_data[-1] = random.uniform(0.3, 1.0)
        elif self.muted:
            self._wave_data[-1] = 0.0
        else:
            self._wave_data[-1] = abs(math.sin(self._tick * 0.08)) * 0.15

        self._blink_tick += 1
        if self._blink_tick >= 35:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # subtle dot grid
        p.setPen(QPen(qcol(C.PRI_GHO, 60), 1))
        for x in range(0, W, 50):
            for y in range(0, H, 50):
                p.drawPoint(x, y)

        r_face = fw * 0.30

        # halo glow rings
        for i in range(8):
            r   = r_face * (1.9 - i * 0.09)
            frc = 1.0 - i / 8
            a   = max(0, min(255, int(self._halo * 0.07 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a   = max(0, int(200 * (1.0 - pr / (fw * 0.72))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.47, 2.5, 110, 80), (0.39, 1.8, 75, 58), (0.31, 1.2, 52, 42)]
        ):
            ring_r = fw * r_frac
            base   = self._rings[idx]
            a_val  = max(0, min(255, int(self._halo * (1.0 - idx * 0.17))))
            col    = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r)); p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # center orb
        orb_r = int(fw * 0.24 * self._scale)
        for i in range(10, 0, -1):
            r2  = int(orb_r * i / 10)
            frc = i / 10
            a   = max(0, min(255, int(self._halo * 0.9 * frc)))
            if self.muted:
                col = QColor(180, 30, 60, a)
            elif self.speaking:
                col = QColor(100, 60, 220, a)
            else:
                col = QColor(40, 40, 140, a)
            p.setBrush(QBrush(col)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))

        # ZYON text
        p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2.2))), 1))
        p.setFont(QFont("Courier New", max(12, int(fw * 0.055)), QFont.Weight.Bold))
        p.drawText(QRectF(cx - 90, cy - 18, 180, 36), Qt.AlignmentFlag.AlignCenter, "Z Y O N")

        p.setPen(QPen(qcol(C.ACC2, 180), 1))
        p.setFont(QFont("Courier New", max(7, int(fw * 0.03))))
        p.drawText(QRectF(cx - 90, cy + 14, 180, 18), Qt.AlignmentFlag.AlignCenter, "AI ASSISTANT")

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.0, 2.0)

        # SYSTEM ONLINE dot + text
        dot_y = cy + fw * 0.38
        dot_col = qcol(C.MUTED_C if self.muted else C.GREEN)
        p.setBrush(QBrush(dot_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - 60, dot_y + 4, 8, 8))
        p.setPen(QPen(dot_col, 1))
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.drawText(QRectF(cx - 48, dot_y, 120, 18), Qt.AlignmentFlag.AlignLeft,
                   "MUTED" if self.muted else "SYSTEM ONLINE")

        # state label below
        sy = dot_y + 22
        if self.speaking:
            txt, col = "SPEAKING", qcol(C.YELLOW)
        elif self.muted:
            txt, col = "MUTED", qcol(C.RED)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym} PROCESSING", qcol(C.YELLOW)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym} LISTENING", qcol(C.GREEN)
        else:
            txt, col = self.state, qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 9))
        p.drawText(QRectF(0, sy, W, 18), Qt.AlignmentFlag.AlignCenter, txt)


# ── Metric Bar ─────────────────────────────────────────────────────────────────
class MetricBar(QWidget):
    def __init__(self, label: str, sub: str = "", color: str = C.PRI, parent=None):
        super().__init__(parent)
        self.label = label
        self.sub   = sub
        self.color = color
        self._pct  = 0.0
        self._text = "0%"
        self.setFixedHeight(36)

    def set_value(self, pct: float, text: str, sub: str = ""):
        self._pct  = max(0.0, min(100.0, pct))
        self._text = text
        if sub:
            self.sub = sub
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # label row
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(0, 0, W // 2, 14, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label)
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(W // 2, 0, W // 2, 14, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

        # sub label
        if self.sub:
            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(0, 14, W, 8, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.sub)

        # bar track
        bar_y = H - 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol(C.BORDER, 180)))
        p.drawRoundedRect(QRectF(0, bar_y, W, 5), 2, 2)

        # bar fill
        fill_w = W * self._pct / 100
        if fill_w > 2:
            grad = QLinearGradient(0, 0, fill_w, 0)
            base = QColor(self.color)
            grad.setColorAt(0, QColor(base.red()//2, base.green()//2, base.blue()//2, 220))
            grad.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 255))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(0, bar_y, fill_w, 5), 2, 2)


# ── Log Widget ─────────────────────────────────────────────────────────────────
class LogWidget(QTextEdit):
    _append_sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 8))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK}; color: {C.TEXT_MED};
                border: none; padding: 4px;
            }}
            QScrollBar:vertical {{
                background: {C.PANEL}; width: 4px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 2px;
            }}
        """)
        self._append_sig.connect(self._do_append)
        self._queue: list[str] = []
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._flush)
        self._tmr.start(80)

    def append_log(self, text: str):
        self._append_sig.emit(text)

    def _do_append(self, text: str):
        self._queue.append(text)

    def _flush(self):
        if not self._queue:
            return
        for text in self._queue[:6]:
            ts = time.strftime("%H:%M:%S")
            if text.startswith("SYS:"):
                col = C.CYAN
            elif text.startswith("ERR:"):
                col = C.RED
            elif text.startswith("You:"):
                col = C.WHITE
            elif text.startswith("ZYON:"):
                col = C.ACC2
            elif "[SUCCESS]" in text:
                col = C.GREEN
            elif "[INFO]" in text:
                col = C.TEXT_MED
            else:
                col = C.TEXT_MED
            self.append(f'<span style="color:{C.TEXT_DIM}">{ts}</span> '
                        f'<span style="color:{col}">{text}</span>')
        self._queue = self._queue[6:]
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── Terminal Panel (bottom) ─────────────────────────────────────────────────────
class TerminalPanel(QWidget):
    def __init__(self, title: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {C.DARK};
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(28)
        title_bar.setStyleSheet(f"""
            background: {C.PANEL2};
            border-bottom: 1px solid {C.BORDER};
            border-radius: 6px 6px 0 0;
        """)
        tb_lay = QHBoxLayout(title_bar)
        tb_lay.setContentsMargins(10, 0, 10, 0)

        # traffic lights
        for dot_col in ["#ff5f57", "#ffbd2e", "#28ca42"]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {dot_col}; background: transparent; border: none;")
            dot.setFont(QFont("Courier New", 8))
            tb_lay.addWidget(dot)

        tb_lay.addSpacing(8)
        lbl = QLabel(f"zyon@system:~ / {title}")
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        tb_lay.addWidget(lbl)
        tb_lay.addStretch()
        lay.addWidget(title_bar)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Courier New", 8))
        self._text.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; color: {C.TEXT_MED};
                border: none; padding: 6px;
            }}
            QScrollBar:vertical {{
                background: {C.PANEL}; width: 3px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 1px;
            }}
        """)
        lay.addWidget(self._text)

        # prompt row
        prompt_row = QWidget()
        prompt_row.setStyleSheet(f"background: transparent; border: none;")
        pr_lay = QHBoxLayout(prompt_row)
        pr_lay.setContentsMargins(8, 2, 8, 6)
        prompt_lbl = QLabel(f"zyon@system:~ / {title} ▌")
        prompt_lbl.setFont(QFont("Courier New", 8))
        prompt_lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        pr_lay.addWidget(prompt_lbl)
        pr_lay.addStretch()
        lay.addWidget(prompt_row)

    def write(self, text: str, color: str = None):
        col = color or C.TEXT_MED
        self._text.append(f'<span style="color:{col}">{text}</span>')
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_content(self, html: str):
        self._text.setHtml(html)


# ── Voice Orb Panel (top right) ────────────────────────────────────────────────
class VoiceOrbWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(220)
        self._state    = "LISTENING"
        self._speaking = False
        self._tick     = 0
        self._wave     = [0.0] * 30
        self._orb_r    = 0.0
        self._orb_tgt  = 0.3
        self._orb_rings = [0.0, 120.0, 240.0]

        tmr = QTimer(self)
        tmr.timeout.connect(self._step)
        tmr.start(33)

    def set_state(self, state: str, speaking: bool):
        self._state    = state
        self._speaking = speaking

    def _step(self):
        self._tick += 1

        # wave
        for i in range(len(self._wave) - 1):
            self._wave[i] = self._wave[i+1]
        if self._speaking:
            self._wave[-1] = random.uniform(0.4, 1.0)
        else:
            self._wave[-1] = abs(math.sin(self._tick * 0.12)) * 0.2

        speeds = [1.0, -0.7, 1.5] if self._speaking else [0.4, -0.25, 0.6]
        for i, spd in enumerate(speeds):
            self._orb_rings[i] = (self._orb_rings[i] + spd) % 360

        tgt = 0.7 if self._speaking else 0.3
        self._orb_r += (tgt - self._orb_r) * 0.15
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))

        W, H = self.width(), self.height()
        cx, cy = W / 2, (H - 50) / 2 + 10
        r_base = min(W, H - 60) * 0.32

        # orb rings
        for idx, (r_frac, arc_l, gap) in enumerate(
            [(1.5, 80, 60), (1.25, 60, 50), (1.05, 40, 38)]
        ):
            ring_r = r_base * r_frac
            base   = self._orb_rings[idx]
            a      = max(40, min(160, int(80 + self._orb_r * 100)))
            col    = qcol(C.PRI, a)
            p.setPen(QPen(col, 1.5 - idx * 0.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect  = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # center orb
        for i in range(8, 0, -1):
            r2  = int(r_base * i / 8)
            frc = i / 8
            a   = int(180 * frc * (0.4 + self._orb_r * 0.6))
            col = QColor(80, 60, 200, min(255, a))
            p.setBrush(QBrush(col)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))

        # state text
        if self._speaking:
            txt = "Speak now..."
            col = qcol(C.WHITE)
        elif self._state == "THINKING":
            txt = "Processing..."
            col = qcol(C.YELLOW)
        else:
            txt = "Listening..."
            col = qcol(C.TEXT)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Courier New", 10))
        p.drawText(QRectF(0, cy + r_base + 10, W, 20), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = H - 32
        N  = len(self._wave)
        bw = W / (N * 1.2)
        ox = (W - N * bw * 1.2) / 2
        for i, v in enumerate(self._wave):
            hgt = max(2, int(v * 20))
            col = qcol(C.PRI, 180) if v > 0.5 else qcol(C.PRI_DIM, 140)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawRoundedRect(QRectF(ox + i * bw * 1.2, wy - hgt, bw, hgt), 1, 1)


# ── Shortcut Button ─────────────────────────────────────────────────────────────
class ShortcutBtn(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 10))
        icon_lbl.setStyleSheet("background: transparent; border: none; color: white;")
        text_lbl = QLabel(label)
        text_lbl.setFont(QFont("Courier New", 8))
        text_lbl.setStyleSheet(f"background: transparent; border: none; color: {C.TEXT_MED};")
        lay.addWidget(icon_lbl)
        lay.addWidget(text_lbl)
        lay.addStretch()
        self.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; border: 1px solid {C.BORDER};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI_DIM};
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


# ── File Drop Zone (simplified) ─────────────────────────────────────────────────
def _file_category(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".pdf"}: return "pdf"
    if ext in {".py", ".js", ".ts", ".cpp", ".java", ".rb", ".go"}: return "code"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}: return "image"
    if ext in {".txt", ".md", ".csv", ".json", ".yaml", ".xml"}: return "text"
    return "unknown"

def _fmt_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

_FILE_ICONS = {
    "pdf":     ("📄", C.RED),
    "code":    ("💻", C.GREEN),
    "image":   ("🖼", C.CYAN),
    "text":    ("📝", C.TEXT),
    "unknown": ("📎", C.TEXT_DIM),
}


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(50)
        self._file: str | None = None
        self._hover = False
        self.setStyleSheet(f"""
            QWidget {{
                background: {C.PANEL2}; border: 1px dashed {C.BORDER_B};
                border-radius: 5px;
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 5)
        self._lbl = QLabel("📎  Drop file or click to upload")
        self._lbl.setFont(QFont("Courier New", 8))
        self._lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        lay.addWidget(self._lbl)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover = True; self.update()

    def dragLeaveEvent(self, e):
        self._hover = False; self.update()

    def dropEvent(self, e: QDropEvent):
        self._hover = False
        urls = e.mimeData().urls()
        if urls:
            self._set_file(urls[0].toLocalFile())

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._file = path
        p = Path(path)
        icon, _ = _FILE_ICONS.get(_file_category(p), _FILE_ICONS["unknown"])
        self._lbl.setText(f"{icon}  {p.name}  ·  {_fmt_size(p.stat().st_size)}")
        self._lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
        self.file_selected.emit(path)

    def current_file(self) -> str | None:
        return self._file

    def clear_file(self):
        self._file = None
        self._lbl.setText("📎  Drop file or click to upload")
        self._lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")


# ── Setup Overlay ───────────────────────────────────────────────────────────────
class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QWidget {{
                background: {C.PANEL}; border: 1px solid {C.BORDER_B};
                border-radius: 10px;
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        title = QLabel("ZYON SETUP")
        title.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        sub = QLabel("Configure your Gemini API key and OS to continue")
        sub.setFont(QFont("Courier New", 8))
        sub.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        def _lbl(txt):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            l.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
            return l

        lay.addWidget(_lbl("GEMINI API KEY"))
        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("AIza...")
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setFont(QFont("Courier New", 9))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.DARK}; color: {C.WHITE};
                border: 1px solid {C.BORDER_B}; border-radius: 4px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        lay.addWidget(self._key_input)

        lay.addWidget(_lbl("OPERATING SYSTEM"))
        self._os_sel = "windows"
        os_row = QHBoxLayout()
        self._os_btns = {}
        for os_name in ["windows", "mac", "linux"]:
            btn = QPushButton(os_name.upper())
            btn.setFixedHeight(28)
            btn.setFont(QFont("Courier New", 8))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, n=os_name: self._sel(n))
            self._os_btns[os_name] = btn
            os_row.addWidget(btn)
        lay.addLayout(os_row)
        self._sel("windows")

        self._err = QLabel("")
        self._err.setFont(QFont("Courier New", 8))
        self._err.setStyleSheet(f"color: {C.RED}; background: transparent; border: none;")
        self._err.setWordWrap(True)
        lay.addWidget(self._err)

        submit = QPushButton("▸  INITIALIZE ZYON")
        submit.setFixedHeight(36)
        submit.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        submit.setCursor(Qt.CursorShape.PointingHandCursor)
        submit.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid {C.PRI}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_DIM}; color: white; }}
        """)
        submit.clicked.connect(self._submit)
        lay.addWidget(submit)

        link = QLabel('<a href="https://aistudio.google.com/apikey" '
                      f'style="color:{C.ACC2};">Get free Gemini API key →</a>')
        link.setFont(QFont("Courier New", 8))
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(link)

    def _sel(self, key: str):
        self._os_sel = key
        for k, btn in self._os_btns.items():
            if k == key:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.PRI_GHO}; color: {C.PRI};
                        border: 1px solid {C.PRI}; border-radius: 4px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.PANEL2}; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 4px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT_MED}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key or len(key) < 10:
            self._err.setText("Please enter a valid API key.")
            return
        self.done.emit(key, self._os_sel)


# ── Main Window ─────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("ZYON")
        self.setMinimumSize(1100, 720)
        self.resize(1366, 860)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - 1366) // 2,
            (screen.height() - 860)  // 2,
        )

        self.on_text_command  = None
        self._muted           = False
        self._current_file: str | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top menubar-style header
        root.addWidget(self._build_topbar())

        # Body: left | center | right
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_left_panel(), stretch=0)

        center_col = QVBoxLayout()
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(0)
        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_col.addWidget(self.hud, stretch=1)
        center_col.addWidget(self._build_terminal_row())
        body.addLayout(center_col, stretch=1)

        body.addWidget(self._build_right_panel(), stretch=0)
        root.addLayout(body, stretch=1)

        # Bottom icon dock
        root.addWidget(self._build_dock())

        # Timers
        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        # Sysinfo refresh in shell panel
        self._sysinfo_tmr = QTimer(self)
        self._sysinfo_tmr.timeout.connect(self._update_sysinfo)
        self._sysinfo_tmr.start(5000)
        self._update_sysinfo()

        self._log_sig.connect(self._log.append_log)
        self._log_sig.connect(lambda t: self._chat_term.write(t))
        self._state_sig.connect(self._apply_state)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 430
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )

    # ── Top Bar ──────────────────────────────────────────────────────────────
    def _build_topbar(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(36)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 12, 0)

        # Left: ZYON menu items
        for item in ["ZYON", "Terminal", "Shell", "Edit", "View", "Window", "Help"]:
            lbl = QLabel(item)
            lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold if item == "ZYON" else QFont.Weight.Normal))
            col = C.PRI if item == "ZYON" else C.TEXT_MED
            lbl.setStyleSheet(f"color: {col}; background: transparent; padding: 0 8px;")
            lay.addWidget(lbl)

        lay.addStretch()

        # Center: date/time
        self._clock_lbl = QLabel("00:00")
        self._clock_lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._clock_lbl)

        lay.addStretch()

        # Right: system stats
        self._top_cpu = QLabel("CPU 0%")
        self._top_ram = QLabel("RAM 0 GB")
        self._top_net = QLabel("4G")
        self._top_bat = QLabel("🔋 63%")
        for lbl in [self._top_cpu, self._top_ram, self._top_net, self._top_bat]:
            lbl.setFont(QFont("Courier New", 8))
            lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; padding: 0 6px;")
            lay.addWidget(lbl)

        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%a %b %d  %I:%M %p"))

    # ── Left Panel ────────────────────────────────────────────────────────────
    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(210)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 12, 10, 12)
        lay.setSpacing(8)

        def _section(title):
            hdr = QWidget()
            hdr_lay = QHBoxLayout(hdr)
            hdr_lay.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(title)
            lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            hdr_lay.addWidget(lbl)
            hdr_lay.addStretch()
            close_btn = QLabel("×")
            close_btn.setFont(QFont("Courier New", 10))
            close_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            hdr_lay.addWidget(close_btn)
            return hdr

        # ── System Overview
        lay.addWidget(_section("SYSTEM OVERVIEW"))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        self._bar_cpu  = MetricBar("CPU Usage",  "",          C.PRI)
        self._bar_mem  = MetricBar("RAM Usage",  "",          "#a855f7")
        self._bar_disk = MetricBar("Disk Usage", "",          C.CYAN)
        self._bar_net  = MetricBar("Network",    "",          C.GREEN)
        self._bar_tmp  = MetricBar("Temperature","",          C.YELLOW)
        for bar in [self._bar_cpu, self._bar_mem, self._bar_disk,
                    self._bar_net, self._bar_tmp]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        # ── Voice Status
        lay.addWidget(_section("VOICE STATUS"))
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep2)

        voice_row = QWidget()
        voice_row.setStyleSheet("background: transparent;")
        vr_lay = QHBoxLayout(voice_row)
        vr_lay.setContentsMargins(0, 4, 0, 4)
        mic_lbl = QLabel("🎙")
        mic_lbl.setFont(QFont("Segoe UI Emoji", 14))
        mic_lbl.setStyleSheet("background: transparent; border: none;")
        vr_lay.addWidget(mic_lbl)
        self._voice_lbl = QLabel("Listening...")
        self._voice_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        self._voice_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        vr_lay.addWidget(self._voice_lbl)
        vr_lay.addStretch()
        lay.addWidget(voice_row)

        # mini waveform label
        self._wave_lbl = QLabel("▁▂▃▄▅▆▇█▇▆▅▄▃▂▁")
        self._wave_lbl.setFont(QFont("Courier New", 8))
        self._wave_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        lay.addWidget(self._wave_lbl)

        # wave animation timer
        self._wave_tick = 0
        self._wave_tmr = QTimer(self)
        self._wave_tmr.timeout.connect(self._tick_wave)
        self._wave_tmr.start(120)

        lay.addSpacing(4)

        # ── Shortcuts
        lay.addWidget(_section("SHORTCUTS"))
        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep3)

        shortcuts = [
            ("🔍", "Open YouTube"),
            ("🔎", "Search Google"),
            ("📝", "Open Notepad"),
            ("🖥", "System Scan"),
            ("⏻",  "Shutdown"),
        ]
        for icon, label in shortcuts:
            btn = ShortcutBtn(icon, label)
            btn.clicked.connect(lambda _, l=label: self._shortcut_cmd(l))
            lay.addWidget(btn)

        lay.addStretch()

        # mute button
        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(28)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        return w

    def _tick_wave(self):
        self._wave_tick += 1
        chars = "▁▂▃▄▅▆▇█"
        wave  = "".join(random.choice(chars) for _ in range(16))
        col   = C.ACC if self.hud.speaking else C.PRI_DIM
        self._wave_lbl.setStyleSheet(f"color: {col}; background: transparent;")
        self._wave_lbl.setText(wave)

    def _shortcut_cmd(self, label: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(label,), daemon=True).start()

    # ── Right Panel ───────────────────────────────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(310)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        def _panel_header(title):
            hdr = QWidget()
            hdr.setStyleSheet(f"""
                background: {C.PANEL2}; border: 1px solid {C.BORDER};
                border-radius: 6px 6px 0 0;
            """)
            hdr.setFixedHeight(30)
            h_lay = QHBoxLayout(hdr)
            h_lay.setContentsMargins(10, 0, 10, 0)
            lbl = QLabel(title)
            lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
            h_lay.addWidget(lbl)
            h_lay.addStretch()
            for sym, col in [("−", C.TEXT_DIM), ("□", C.TEXT_DIM), ("×", C.RED)]:
                s = QLabel(sym)
                s.setFont(QFont("Courier New", 10))
                s.setStyleSheet(f"color: {col}; background: transparent; border: none; padding: 0 2px;")
                h_lay.addWidget(s)
            return hdr

        # Voice Assistant panel
        lay.addWidget(_panel_header("VOICE ASSISTANT"))
        self._voice_orb = VoiceOrbWidget()
        self._voice_orb.setStyleSheet(f"background: {C.PANEL}; border: 1px solid {C.BORDER}; border-top: none;")
        lay.addWidget(self._voice_orb)

        lay.addSpacing(6)

        # Quick Logs panel
        lay.addWidget(_panel_header("QUICK LOGS"))
        self._log = LogWidget()
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL}; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-top: none;
                border-radius: 0 0 6px 6px; padding: 4px;
            }}
            QScrollBar:vertical {{
                background: {C.PANEL}; width: 4px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 2px;
            }}
        """)
        lay.addWidget(self._log, stretch=1)

        lay.addSpacing(6)

        # File upload
        lay.addWidget(_panel_header("FILE UPLOAD"))
        drop_wrap = QWidget()
        drop_wrap.setStyleSheet(f"background: {C.PANEL}; border: 1px solid {C.BORDER}; border-top: none; border-radius: 0 0 6px 6px;")
        dw_lay = QVBoxLayout(drop_wrap)
        dw_lay.setContentsMargins(8, 8, 8, 8)
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        dw_lay.addWidget(self._drop_zone)
        lay.addWidget(drop_wrap)

        lay.addSpacing(4)

        # Input row
        lay.addWidget(_panel_header("COMMAND INPUT"))
        input_wrap = QWidget()
        input_wrap.setStyleSheet(f"background: {C.PANEL}; border: 1px solid {C.BORDER}; border-top: none; border-radius: 0 0 6px 6px;")
        iw_lay = QVBoxLayout(input_wrap)
        iw_lay.setContentsMargins(8, 8, 8, 8)
        iw_lay.setSpacing(5)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.DARK}; color: {C.WHITE};
                border: 1px solid {C.BORDER_B}; border-radius: 4px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 4px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        iw_lay.addLayout(row)
        lay.addWidget(input_wrap)

        return w

    # ── Terminal Row (bottom) ─────────────────────────────────────────────────
    def _build_terminal_row(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(220)
        w.setStyleSheet(f"background: {C.BG}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self._chat_term  = TerminalPanel("chat",  C.GREEN)
        self._log_term   = TerminalPanel("log",   C.CYAN)
        self._shell_term = TerminalPanel("shell", C.ACC2)

        lay.addWidget(self._chat_term,  stretch=1)
        lay.addWidget(self._log_term,   stretch=1)
        lay.addWidget(self._shell_term, stretch=1)

        # seed log terminal with startup lines
        QTimer.singleShot(500, self._seed_log_term)
        return w

    def _seed_log_term(self):
        ts = time.strftime("%H:%M:%S")
        for line, col in [
            (f"{ts}  [INFO]   Voice input detected",     C.TEXT_MED),
            (f"{ts}  [INFO]   Processing command...",    C.TEXT_MED),
            (f"{ts}  [INFO]   ZYON AI Online",           C.CYAN),
            (f"{ts}  [INFO]   Waiting for command...",   C.TEXT_DIM),
        ]:
            self._log_term.write(line, col)

    def _update_sysinfo(self):
        snap = _metrics.snapshot()
        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600); m = int((elapsed % 3600) // 60)
            uptime  = f"{h:02d}:{m:02d}"
        except Exception:
            uptime = "--:--"
        try:
            pkgs = len(psutil.pids())
        except Exception:
            pkgs = 0

        os_name = {
            "Windows": "ZYON OS (Windows)",
            "Darwin":  "ZYON OS (macOS)",
            "Linux":   "ZYON OS (Linux)",
        }.get(_OS, f"ZYON OS ({_OS})")

        mem_gb  = snap["mem_used"] / 1e9
        mem_tot = snap["mem_total"] / 1e9
        disk_gb = snap["disk_used"] / 1e9
        dsk_tot = snap["disk_total"] / 1e9

        lines = [
            (f"OS: {os_name}",                           C.TEXT),
            (f"Host: ZYON AI System",                    C.TEXT_DIM),
            (f"Kernel: 6.5.0-zyon",                      C.TEXT_DIM),
            (f"Uptime: {uptime}",                        C.TEXT_DIM),
            (f"Packages: {pkgs} (zyon-pkg)",             C.TEXT_DIM),
            (f"Shell: zsh 5.9",                          C.TEXT_DIM),
            (f"Resolution: {QApplication.primaryScreen().size().width()}x{QApplication.primaryScreen().size().height()}", C.TEXT_DIM),
            (f"CPU: {snap['cpu']:.0f}%",                 C.PRI),
            (f"GPU: ZYON GPU",                           C.ACC2),
            (f"Memory: {mem_gb:.2f}GiB / {mem_tot:.0f}GiB", C.GREEN),
        ]
        html = "".join(
            f'<span style="color:{c}">{l}</span><br>' for l, c in lines
        )
        self._shell_term.set_content(
            f'<div style="font-family:Courier New; font-size:9pt; background:transparent;">{html}</div>'
        )

    # ── Bottom Dock ───────────────────────────────────────────────────────────
    def _build_dock(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(58)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(2)

        # version label left
        ver = QLabel("v1.0.0  ZYON AI Assistant")
        ver.setFont(QFont("Courier New", 7))
        ver.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; padding: 0 12px;")
        lay.addWidget(ver)

        lay.addStretch()

        dock_items = [
            ("⌨", "Terminal"),
            ("📁", "Files"),
            ("🌐", "Browser"),
            ("✉", "Mail"),
            ("♪", "Music"),
            ("⌥", "Code"),
            ("🗑", "Trash"),
        ]
        for i, (icon, tip) in enumerate(dock_items):
            btn = QPushButton(icon)
            btn.setFixedSize(44, 44)
            btn.setFont(QFont("Segoe UI Emoji", 16))
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            is_active = (i == 0)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {'#1a1a2e' if is_active else 'transparent'};
                    border: {'1px solid ' + C.PRI if is_active else 'none'};
                    border-radius: 10px; color: white;
                }}
                QPushButton:hover {{
                    background: {C.PRI_GHO};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 10px;
                }}
            """)
            lay.addWidget(btn)

        lay.addStretch()
        return w

    # ── Metrics Update ────────────────────────────────────────────────────────
    def _update_metrics(self):
        snap = _metrics.snapshot()

        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")
        self._top_cpu.setText(f"CPU {cpu:.0f}%")

        mem   = snap["mem"]
        mem_g = snap["mem_used"] / 1e9
        tot_g = snap["mem_total"] / 1e9
        self._bar_mem.set_value(mem, f"{mem:.0f}%", f"{mem_g:.1f} GB / {tot_g:.0f} GB")
        self._top_ram.setText(f"RAM {mem_g:.1f} GB/{tot_g:.0f} GB")

        disk   = snap["disk"]
        disk_g = snap["disk_used"] / 1e9
        dtot_g = snap["disk_total"] / 1e9
        self._bar_disk.set_value(disk, f"{disk:.0f}%", f"{disk_g:.0f} GB / {dtot_g:.0f} GB")

        up   = snap["net_up"]
        down = snap["net_down"]
        up_s   = f"{up*1024:.0f}KB/s" if up < 1 else f"{up:.1f}MB/s"
        down_s = f"{down*1024:.0f}KB/s" if down < 1 else f"{down:.1f}MB/s"
        net_pct = min(100, (up + down) * 5)
        self._bar_net.set_value(net_pct, f"↑{up_s}", f"↓{down_s}")
        self._top_net.setText(f"↑{up_s} ↓{down_s}")

        tmp = snap["tmp"]
        if tmp >= 0:
            self._bar_tmp.set_value(min(100, tmp), f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        # battery
        try:
            bat = psutil.sensors_battery()
            if bat:
                pct = int(bat.percent)
                charging = "⚡" if bat.power_plugged else "🔋"
                self._top_bat.setText(f"{charging} {pct}%")
        except Exception:
            pass

    # ── State & Log ───────────────────────────────────────────────────────────
    def _apply_state(self, state: str):
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        self._voice_orb.set_state(state, state == "SPEAKING")
        lbl = {
            "LISTENING":  "Listening...",
            "THINKING":   "Processing...",
            "SPEAKING":   "Speaking...",
            "MUTED":      "Muted",
        }.get(state, state)
        self._voice_lbl.setText(lbl)

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        size = _fmt_size(p.stat().st_size)
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #200008; color: {C.RED};
                    border: 1px solid {C.RED}; border-radius: 4px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a0a; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 4px;
                }}
                QPushButton:hover {{ background: #002614; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        self._chat_term.write(f"You: {txt}", C.WHITE)
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 430
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. ZYON online.")
        self._chat_term.write("ZYON: System initialized and online.", C.ACC2)


# ── Shims & Public API ─────────────────────────────────────────────────────────
class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class ZyonUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
