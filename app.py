#!/usr/bin/env python3
"""
HMI Virtual Bidireccional - Embobinadora Toroidal
PySide6 + paho-mqtt

Topics:
  Publica  → bobibobiutb/cmd
  Suscribe → bobibobiutb/status

Bidireccionalidad:
  - Cambios en HMI física se reflejan aquí vía status.config
  - Cambios aquí se envían al ESP32 vía cmd
  - Flag _updating_from_mqtt evita bucles de retroalimentación
"""

import sys
import json
import time
import datetime
import paho.mqtt.client as mqtt

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QTextEdit, QGroupBox, QProgressBar,
    QSizePolicy, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QObject, Slot, QTimer
from PySide6.QtGui import QFont, QColor, QPalette

# ─── CONFIGURACIÓN MQTT ───────────────────────────────────────────────────────
MQTT_BROKER   = "broker.hivemq.com"
MQTT_PORT     = 1883
TOPICO_CMD    = "bobibobiutb/cmd"
TOPICO_STATUS = "bobibobiutb/status"

# Tiempo máximo sin recibir status antes de marcar ESP32 offline
ESP32_TIMEOUT_S = 6

# Velocidad: rango continuo 10-100 %
VEL_MIN  = 10
VEL_MAX  = 100
VEL_STEP = 5

# Recarga: cm por vuelta de carrete
CM_POR_VUELTA = 30.0

# ─── SEÑALES THREAD-SAFE ──────────────────────────────────────────────────────
class MqttSignals(QObject):
    """Puente entre el hilo MQTT y el hilo Qt principal."""
    status_received = Signal(dict)
    calc_received   = Signal(dict)
    connected       = Signal()
    disconnected    = Signal()
    log             = Signal(str)


# ─── WORKER MQTT ─────────────────────────────────────────────────────────────
class MqttWorker:
    def __init__(self, signals: MqttSignals):
        self.signals   = signals
        self._ready    = False
        self.client    = mqtt.Client(client_id="HMI-Bobina-Virtual")
        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message    = self._on_message

    def connect(self):
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self.client.loop_start()
        except Exception as exc:
            self.signals.log.emit(f"[MQTT] Error de conexión: {exc}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, payload: dict):
        if not self._ready:
            self.signals.log.emit("[MQTT] No conectado — comando descartado")
            return
        msg = json.dumps(payload, separators=(",", ":"))
        self.client.publish(TOPICO_CMD, msg)
        self.signals.log.emit(f">> {msg}")

    # ── Callbacks MQTT (hilo de red) ─────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._ready = True
            client.subscribe(TOPICO_STATUS)
            self.signals.connected.emit()
            self.signals.log.emit("[MQTT] Conectado a broker.hivemq.com")
        else:
            self.signals.log.emit(f"[MQTT] Fallo de conexión (rc={rc})")

    def _on_disconnect(self, client, userdata, rc):
        self._ready = False
        self.signals.disconnected.emit()
        self.signals.log.emit(f"[MQTT] Desconectado (rc={rc})")

    def _on_message(self, client, userdata, msg):
        try:
            raw  = msg.payload.decode("utf-8")
            data = json.loads(raw)
            mtype = data.get("type", "")
            if mtype == "status":
                self.signals.status_received.emit(data)
            elif mtype == "calculation":
                self.signals.calc_received.emit(data)
            else:
                self.signals.log.emit(f"<< {raw}")
        except Exception as exc:
            self.signals.log.emit(f"[MQTT] Error parse: {exc}")


# =============================================================================
#  VENTANA PRINCIPAL
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HMI Virtual — Embobinadora Toroidal")
        self.setMinimumSize(1050, 720)

        # Flag para evitar que actualizaciones desde MQTT disparen comandos
        self._updating_from_mqtt = False

        # Timestamp del último status recibido (para detectar ESP32 offline)
        self._last_esp32_seen: float = 0.0

        # MQTT
        self.mqtt_signals = MqttSignals()
        self.mqtt_worker  = MqttWorker(self.mqtt_signals)

        self.mqtt_signals.status_received.connect(self.on_status_received)
        self.mqtt_signals.calc_received.connect(self.on_calc_received)
        self.mqtt_signals.connected.connect(self.on_mqtt_connected)
        self.mqtt_signals.disconnected.connect(self.on_mqtt_disconnected)
        self.mqtt_signals.log.connect(self.append_log)

        self._build_ui()
        self.mqtt_worker.connect()

        # Timer para revisar conexión ESP32 cada 3 s
        self._esp32_timer = QTimer(self)
        self._esp32_timer.timeout.connect(self._check_esp32_connection)
        self._esp32_timer.start(3000)

    # =========================================================================
    #  CONSTRUCCIÓN DE UI
    # =========================================================================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(12)
        root.setContentsMargins(12, 12, 12, 12)

        root.addWidget(self._build_left_panel(), stretch=0)
        root.addWidget(self._build_right_panel(), stretch=1)

    # ── Panel izquierdo: parámetros + cálculo + recarga + controles ──────────
    def _build_left_panel(self) -> QWidget:
        # Scroll area para acomodar todas las secciones sin recortar
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(400)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        layout.setContentsMargins(4, 4, 8, 4)

        # ── Banner: sin filamento ────────────────────────────────────────────
        self.lbl_no_wire_banner = QLabel("⚠  SIN FILAMENTO — Solo modo recarga habilitado")
        self.lbl_no_wire_banner.setAlignment(Qt.AlignCenter)
        self.lbl_no_wire_banner.setWordWrap(True)
        self.lbl_no_wire_banner.setStyleSheet(
            "background:#c0392b; color:white; border-radius:5px; padding:7px 6px;"
            "font-weight:bold; font-size:12px; letter-spacing:0.5px;"
        )
        self.lbl_no_wire_banner.setVisible(False)
        layout.addWidget(self.lbl_no_wire_banner)

        # ── Grupo parámetros ────────────────────────────────────────────────
        self.grp_params = QGroupBox("Parámetros del toroide")
        grid = QGridLayout(self.grp_params)
        grid.setColumnStretch(1, 1)

        def lbl(text):
            l = QLabel(text)
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return l

        # D. Externo
        grid.addWidget(lbl("D. Externo (mm):"), 0, 0)
        self.spin_od = QDoubleSpinBox()
        self.spin_od.setRange(30.0, 70.0)
        self.spin_od.setSingleStep(0.5)
        self.spin_od.setDecimals(1)
        self.spin_od.setValue(50.0)
        grid.addWidget(self.spin_od, 0, 1)

        # D. Interno
        grid.addWidget(lbl("D. Interno (mm):"), 1, 0)
        self.spin_id = QDoubleSpinBox()
        self.spin_id.setRange(25.0, 60.0)
        self.spin_id.setSingleStep(0.5)
        self.spin_id.setDecimals(1)
        self.spin_id.setValue(30.0)
        grid.addWidget(self.spin_id, 1, 1)

        # Altura
        grid.addWidget(lbl("Altura (mm):"), 2, 0)
        self.spin_h = QDoubleSpinBox()
        self.spin_h.setRange(5.0, 30.0)
        self.spin_h.setSingleStep(0.5)
        self.spin_h.setDecimals(1)
        self.spin_h.setValue(20.0)
        grid.addWidget(self.spin_h, 2, 1)

        # Vueltas objetivo
        grid.addWidget(lbl("Vueltas objetivo:"), 3, 0)
        self.spin_turns = QSpinBox()
        self.spin_turns.setRange(10, 100)
        self.spin_turns.setSingleStep(10)
        self.spin_turns.setValue(100)
        grid.addWidget(self.spin_turns, 3, 1)

        # Velocidad
        grid.addWidget(lbl("Velocidad (%):"), 4, 0)
        self.spin_speed = QSpinBox()
        self.spin_speed.setRange(VEL_MIN, VEL_MAX)
        self.spin_speed.setSingleStep(VEL_STEP)
        self.spin_speed.setValue(70)
        self.spin_speed.setSuffix(" %")
        grid.addWidget(self.spin_speed, 4, 1)

        # Diám. alambre (fijo)
        grid.addWidget(lbl("Diám. alambre:"), 5, 0)
        lbl_wire = QLabel("0.5 mm  (fijo)")
        lbl_wire.setStyleSheet("color:#888;")
        grid.addWidget(lbl_wire, 5, 1)

        layout.addWidget(self.grp_params)

        # ── Advertencia de geometría ─────────────────────────────────────────
        self.lbl_geometry_warn = QLabel("")
        self.lbl_geometry_warn.setAlignment(Qt.AlignCenter)
        self.lbl_geometry_warn.setStyleSheet(
            "color:white; background:#c0392b; border-radius:4px; padding:4px; font-weight:bold;"
        )
        self.lbl_geometry_warn.setVisible(False)
        layout.addWidget(self.lbl_geometry_warn)

        # ── Resultado de cálculo ──────────────────────────────────────────────
        # Flujo visual: Params → Geo warn → [Resultado cálculo] → Recarga → Ctrl
        self.grp_calc = QGroupBox("Resultado de cálculo")
        cg = QGridLayout(self.grp_calc)

        def clbl(text):
            l = QLabel(text)
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return l

        cg.addWidget(clbl("Long. de alambre:"), 0, 0)
        self.lbl_wire_len = QLabel("---")
        cg.addWidget(self.lbl_wire_len, 0, 1)

        cg.addWidget(clbl("Capas usadas:"), 1, 0)
        self.lbl_max_layers = QLabel("---")
        cg.addWidget(self.lbl_max_layers, 1, 1)

        cg.addWidget(clbl("Capacidad total:"), 2, 0)
        self.lbl_total_cap = QLabel("---")
        cg.addWidget(self.lbl_total_cap, 2, 1)

        cg.addWidget(clbl("Vueltas/capa:"), 3, 0)
        self.lbl_turns_per_layer = QLabel("---")
        self.lbl_turns_per_layer.setWordWrap(True)
        cg.addWidget(self.lbl_turns_per_layer, 3, 1)

        cg.addWidget(clbl("Advertencia:"), 4, 0)
        self.lbl_calc_warn = QLabel("")
        self.lbl_calc_warn.setStyleSheet("color:#e67e22;")
        cg.addWidget(self.lbl_calc_warn, 4, 1)

        layout.addWidget(self.grp_calc)

        # ── Grupo botones de control ─────────────────────────────────────────
        self.grp_ctrl = QGroupBox("Control")
        btn_grid = QGridLayout(self.grp_ctrl)

        self.btn_calc  = self._make_btn("Calcular",  "#2980b9")
        self.btn_start = self._make_btn("Iniciar",   "#27ae60")
        self.btn_pause = self._make_btn("Pausar",    "#e67e22")
        self.btn_stop  = self._make_btn("Detener",   "#c0392b")
        self.btn_reset = self._make_btn("Reset",     "#7f8c8d")

        btn_grid.addWidget(self.btn_calc,  0, 0, 1, 2)
        btn_grid.addWidget(self.btn_start, 1, 0)
        btn_grid.addWidget(self.btn_pause, 1, 1)
        btn_grid.addWidget(self.btn_stop,  2, 0)
        btn_grid.addWidget(self.btn_reset, 2, 1)

        self.btn_calc.clicked.connect(self.cmd_calculate)
        self.btn_start.clicked.connect(self.cmd_start)
        self.btn_pause.clicked.connect(self.cmd_pause)
        self.btn_stop.clicked.connect(self.cmd_stop)
        self.btn_reset.clicked.connect(self.cmd_reset)

        # grp_ctrl se agrega al layout DESPUÉS del bloque de recarga (ver abajo)

        # ── Modo Recarga ──────────────────────────────────────────────────────
        self.grp_reload = QGroupBox("♻ Modo Recarga (carrete)")
        self.grp_reload.setStyleSheet(
            "QGroupBox { border:2px solid #7d3c98; border-radius:6px; "
            "margin-top:8px; font-weight:bold; color:#a569bd; }"
            "QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; }"
        )
        rg = QGridLayout(self.grp_reload)
        rg.setColumnStretch(1, 1)

        def rlbl(text):
            l = QLabel(text)
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return l

        # Longitud a recargar
        rg.addWidget(rlbl("Longitud (cm):"), 0, 0)
        self.spin_reload_len = QSpinBox()
        self.spin_reload_len.setRange(10, 3000)
        self.spin_reload_len.setSingleStep(10)
        self.spin_reload_len.setValue(300)
        self.spin_reload_len.setSuffix(" cm")
        self.spin_reload_len.valueChanged.connect(self._update_reload_turns_label)
        rg.addWidget(self.spin_reload_len, 0, 1)

        # Vueltas calculadas
        rg.addWidget(rlbl("Vueltas calc.:"), 1, 0)
        self.lbl_reload_turns_calc = QLabel("10 vueltas")
        self.lbl_reload_turns_calc.setStyleSheet("color:#a569bd; font-weight:bold;")
        rg.addWidget(self.lbl_reload_turns_calc, 1, 1)

        # Progreso de recarga
        rg.addWidget(rlbl("Progreso:"), 2, 0)
        self.progress_reload = QProgressBar()
        self.progress_reload.setRange(0, 100)
        self.progress_reload.setValue(0)
        self.progress_reload.setTextVisible(True)
        self.progress_reload.setStyleSheet(
            "QProgressBar::chunk { background:#7d3c98; }"
        )
        rg.addWidget(self.progress_reload, 2, 1)

        # Estado recarga
        rg.addWidget(rlbl("Estado:"), 3, 0)
        self.lbl_reload_state = QLabel("Inactivo")
        self.lbl_reload_state.setStyleSheet("color:#7f8c8d; font-weight:bold;")
        rg.addWidget(self.lbl_reload_state, 3, 1)

        # Métricas (vueltas hechas / objetivo)
        rg.addWidget(rlbl("Vueltas:"), 4, 0)
        self.lbl_reload_progress = QLabel("0 / 0")
        rg.addWidget(self.lbl_reload_progress, 4, 1)

        # Botones recarga  (verde=iniciar · naranja=pausar · rojo=cancelar)
        self.btn_reload_start  = self._make_btn("▶ Iniciar Recarga",  "#27ae60")
        self.btn_reload_pause  = self._make_btn("⏸ Pausar",           "#e67e22")
        self.btn_reload_cancel = self._make_btn("✕ Cancelar",         "#c0392b")

        rg.addWidget(self.btn_reload_start,  5, 0, 1, 2)
        rg.addWidget(self.btn_reload_pause,  6, 0)
        rg.addWidget(self.btn_reload_cancel, 6, 1)

        self.btn_reload_start.clicked.connect(self.cmd_reload_start)
        self.btn_reload_pause.clicked.connect(self.cmd_reload_pause)
        self.btn_reload_cancel.clicked.connect(self.cmd_reload_reset)

        layout.addWidget(self.grp_reload)

        # ── Controles de ejecución ────────────────────────────────────────────
        layout.addWidget(self.grp_ctrl)

        # Inicializar etiqueta de vueltas calculadas
        self._update_reload_turns_label()

        # ── Indicadores de conexión ──────────────────────────────────────────
        conn_box = QGroupBox("Conexión")
        conn_layout = QGridLayout(conn_box)
        conn_layout.setContentsMargins(8, 6, 8, 6)

        conn_layout.addWidget(QLabel("Broker MQTT:"), 0, 0)
        self.lbl_mqtt_status = QLabel("● Conectando…")
        self.lbl_mqtt_status.setStyleSheet("color:#e67e22; font-weight:bold;")
        conn_layout.addWidget(self.lbl_mqtt_status, 0, 1)

        conn_layout.addWidget(QLabel("ESP32 / HMI física:"), 1, 0)
        self.lbl_esp32_status = QLabel("○ Sin datos")
        self.lbl_esp32_status.setStyleSheet("color:#7f8c8d; font-weight:bold;")
        conn_layout.addWidget(self.lbl_esp32_status, 1, 1)

        conn_layout.addWidget(QLabel("Último status:"), 2, 0)
        self.lbl_last_seen = QLabel("—")
        self.lbl_last_seen.setStyleSheet("color:#7f8c8d; font-size:11px;")
        conn_layout.addWidget(self.lbl_last_seen, 2, 1)

        layout.addWidget(conn_box)

        # ── Indicador de alambre ─────────────────────────────────────────────
        self.lbl_wire_sensor = QLabel("● Sensor alambre: —")
        self.lbl_wire_sensor.setAlignment(Qt.AlignCenter)
        self.lbl_wire_sensor.setStyleSheet(
            "background:#1e2025; color:#7f8c8d; border-radius:4px; padding:4px;"
            "font-weight:bold; font-size:12px;"
        )
        layout.addWidget(self.lbl_wire_sensor)

        layout.addStretch()
        scroll.setWidget(panel)
        return scroll

    # ── Panel derecho: estado + cálculo + log ────────────────────────────────
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # ── Estado del sistema ───────────────────────────────────────────────
        grp_state = QGroupBox("Estado del sistema")
        sg = QGridLayout(grp_state)

        sg.addWidget(QLabel("Estado:"), 0, 0)
        self.lbl_state = QLabel("---")
        self.lbl_state.setFont(QFont("Arial", 14, QFont.Bold))
        sg.addWidget(self.lbl_state, 0, 1)

        sg.addWidget(QLabel("Progreso:"), 1, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        sg.addWidget(self.progress_bar, 1, 1)

        sg.addWidget(QLabel("Vueltas hechas:"),     2, 0)
        self.lbl_turns_done = QLabel("0")
        sg.addWidget(self.lbl_turns_done, 2, 1)

        sg.addWidget(QLabel("Vueltas restantes:"),  3, 0)
        self.lbl_turns_rem = QLabel("0")
        sg.addWidget(self.lbl_turns_rem, 3, 1)

        sg.addWidget(QLabel("Velocidad activa:"),   4, 0)
        self.lbl_speed_active = QLabel("---")
        sg.addWidget(self.lbl_speed_active, 4, 1)

        sg.addWidget(QLabel("Cálculo:"),            5, 0)
        self.lbl_calc_flag = QLabel("Pendiente")
        sg.addWidget(self.lbl_calc_flag, 5, 1)

        sg.addWidget(QLabel("Modo operación:"),      6, 0)
        self.lbl_modo = QLabel("Bobinado")
        self.lbl_modo.setStyleSheet("color:#2980b9; font-weight:bold;")
        sg.addWidget(self.lbl_modo, 6, 1)

        sg.addWidget(QLabel("Advertencia:"),        7, 0)
        self.lbl_warning = QLabel("")
        self.lbl_warning.setStyleSheet("color:#c0392b; font-weight:bold;")
        sg.addWidget(self.lbl_warning, 7, 1)

        layout.addWidget(grp_state)

        # ── Log MQTT ─────────────────────────────────────────────────────────
        # (Resultado de cálculo movido al panel izquierdo — flujo visual correcto)
        grp_log = QGroupBox("Log MQTT")
        lg = QVBoxLayout(grp_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(180)
        self.txt_log.setFont(QFont("Courier", 9))
        lg.addWidget(self.txt_log)
        layout.addWidget(grp_log)

        # ── Conectar señales de validación ───────────────────────────────────
        self.spin_od.valueChanged.connect(self._validate_geometry_local)
        self.spin_id.valueChanged.connect(self._validate_geometry_local)

        return panel

    # ── Helper botones con estilo ─────────────────────────────────────────────
    @staticmethod
    def _make_btn(text: str, color: str) -> QPushButton:
        b = QPushButton(text)
        b.setMinimumHeight(36)
        b.setStyleSheet(
            f"QPushButton {{ background:{color}; color:white; border-radius:5px; "
            f"font-weight:bold; font-size:13px; }}"
            f"QPushButton:disabled {{ background:#bdc3c7; color:#888; }}"
            f"QPushButton:hover {{ opacity:0.85; }}"
        )
        return b

    # =========================================================================
    #  RECARGA — helper etiqueta de vueltas calculadas
    # =========================================================================
    def _update_reload_turns_label(self):
        import math
        cm  = self.spin_reload_len.value()
        turns = math.ceil(cm / CM_POR_VUELTA)
        self.lbl_reload_turns_calc.setText(f"{turns} vueltas")

    # =========================================================================
    #  BLOQUEO POR ESTADO DE FILAMENTO (FilamentState FSM)
    # =========================================================================
    def _set_wire_blocking(self, filament_lock_active: bool, reload_required: bool):
        """
        Gestiona el bloqueo de secciones según el estado de filamento del ESP32.

        filament_lock_active=True → SIN filamento → bloquear TODO (incluida recarga)
        reload_required=True      → filamento vuelve → SOLO recarga habilitada
        ambos False               → operación normal → todo habilitado
        """
        DISABLED_TIP = "Opción deshabilitada: falta filamento"
        RED_STYLE   = ("background:#c0392b; color:white; border-radius:5px; "
                       "padding:7px 6px; font-weight:bold; font-size:12px; "
                       "letter-spacing:0.5px;")
        ORG_STYLE   = ("background:#e67e22; color:white; border-radius:5px; "
                       "padding:7px 6px; font-weight:bold; font-size:12px; "
                       "letter-spacing:0.5px;")

        if filament_lock_active:
            # ── SIN filamento: TODO bloqueado, ni siquiera se puede recargar ──
            self.lbl_no_wire_banner.setVisible(True)
            self.lbl_no_wire_banner.setText(
                "🚨  SIN FILAMENTO — Inserte alambre para habilitar recarga"
            )
            self.lbl_no_wire_banner.setStyleSheet(RED_STYLE)
            self.grp_params.setEnabled(False)
            self.grp_params.setToolTip(DISABLED_TIP)
            self.grp_calc.setEnabled(False)
            self.grp_calc.setToolTip(DISABLED_TIP)
            self.grp_reload.setEnabled(False)
            self.grp_reload.setToolTip("Sin filamento — no se puede iniciar recarga")
            self.grp_ctrl.setEnabled(False)
            self.grp_ctrl.setToolTip(DISABLED_TIP)

        elif reload_required:
            # ── Filamento detectado: SOLO recarga habilitada hasta que termine ─
            self.lbl_no_wire_banner.setVisible(True)
            self.lbl_no_wire_banner.setText(
                "♻  Configure y complete la recarga para volver al modo normal"
            )
            self.lbl_no_wire_banner.setStyleSheet(ORG_STYLE)
            self.grp_params.setEnabled(False)
            self.grp_params.setToolTip(DISABLED_TIP)
            self.grp_calc.setEnabled(False)
            self.grp_calc.setToolTip(DISABLED_TIP)
            self.grp_reload.setEnabled(True)
            self.grp_reload.setToolTip("")
            # Cancelar recarga no permitido en modo obligatorio
            self.btn_reload_cancel.setEnabled(False)
            self.btn_reload_cancel.setToolTip("No se puede cancelar: recarga obligatoria")
            self.grp_ctrl.setEnabled(False)
            self.grp_ctrl.setToolTip(DISABLED_TIP)

        else:
            # ── Operación normal ─────────────────────────────────────────────
            self.lbl_no_wire_banner.setVisible(False)
            self.grp_params.setEnabled(True)
            self.grp_params.setToolTip("")
            self.grp_calc.setEnabled(True)
            self.grp_calc.setToolTip("")
            self.grp_reload.setEnabled(True)
            self.grp_reload.setToolTip("")
            self.btn_reload_cancel.setEnabled(True)
            self.btn_reload_cancel.setToolTip("")
            self.grp_ctrl.setEnabled(True)
            self.grp_ctrl.setToolTip("")

    # =========================================================================
    #  VALIDACIÓN GEOMÉTRICA LOCAL (sin enviar MQTT)
    # =========================================================================
    def _validate_geometry_local(self):
        od  = self.spin_od.value()
        id_ = self.spin_id.value()
        if id_ >= od:
            self.lbl_geometry_warn.setText(f"ERROR: D.Int ({id_}) ≥ D.Ext ({od})")
            self.lbl_geometry_warn.setVisible(True)
            self.btn_calc.setEnabled(False)
            self.btn_start.setEnabled(False)
        else:
            self.lbl_geometry_warn.setVisible(False)
            self.btn_calc.setEnabled(True)
            self.btn_start.setEnabled(True)

    # =========================================================================
    #  SLOTS MQTT  (ejecutados en el hilo Qt principal gracias a Signal/Slot)
    # =========================================================================
    @Slot()
    def on_mqtt_connected(self):
        self.lbl_mqtt_status.setText("● Conectado")
        self.lbl_mqtt_status.setStyleSheet("color:#27ae60; font-weight:bold;")

    @Slot()
    def on_mqtt_disconnected(self):
        self.lbl_mqtt_status.setText("○ Desconectado")
        self.lbl_mqtt_status.setStyleSheet("color:#c0392b; font-weight:bold;")
        # Si MQTT cae, el ESP32 también queda offline
        self._set_esp32_offline()

    def _check_esp32_connection(self):
        """Revisa periódicamente si el ESP32 sigue mandando status."""
        if self._last_esp32_seen == 0:
            return  # nunca recibimos nada aún
        elapsed = time.time() - self._last_esp32_seen
        if elapsed > ESP32_TIMEOUT_S:
            self._set_esp32_offline()
        elif elapsed > 2:
            # Sigue online pero han pasado varios segundos → mostrar tiempo
            self.lbl_last_seen.setText(f"hace {int(elapsed)} s")
            self.lbl_last_seen.setStyleSheet("color:#e67e22; font-size:11px;")

    def _set_esp32_offline(self):
        elapsed = int(time.time() - self._last_esp32_seen) if self._last_esp32_seen else 0
        self.lbl_esp32_status.setText("○ Sin respuesta")
        self.lbl_esp32_status.setStyleSheet("color:#c0392b; font-weight:bold;")
        self.lbl_last_seen.setText(f"hace {elapsed} s" if elapsed else "—")
        self.lbl_last_seen.setStyleSheet("color:#c0392b; font-size:11px;")
        self.lbl_wire_sensor.setText("● Sensor alambre: —")
        self.lbl_wire_sensor.setStyleSheet(
            "background:#1e2025; color:#7f8c8d; border-radius:4px; padding:4px;"
            "font-weight:bold; font-size:12px;"
        )

    @Slot(dict)
    def on_status_received(self, data: dict):
        """Actualiza la UI con el estado publicado por el ESP32."""
        # Registrar timestamp → usado para detectar ESP32 offline
        self._last_esp32_seen = time.time()
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.lbl_last_seen.setText(ts)
        self.lbl_last_seen.setStyleSheet("color:#27ae60; font-size:11px;")
        self.lbl_esp32_status.setText("● Conectado (HMI física)")
        self.lbl_esp32_status.setStyleSheet("color:#27ae60; font-weight:bold;")

        # Activar flag para que los valueChanged de los spinboxes
        # no disparen comandos MQTT de vuelta al ESP32
        self._updating_from_mqtt = True
        try:
            self._apply_status(data)
        finally:
            self._updating_from_mqtt = False

    def _apply_status(self, data: dict):
        state         = data.get("state", "unknown")
        turns_done    = data.get("turns_done", 0)
        turns_rem     = data.get("turns_remaining", 0)
        progress      = int(data.get("progress_percent", 0))
        speed         = data.get("speed", 0)
        calc_pending  = data.get("calculation_pending", True)
        geo_valid     = data.get("geometry_valid", True)
        warning       = data.get("warning", "")

        # Estado con color
        COLOR_MAP = {
            "ready":     ("#27ae60",  "READY"),
            "running":   ("#2980b9",  "RUNNING"),
            "paused":    ("#e67e22",  "PAUSED"),
            "stopped":   ("#c0392b",  "STOPPED"),
            "complete":  ("#8e44ad",  "COMPLETE"),
            "emergency": ("#c0392b",  "EMERGENCY"),
        }
        color, label = COLOR_MAP.get(state, ("#555", state.upper()))
        self.lbl_state.setText(label)
        self.lbl_state.setStyleSheet(f"color:{color};")

        self.progress_bar.setValue(progress)
        self.progress_bar.setFormat(f"{progress}%")
        self.lbl_turns_done.setText(str(turns_done))
        self.lbl_turns_rem.setText(str(turns_rem))
        self.lbl_speed_active.setText(f"{speed}%")
        self.lbl_calc_flag.setText("Listo" if not calc_pending else "Pendiente")
        self.lbl_calc_flag.setStyleSheet(
            "color:#27ae60;" if not calc_pending else "color:#e67e22;"
        )
        self.lbl_warning.setText(warning)

        # ── Sensor de alambre ─────────────────────────────────────────────
        wire_present = data.get("wire_present", None)
        if wire_present is True:
            self.lbl_wire_sensor.setText("● Sensor alambre: PRESENTE")
            self.lbl_wire_sensor.setStyleSheet(
                "background:#152d1f; color:#27ae60; border-radius:4px; padding:4px;"
                "font-weight:bold; font-size:12px;"
            )
        elif wire_present is False:
            self.lbl_wire_sensor.setText("● Sensor alambre: AUSENTE")
            self.lbl_wire_sensor.setStyleSheet(
                "background:#2d1515; color:#e74c3c; border-radius:4px; padding:4px;"
                "font-weight:bold; font-size:12px;"
            )

        # ── Bloquear/desbloquear secciones según estado de filamento ─────────
        filament_lock_active = data.get("filament_lock_active", False)
        reload_required      = data.get("reload_required",      False)
        self._set_wire_blocking(filament_lock_active, reload_required)

        # Geometría desde ESP32
        if not geo_valid:
            self.lbl_geometry_warn.setText("ERROR geometría reportado por ESP32")
            self.lbl_geometry_warn.setVisible(True)
        # No forzamos visible(False) aquí; la validación local lo maneja

        # ── Sincronizar parámetros: ESP32 → HMI virtual ───────────────────
        cfg = data.get("config", {})
        if cfg:
            od  = cfg.get("outer_diameter")
            id_ = cfg.get("inner_diameter")
            h   = cfg.get("height")
            t   = cfg.get("target_turns")
            spd = cfg.get("speed")

            if od  is not None: self.spin_od.setValue(float(od))
            if id_ is not None: self.spin_id.setValue(float(id_))
            if h   is not None: self.spin_h.setValue(float(h))
            if t   is not None: self.spin_turns.setValue(int(t))
            if spd is not None:
                spd_int = max(VEL_MIN, min(VEL_MAX, int(spd)))
                self.spin_speed.setValue(spd_int)

        # ── Modo de operación ─────────────────────────────────────────────
        modo = data.get("modo", "bobinado")
        if modo == "recarga":
            self.lbl_modo.setText("♻ Recarga")
            self.lbl_modo.setStyleSheet("color:#a569bd; font-weight:bold;")
        else:
            self.lbl_modo.setText("Bobinado")
            self.lbl_modo.setStyleSheet("color:#2980b9; font-weight:bold;")

        # ── Estado de recarga ─────────────────────────────────────────────
        modo          = data.get("modo", "bobinado")
        reload_done   = data.get("reload_done", 0)
        reload_target = data.get("reload_target", 0)
        reload_len_cm = data.get("reload_length_cm", None)

        if modo == "recarga":
            # Sincronizar longitud si viene del ESP32
            if reload_len_cm is not None:
                self.spin_reload_len.setValue(int(reload_len_cm))

            # Etiqueta de estado
            RELOAD_STATE_MAP = {
                "ready":     ("LISTO",       "#a569bd"),
                "running":   ("RECARGANDO",  "#7d3c98"),
                "paused":    ("PAUSADO",     "#e67e22"),
                "stopped":   ("DETENIDO",    "#c0392b"),
                "complete":  ("COMPLETO ✓",  "#27ae60"),
                "emergency": ("EMERGENCIA",  "#c0392b"),
            }
            rs_color = RELOAD_STATE_MAP.get(state, ("---", "#7f8c8d"))
            self.lbl_reload_state.setText(rs_color[0])
            self.lbl_reload_state.setStyleSheet(f"color:{rs_color[1]}; font-weight:bold;")

            # Progreso
            if reload_target > 0:
                pct = min(100, int(reload_done * 100 / reload_target))
                self.progress_reload.setValue(pct)
                self.progress_reload.setFormat(f"{pct}%")
                self.lbl_reload_progress.setText(f"{reload_done} / {reload_target}")
            else:
                self.progress_reload.setValue(0)
                self.lbl_reload_progress.setText("0 / 0")
        else:
            # Modo bobinado normal — resetear indicadores de recarga si no estamos en ese modo
            self.lbl_reload_state.setText("Inactivo")
            self.lbl_reload_state.setStyleSheet("color:#7f8c8d; font-weight:bold;")

        # Re-validar geometría con los nuevos valores
        self._validate_geometry_local()

    @Slot(dict)
    def on_calc_received(self, data: dict):
        """Muestra el resultado de cálculo publicado por el ESP32."""
        wire_len  = data.get("wire_length_m", 0)
        max_lyr   = data.get("max_layers", 0)
        total_cap = data.get("total_capacity", 0)
        tpl       = data.get("turns_per_layer", "---")
        warn      = data.get("warning", "")

        self.lbl_wire_len.setText(f"{wire_len:.2f} m")
        self.lbl_max_layers.setText(str(max_lyr))
        self.lbl_total_cap.setText(str(total_cap))
        self.lbl_turns_per_layer.setText(tpl if tpl else "---")
        self.lbl_calc_warn.setText(warn)

    @Slot(str)
    def append_log(self, msg: str):
        self.txt_log.append(msg)
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum()
        )

    # =========================================================================
    #  ENVÍO DE COMANDOS MQTT
    # =========================================================================
    def cmd_calculate(self):
        """Envía 'calculate' con los parámetros actuales de la HMI virtual."""
        if self._updating_from_mqtt:
            return
        od  = self.spin_od.value()
        id_ = self.spin_id.value()
        if id_ >= od:
            self.lbl_geometry_warn.setText("ERROR: D.Int >= D.Ext — no se puede calcular")
            self.lbl_geometry_warn.setVisible(True)
            return
        payload = {
            "cmd": "calculate",
            "toroid": {
                "outer_diameter": od,
                "inner_diameter": id_,
                "height":         self.spin_h.value(),
            },
            "wire_diameter": 0.5,
            "target_turns":  self.spin_turns.value(),
        }
        self.mqtt_worker.publish(payload)

    def cmd_start(self):
        """Envía 'start' con la velocidad seleccionada."""
        if self._updating_from_mqtt:
            return
        speed = self.spin_speed.value()
        self.mqtt_worker.publish({"cmd": "start", "speed": speed})

    def cmd_pause(self):
        self.mqtt_worker.publish({"cmd": "pause"})

    def cmd_stop(self):
        self.mqtt_worker.publish({"cmd": "stop"})

    def cmd_reset(self):
        self.mqtt_worker.publish({"cmd": "reset"})

    def cmd_reload_start(self):
        """Inicia el modo recarga con la longitud configurada."""
        if self._updating_from_mqtt:
            return
        import math
        length_cm = self.spin_reload_len.value()
        turns     = math.ceil(length_cm / CM_POR_VUELTA)
        self.mqtt_worker.publish({
            "cmd":           "reload_start",
            "length_cm":     length_cm,
            "target_turns":  turns,
            "speed":         self.spin_speed.value(),
        })

    def cmd_reload_pause(self):
        """Pausa/reanuda la recarga en curso."""
        self.mqtt_worker.publish({"cmd": "reload_pause"})

    def cmd_reload_reset(self):
        """Cancela la recarga y vuelve al modo bobinado."""
        self.mqtt_worker.publish({"cmd": "reload_reset"})

    # =========================================================================
    #  CIERRE
    # =========================================================================
    def closeEvent(self, event):
        self.mqtt_worker.disconnect()
        super().closeEvent(event)


# =============================================================================
#  PUNTO DE ENTRADA
# =============================================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Paleta clara — compatible con PySide6 6.4+
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window,        QColor(245, 245, 248))
    palette.setColor(QPalette.ColorRole.WindowText,    QColor(30,  30,  30))
    palette.setColor(QPalette.ColorRole.Base,          QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(235, 235, 240))
    palette.setColor(QPalette.ColorRole.Button,        QColor(220, 220, 225))
    palette.setColor(QPalette.ColorRole.ButtonText,    QColor(30,  30,  30))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
