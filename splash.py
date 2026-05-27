"""
HicoForge animated splash — sibling to HicoSend's package-send splash.
Metaphor: sparks/embers converge → red-hot ingot forms → hammer strike →
impact ripple → "HicoForge" wordmark reveal.

Pure QPainter — no external assets needed.
"""

import math
import random
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPointF, QRectF, Property,
    QParallelAnimationGroup, QSequentialAnimationGroup, QObject
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QFont, QPainterPath, QFontDatabase
)
from PySide6.QtWidgets import QWidget, QApplication

from app import theme


class Spark:
    """A single ember particle that travels from a random edge to the ingot center."""
    def __init__(self, w, h, cx, cy):
        # Pick a starting edge
        edge = random.choice(["top", "bottom", "left", "right"])
        margin = 40
        if edge == "top":
            self.x0 = random.uniform(margin, w - margin)
            self.y0 = random.uniform(0, h * 0.25)
        elif edge == "bottom":
            self.x0 = random.uniform(margin, w - margin)
            self.y0 = random.uniform(h * 0.75, h)
        elif edge == "left":
            self.x0 = random.uniform(0, w * 0.2)
            self.y0 = random.uniform(margin, h - margin)
        else:
            self.x0 = random.uniform(w * 0.8, w)
            self.y0 = random.uniform(margin, h - margin)

        # Target (ingot center) with a small jitter
        self.x1 = cx + random.uniform(-12, 12)
        self.y1 = cy + random.uniform(-6, 6)

        # Size & timing
        self.size = random.uniform(2.5, 5.0)
        self.delay = random.uniform(0.0, 0.25)
        self.duration = random.uniform(0.55, 0.85)

        # Color tint: orange to gold mix
        tint = random.random()
        if tint < 0.55:
            self.color = QColor(theme.EMBER_ORANGE)
        elif tint < 0.85:
            self.color = QColor(theme.EMBER_GOLD)
        else:
            self.color = QColor(theme.BRAND_RED_BRIGHT)

    def position(self, t):
        """Eased position at normalized time t in [0, 1]."""
        local_t = (t - self.delay) / self.duration
        if local_t <= 0:
            return self.x0, self.y0, 0.0
        if local_t >= 1:
            return self.x1, self.y1, 0.0  # gone
        # easeInOutCubic
        if local_t < 0.5:
            eased = 4 * local_t ** 3
        else:
            eased = 1 - ((-2 * local_t + 2) ** 3) / 2
        x = self.x0 + (self.x1 - self.x0) * eased
        y = self.y0 + (self.y1 - self.y0) * eased
        # Fade in then out
        if local_t < 0.7:
            alpha = min(1.0, local_t / 0.15)
        else:
            alpha = max(0.0, 1.0 - (local_t - 0.7) / 0.3)
        return x, y, alpha


class SplashWindow(QWidget):
    """
    Frameless animated splash. Drives all animation off a single elapsed-time
    value (0 → 1) so the painter can render any frame deterministically.
    """

    # Animation timeline (in seconds)
    T_FADE_IN_END        = 0.45
    T_SPARKS_START       = 0.20
    T_SPARKS_END         = 1.15
    T_INGOT_START        = 1.00
    T_INGOT_FORMED       = 1.45
    T_HAMMER_DOWN_START  = 1.55
    T_HAMMER_IMPACT      = 1.85
    T_RIPPLE_END         = 2.35
    T_WORDMARK_START     = 1.95
    T_WORDMARK_END       = 2.45
    T_TAGLINE_START      = 2.15
    T_TAGLINE_END        = 2.60
    T_PROGRESS_START     = 2.55
    T_TOTAL              = 3.20  # animation length before splash can close

    def __init__(self, on_finished=None):
        super().__init__()
        self.on_finished = on_finished
        self._t = 0.0  # elapsed seconds

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.SplashScreen
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(620, 360)

        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        # Geometry of the "anvil/ingot stage" inside the splash
        self.stage_cx = self.width() / 2
        self.stage_cy = 150  # vertical center of the ingot

        # Build sparks
        self.sparks = [Spark(self.width(), self.height(), self.stage_cx, self.stage_cy)
                       for _ in range(28)]

        # Progress bar sweep position
        self._progress_offset = 0.0

        # Drive everything from a 60 FPS timer
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._tick)
        self._frame_ms = 16
        self._frame_timer.start(self._frame_ms)

        # Track time
        from time import monotonic
        self._monotonic = monotonic
        self._t0 = monotonic()

    def _tick(self):
        self._t = self._monotonic() - self._t0
        # Drive the progress bar sweep continuously after it appears
        if self._t >= self.T_PROGRESS_START:
            self._progress_offset = ((self._t - self.T_PROGRESS_START) * 0.65) % 1.0
        self.update()

        if self._t >= self.T_TOTAL:
            self._frame_timer.stop()
            if self.on_finished:
                # Fade out + close
                self._start_fade_out()

    # ---- Fade-out ----
    def _start_fade_out(self):
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(280)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self._finish)
        self._fade_anim.start()

    def _finish(self):
        cb = self.on_finished
        self.close()
        if cb:
            cb()

    # ---- Painting ----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Shell fade-in
        shell_alpha = self._eased(self._t / self.T_FADE_IN_END, "out_cubic")
        shell_alpha = max(0.0, min(1.0, shell_alpha))

        self._draw_shell(p, shell_alpha)
        self._draw_ambient_glow(p, shell_alpha)
        self._draw_sparks(p)
        self._draw_ingot(p)
        self._draw_hammer(p)
        self._draw_ripple(p)
        self._draw_wordmark(p)
        self._draw_progress(p)

        p.end()

    # --- Shell ---
    def _draw_shell(self, p, alpha):
        p.setOpacity(alpha)
        rect = QRectF(10, 10, self.width() - 20, self.height() - 20)
        # Drop shadow approximation: layered semi-transparent rounded rects
        for i, (off, op) in enumerate([(8, 0.10), (5, 0.16), (2, 0.22)]):
            shadow_rect = QRectF(rect.x() - off/2, rect.y() + off, rect.width() + off, rect.height())
            p.setBrush(QColor(0, 0, 0, int(255 * op)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(shadow_rect, theme.RADIUS_LG, theme.RADIUS_LG)

        # Main background gradient
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, QColor(theme.BG_TOP))
        grad.setColorAt(1.0, QColor(theme.BG_BOTTOM))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, theme.RADIUS_LG, theme.RADIUS_LG)

        # Subtle top highlight line
        hl_grad = QLinearGradient(rect.topLeft(), rect.topRight())
        hl_grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        hl_grad.setColorAt(0.5, QColor(255, 255, 255, 38))
        hl_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl_grad))
        p.drawRect(QRectF(rect.x() + 1, rect.y() + 1, rect.width() - 2, 1))

        p.setOpacity(1.0)

    # --- Ambient ember glow behind the ingot ---
    def _draw_ambient_glow(self, p, shell_alpha):
        # Glow intensity ramps with ingot formation, peaks at hammer impact
        if self._t < self.T_INGOT_START:
            intensity = 0.0
        elif self._t < self.T_HAMMER_IMPACT:
            intensity = (self._t - self.T_INGOT_START) / (self.T_HAMMER_IMPACT - self.T_INGOT_START)
        elif self._t < self.T_HAMMER_IMPACT + 0.15:
            # Flash on impact
            intensity = 1.4
        else:
            decay = (self._t - (self.T_HAMMER_IMPACT + 0.15)) / 0.8
            intensity = max(0.4, 1.0 - decay * 0.6)
        intensity = max(0.0, min(1.4, intensity)) * shell_alpha

        glow_w = 360
        glow_h = 160
        gx = self.stage_cx - glow_w / 2
        gy = self.stage_cy - glow_h / 2
        rg = QRadialGradient(self.stage_cx, self.stage_cy, glow_w / 2)
        rg.setColorAt(0.0, QColor(255, 122, 26, int(120 * intensity)))
        rg.setColorAt(0.4, QColor(225, 29, 44, int(60 * intensity)))
        rg.setColorAt(1.0, QColor(225, 29, 44, 0))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(gx, gy, glow_w, glow_h))

    # --- Sparks converging ---
    def _draw_sparks(self, p):
        if self._t < self.T_SPARKS_START or self._t > self.T_SPARKS_END:
            return
        # Normalize spark time
        sp_t = (self._t - self.T_SPARKS_START) / (self.T_SPARKS_END - self.T_SPARKS_START)
        for s in self.sparks:
            x, y, a = s.position(sp_t)
            if a <= 0:
                continue
            c = QColor(s.color)
            c.setAlphaF(a * 0.95)
            # Soft glow
            glow = QRadialGradient(x, y, s.size * 3)
            gc = QColor(c)
            gc.setAlphaF(a * 0.35)
            glow.setColorAt(0.0, gc)
            gc2 = QColor(c)
            gc2.setAlphaF(0)
            glow.setColorAt(1.0, gc2)
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), s.size * 3, s.size * 3)
            # Core
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(x, y), s.size, s.size)

    # --- The forming ingot ---
    def _draw_ingot(self, p):
        if self._t < self.T_INGOT_START:
            return
        # Scale-in with overshoot from 0 -> 1
        local = (self._t - self.T_INGOT_START) / (self.T_INGOT_FORMED - self.T_INGOT_START)
        local = max(0.0, min(1.0, local))
        scale = self._eased(local, "out_back")

        # Heat color shifts from bright yellow-white (just forged) → orange → red as it cools
        if self._t < self.T_HAMMER_IMPACT:
            heat = 0.85  # very hot
        else:
            decay = (self._t - self.T_HAMMER_IMPACT) / 1.0
            heat = max(0.55, 0.95 - decay * 0.25)

        # Compression squash during hammer impact
        squash_y = 1.0
        if self.T_HAMMER_IMPACT - 0.05 <= self._t <= self.T_HAMMER_IMPACT + 0.18:
            phase = (self._t - (self.T_HAMMER_IMPACT - 0.05)) / 0.23
            squash_y = 1.0 - 0.22 * math.sin(phase * math.pi)

        base_w = 130
        base_h = 38
        w = base_w * scale
        h = base_h * scale * squash_y
        x = self.stage_cx - w / 2
        y = self.stage_cy - h / 2

        # Ingot shape: trapezoid-ish rounded rectangle
        path = QPainterPath()
        inset = w * 0.08
        path.moveTo(x + inset, y)
        path.lineTo(x + w - inset, y)
        path.quadTo(x + w, y, x + w, y + h * 0.35)
        path.lineTo(x + w - inset * 0.5, y + h)
        path.lineTo(x + inset * 0.5, y + h)
        path.lineTo(x, y + h * 0.35)
        path.quadTo(x, y, x + inset, y)
        path.closeSubpath()

        # Heat gradient
        grad = QLinearGradient(0, y, 0, y + h)
        if heat > 0.7:
            grad.setColorAt(0.0, QColor(255, 240, 200))   # near-white hot top
            grad.setColorAt(0.4, QColor(255, 180, 71))
            grad.setColorAt(1.0, QColor(184, 74, 0))
        else:
            grad.setColorAt(0.0, QColor(255, 180, 71))
            grad.setColorAt(0.5, QColor(255, 122, 26))
            grad.setColorAt(1.0, QColor(159, 17, 25))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawPath(path)

        # Top highlight rim
        rim_pen = QPen(QColor(255, 255, 220, int(180 * heat)))
        rim_pen.setWidthF(1.3)
        p.setPen(rim_pen)
        p.setBrush(Qt.NoBrush)
        # Just the top arc
        top_path = QPainterPath()
        top_path.moveTo(x + inset, y + 1)
        top_path.lineTo(x + w - inset, y + 1)
        p.drawPath(top_path)

    # --- Hammer dropping in for the strike ---
    def _draw_hammer(self, p):
        if self._t < self.T_HAMMER_DOWN_START or self._t > self.T_HAMMER_IMPACT + 0.45:
            return

        # Vertical position: from above ingot down to ingot at impact, then bounce back up
        if self._t <= self.T_HAMMER_IMPACT:
            phase = (self._t - self.T_HAMMER_DOWN_START) / (self.T_HAMMER_IMPACT - self.T_HAMMER_DOWN_START)
            eased = self._eased(phase, "in_cubic")
            # Hammer starts way above; ends just touching the ingot top
            top_y0 = self.stage_cy - 150
            top_y1 = self.stage_cy - 28
            head_y = top_y0 + (top_y1 - top_y0) * eased
            alpha = min(1.0, phase * 2.5)
        else:
            phase = (self._t - self.T_HAMMER_IMPACT) / 0.45
            eased = self._eased(phase, "out_cubic")
            top_y0 = self.stage_cy - 28
            top_y1 = self.stage_cy - 110
            head_y = top_y0 + (top_y1 - top_y0) * eased
            alpha = max(0.0, 1.0 - phase)

        p.setOpacity(alpha)

        head_cx = self.stage_cx
        head_w = 70
        head_h = 32

        # Hammer head (dark metal w/ vertical highlight)
        hg = QLinearGradient(head_cx - head_w/2, 0, head_cx + head_w/2, 0)
        hg.setColorAt(0.0, QColor(60, 62, 70))
        hg.setColorAt(0.5, QColor(110, 114, 124))
        hg.setColorAt(1.0, QColor(45, 47, 55))
        p.setBrush(QBrush(hg))
        p.setPen(QPen(QColor(20, 22, 28), 1))
        head_rect = QRectF(head_cx - head_w/2, head_y, head_w, head_h)
        p.drawRoundedRect(head_rect, 4, 4)

        # Handle: brown rectangle extending up
        handle_w = 10
        handle_h = 80
        handle_x = head_cx - handle_w / 2
        handle_y = head_y - handle_h
        hg2 = QLinearGradient(handle_x, 0, handle_x + handle_w, 0)
        hg2.setColorAt(0.0, QColor(80, 50, 30))
        hg2.setColorAt(0.5, QColor(140, 95, 60))
        hg2.setColorAt(1.0, QColor(60, 38, 22))
        p.setBrush(QBrush(hg2))
        p.setPen(QPen(QColor(30, 18, 10), 1))
        p.drawRoundedRect(QRectF(handle_x, handle_y, handle_w, handle_h), 2, 2)

        p.setOpacity(1.0)

    # --- Impact ripple ---
    def _draw_ripple(self, p):
        if self._t < self.T_HAMMER_IMPACT or self._t > self.T_RIPPLE_END:
            return
        phase = (self._t - self.T_HAMMER_IMPACT) / (self.T_RIPPLE_END - self.T_HAMMER_IMPACT)
        # Two staggered ripples
        for ring_offset in (0.0, 0.18):
            rp = phase - ring_offset
            if rp <= 0 or rp >= 1:
                continue
            radius = 40 + rp * 200
            alpha = (1.0 - rp) * 200
            pen = QPen(QColor(255, 180, 71, int(alpha)))
            pen.setWidthF(2.0 * (1.0 - rp * 0.5))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(self.stage_cx, self.stage_cy + 4), radius, radius * 0.35)

    # --- Wordmark + tagline ---
    def _draw_wordmark(self, p):
        # HicoForge title
        if self._t >= self.T_WORDMARK_START:
            phase = min(1.0, (self._t - self.T_WORDMARK_START) / (self.T_WORDMARK_END - self.T_WORDMARK_START))
            eased = self._eased(phase, "out_cubic")
            alpha = eased
            y_offset = (1.0 - eased) * 10

            p.setOpacity(alpha)
            font = QFont("Segoe UI Variable Display", 30, QFont.DemiBold)
            font.setStyleStrategy(QFont.PreferAntialias)
            p.setFont(font)
            p.setPen(QColor(theme.TEXT_PRIMARY))
            title_y = 235 + y_offset
            p.drawText(QRectF(0, title_y, self.width(), 50),
                       Qt.AlignHCenter | Qt.AlignTop, "HicoForge")
            p.setOpacity(1.0)

        # Tagline
        if self._t >= self.T_TAGLINE_START:
            phase = min(1.0, (self._t - self.T_TAGLINE_START) / (self.T_TAGLINE_END - self.T_TAGLINE_START))
            eased = self._eased(phase, "out_cubic")
            alpha = eased
            y_offset = (1.0 - eased) * 6

            p.setOpacity(alpha)
            tag_font = QFont("Segoe UI Variable Text", 9, QFont.Medium)
            tag_font.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
            p.setFont(tag_font)
            p.setPen(QColor(theme.TEXT_DIM))
            tag_y = 285 + y_offset
            p.drawText(QRectF(0, tag_y, self.width(), 20),
                       Qt.AlignHCenter | Qt.AlignTop,
                       "SHAPE  IT.   SHARPEN  IT.")
            p.setOpacity(1.0)

    # --- Progress sweep ---
    def _draw_progress(self, p):
        if self._t < self.T_PROGRESS_START:
            return
        phase = min(1.0, (self._t - self.T_PROGRESS_START) / 0.30)
        p.setOpacity(phase)
        bar_y = self.height() - 30
        bar_x = 30
        bar_w = self.width() - 60
        bar_h = 2
        # Track
        p.setBrush(QColor(255, 255, 255, 18))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1, 1)
        # Sweeping segment
        seg_w = 140
        seg_x = bar_x + (bar_w + seg_w) * self._progress_offset - seg_w
        grad = QLinearGradient(seg_x, 0, seg_x + seg_w, 0)
        grad.setColorAt(0.0, QColor(255, 122, 26, 0))
        grad.setColorAt(0.5, QColor(255, 122, 26, 200))
        grad.setColorAt(1.0, QColor(255, 180, 71, 255))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(seg_x, bar_y, seg_w, bar_h), 1, 1)
        p.setOpacity(1.0)

    # ---- Easing helpers ----
    @staticmethod
    def _eased(t, kind):
        t = max(0.0, min(1.0, t))
        if kind == "out_cubic":
            return 1 - (1 - t) ** 3
        if kind == "in_cubic":
            return t ** 3
        if kind == "in_out_cubic":
            return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
        if kind == "out_back":
            c1 = 1.70158
            c3 = c1 + 1
            return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2
        return t
