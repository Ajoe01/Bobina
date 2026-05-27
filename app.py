from flask import Flask, render_template_string, request, jsonify
import paho.mqtt.client as mqtt
import json
import threading
import time

app = Flask(__name__)

MQTT_BROKER   = "broker.hivemq.com"
MQTT_PORT     = 1883
TOPIC_CMD     = "bobibobiutb/cmd"
TOPIC_STATUS  = "bobibobiutb/status"

mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

latest_status = {
    "type": "status",
    "turns_done": 0,
    "turns_remaining": 0,
    "turns_total": 0,
    "state": "ready",
    "endstop": False,
    "hall": False,
    "speed": 0,
    "direction": "S",
    "modo": "bobinado",
    "reload_done": 0,
    "reload_target": 0,
    "reload_length_cm": 300,
    "filament_lock_active": False,
    "reload_required": False,
    "filament_state": "startup"
}

calculation_result = {
    "wire_length_m": 0,
    "turns_per_layer": 0,
    "max_layers": 0,
    "total_capacity": 0,
    "warning": ""
}

def on_message(client, userdata, msg):
    global latest_status, calculation_result
    try:
        data = json.loads(msg.payload.decode())
        print(f"[MQTT←] {data}")
        if data.get("type") == "status":
            latest_status.update(data)
        elif data.get("type") == "calculation":
            calculation_result = {
                "wire_length_m":  data.get("wire_length_m", 0),
                "turns_per_layer": data.get("turns_per_layer", 0),
                "max_layers":     data.get("max_layers", 0),
                "total_capacity": data.get("total_capacity", 0),
                "warning":        data.get("warning", "")
            }
    except Exception as e:
        print(f"[MQTT] Error procesando mensaje: {e}")

mqtt_client.on_message = on_message
mqtt_client.subscribe(TOPIC_STATUS)
mqtt_client.loop_start()

# ─────────────────────────────────────────────────────────────────────────────
#  PLANTILLA HTML
# ─────────────────────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SISTEMA DE CONTROL - EMBOBINADORA TOROIDAL</title>
    <style>
        :root {
            --gris-maquina: #b0b0b0;
            --gris-oscuro:  #808080;
            --gris-claro:   #d9d9d9;
            --azul-utb:     #0033a0;
            --negro-panel:  #1a1a1a;
            --blanco-puro:  #ffffff;
            --rojo-error:   #c0392b;
            --verde-ok:     #27ae60;
        }

        * { margin:0; padding:0; box-sizing:border-box; font-family:'Courier New',Courier,monospace; }
        body { background-color:#ffffff; color:var(--negro-panel); padding:20px; }

        .container {
            max-width:1200px; margin:0 auto;
            background-color:#ffffff;
            border:4px solid var(--gris-claro);
            border-right-color:var(--gris-oscuro);
            border-bottom-color:var(--gris-oscuro);
            padding:15px;
            box-shadow:10px 10px 0px rgba(0,0,0,0.15);
        }

        header {
            background-color:var(--azul-utb); color:var(--blanco-puro);
            padding:15px; border:3px inset rgba(255,255,255,0.2);
            margin-bottom:20px;
            display:flex; justify-content:space-between; align-items:center;
        }
        header h1 { font-size:1.8em; letter-spacing:-1px; }
        header .subtitle {
            font-size:0.8em; text-transform:uppercase;
            border-top:1px solid var(--blanco-puro);
            padding-top:5px; margin-top:5px;
        }

        /* Badge de estado del servidor */
        .srv-badge {
            font-size:0.75em; font-weight:bold; padding:5px 12px;
            border:2px outset rgba(255,255,255,0.3); white-space:nowrap;
            text-align:center; min-width:130px;
        }
        .srv-badge.online  { background:#1a5c1a; color:#00ff00; }
        .srv-badge.offline { background:#5c1a1a; color:#ff6666; }

        .grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; }

        .card {
            background-color:#ffffff;
            border:3px outset var(--gris-claro); padding:20px;
        }
        .card h2 {
            background-color:var(--gris-oscuro); color:var(--blanco-puro);
            font-size:1em; padding:5px 10px; margin-bottom:15px;
            border:2px inset var(--gris-claro);
        }

        /* ── Reload card ── */
        .reload-card {
            background-color:#ffffff;
            border:3px outset var(--gris-claro);
            padding:20px; margin-top:15px;
        }
        .reload-card h2 {
            background-color:var(--gris-oscuro); color:var(--blanco-puro);
            font-size:1em; padding:5px 10px; margin-bottom:15px;
            border:2px inset var(--gris-claro);
        }
        .reload-progress-container {
            background:#222; border:2px solid #00ff00;
            height:26px; margin:8px 0; display:none;
        }
        .reload-progress-bar {
            height:100%; background-color:#00ff00; color:black; font-weight:bold;
            display:flex; align-items:center; justify-content:center;
            min-width:30px; transition:width 0.5s ease;
        }
        .reload-info-grid {
            display:grid; grid-template-columns:1fr 1fr 1fr; gap:5px; margin:8px 0;
        }
        .reload-info-item {
            border:1px solid #004400; padding:5px;
            font-size:0.8em; background:var(--negro-panel); color:#00ff00;
        }
        .reload-state-display {
            background:var(--negro-panel); color:#00ff00;
            border:2px solid #00ff00; padding:6px 10px;
            font-size:0.85em; margin-bottom:8px; text-align:center; display:none;
        }
        .btn-reload-start  { background-color:var(--azul-utb); color:white; width:100%; margin-bottom:8px; }
        .btn-reload-pause  { background-color:#f1c40f; color:black; }
        .btn-reload-cancel { background-color:var(--gris-oscuro); color:white; }

        .input-group {
            margin-bottom:10px; display:flex;
            align-items:center; justify-content:space-between; flex-wrap:wrap; gap:4px;
        }
        label { font-weight:bold; font-size:0.85em; text-transform:uppercase; flex:1; }

        input[type="number"] {
            width:100px; background-color:var(--blanco-puro);
            border:3px inset var(--gris-oscuro); padding:5px; font-weight:bold;
            color:var(--negro-panel); text-align:center; transition:border-color 0.2s;
        }
        input.input-error { border-color:var(--rojo-error)!important; background-color:#fdecea; }
        input.input-ok    { border-color:var(--verde-ok)!important; }

        .field-error {
            font-size:0.72em; color:var(--rojo-error);
            font-weight:bold; width:100%; text-align:right; display:none;
        }
        .field-error.visible { display:block; }

        button {
            border:4px outset var(--gris-claro); background-color:var(--gris-claro);
            padding:12px; font-weight:bold; cursor:pointer;
            text-transform:uppercase; transition:all 0.1s;
            font-family:'Courier New',Courier,monospace;
        }
        button:active   { border-style:inset; transform:translate(2px,2px); }
        button:disabled { opacity:0.4; cursor:not-allowed; transform:none!important; }

        .btn-calculate { background-color:var(--azul-utb); color:white; width:100%; margin-top:10px; }
        .button-group  { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        .btn-start { background-color:#2ecc71; color:white; }
        .btn-pause { background-color:#f1c40f; color:black; }
        .btn-stop  { background-color:#e74c3c; color:white; }
        .btn-reset { background-color:var(--gris-oscuro); color:white; }

        .toast {
            display:none; margin-top:10px; padding:8px 12px;
            font-size:0.82em; font-weight:bold; border-left:4px solid;
        }
        .toast.error   { background:#fdecea; border-color:var(--rojo-error); color:var(--rojo-error); display:block; }
        .toast.warning { background:#fff8e1; border-color:#f39c12;           color:#7d5a00;            display:block; }
        .toast.success { background:#eafaf1; border-color:var(--verde-ok);   color:#1a6e3a;            display:block; }

        /* Panel de estado */
        .status-panel {
            background-color:var(--negro-panel); color:#00ff00;
            border:6px solid var(--gris-oscuro); padding:15px;
        }
        .status-main {
            border:2px solid #00ff00; padding:10px;
            margin-bottom:15px; text-align:center;
        }
        .state-value { font-size:2em; font-weight:bold; }
        .progress-bar-container { background:#222; border:2px solid #00ff00; height:30px; margin:10px 0; }
        .progress-bar {
            height:100%; background-color:#00ff00; color:black; font-weight:bold;
            display:flex; align-items:center; justify-content:center; min-width:30px;
        }
        .info-grid { display:grid; grid-template-columns:1fr 1fr; gap:5px; }
        .info-item { border:1px solid #004400; padding:5px; font-size:0.8em; }
        .sensor-status { padding:2px 5px; border:1px solid #00ff00; }
        .sensor-active { background-color:#00ff00; color:black; }

        .checklist {
            background:var(--negro-panel); border:2px solid #444;
            padding:10px; margin-top:12px;
        }
        .checklist-title { color:#aaa; font-size:0.75em; margin-bottom:6px; text-transform:uppercase; }
        .check-item { font-size:0.78em; padding:3px 0; display:flex; align-items:center; gap:6px; }
        .check-ok   { color:#00ff00; }
        .check-fail { color:#ff4444; }
        .check-warn { color:#f1c40f; }

        .results-panel {
            background-color:var(--blanco-puro); border:3px inset var(--gris-oscuro);
            margin-top:15px; padding:10px; color:var(--negro-panel); display:none;
        }
        .result-item { border-bottom:1px dashed var(--gris-oscuro); padding:3px 0; font-size:0.85em; }

        /* ── Overlay bloqueo por falta de filamento ── */
        .block-wrap { position:relative; }
        .block-overlay {
            display:none; position:absolute;
            top:0; left:0; right:0; bottom:0;
            background:rgba(160,20,10,0.88);
            z-index:200; align-items:center; justify-content:center;
            border:4px solid #e74c3c;
        }
        .block-overlay.active { display:flex; }
        .block-msg {
            color:#ffffff; font-size:1.3em; font-weight:bold;
            text-align:center; padding:22px 28px;
            border:3px outset rgba(255,255,255,0.25);
            background:rgba(0,0,0,0.35); letter-spacing:3px;
            line-height:1.6; text-shadow:0 0 12px #ff2222;
        }
        .block-msg span {
            display:block; font-size:0.58em; letter-spacing:1px;
            margin-top:6px; color:#ffaaaa; font-weight:normal;
        }

        /* Banner global */
        #globalBlockBanner {
            display:none; background:#c0392b; color:white;
            font-weight:bold; font-size:1em; text-align:center;
            padding:10px; border:3px outset #e74c3c;
            margin-bottom:14px; letter-spacing:2px;
        }
        #globalBlockBanner.active { display:block; }

        footer {
            margin-top:20px; background-color:var(--gris-oscuro);
            color:var(--blanco-puro); padding:10px;
            font-size:0.7em; text-align:center;
            border:2px inset var(--gris-claro);
        }
    </style>
</head>
<body>
<div class="container">

    <header>
        <div>
            <h1>CONTROLADOR INDUSTRIAL V1.0 - UTB</h1>
            <div class="subtitle">Embedded System ESP32 // Toroidal Winding Control</div>
        </div>
        <div class="srv-badge offline" id="srvBadge">○ SIN SERVIDOR</div>
    </header>

    <!-- Banner global de bloqueo -->
    <div id="globalBlockBanner">🔒 &nbsp; SIN FILAMENTO — SISTEMA BLOQUEADO &nbsp; 🔒</div>

    <div class="grid">

        <!-- ═══ COLUMNA IZQUIERDA: PARÁMETROS + RECARGA ═══ -->
        <div class="block-wrap card" id="cardParams">
            <div class="block-overlay" id="overlayParams">
                <div class="block-msg">🔒 SISTEMA BLOQUEADO<span>Opción deshabilitada — falta filamento</span></div>
            </div>

            <h2>[ PARÁMETROS DE ENTRADA ]</h2>

            <div class="input-group">
                <label>D. EXTERIOR (mm)</label>
                <input type="number" id="outer"  value="59.5" min="1"    step="0.1"  oninput="validateField(this)">
                <span class="field-error" id="err-outer"></span>
            </div>
            <div class="input-group">
                <label>D. INTERIOR (mm)</label>
                <input type="number" id="inner"  value="39.5" min="1"    step="0.1"  oninput="validateField(this)">
                <span class="field-error" id="err-inner"></span>
            </div>
            <div class="input-group">
                <label>ALTURA (mm)</label>
                <input type="number" id="height" value="20"   min="0.1"  step="0.1"  oninput="validateField(this)">
                <span class="field-error" id="err-height"></span>
            </div>
            <div class="input-group">
                <label>D. ALAMBRE (mm)</label>
                <input type="number" id="wire"   value="0.3"  min="0.01" step="0.01" oninput="validateField(this)">
                <span class="field-error" id="err-wire"></span>
            </div>
            <div class="input-group">
                <label>VUELTAS OBJ.</label>
                <input type="number" id="turns"  value="5"    min="1"    step="1"    oninput="validateField(this)">
                <span class="field-error" id="err-turns"></span>
            </div>
            <div class="input-group">
                <label>MOTOR VEL (%)</label>
                <input type="number" id="speed"  value="70"   min="10"   max="100" step="1" oninput="validateField(this)">
                <span class="field-error" id="err-speed"></span>
            </div>

            <div class="toast" id="calcToast"></div>
            <button class="btn-calculate" onclick="calculate()">EJECUTAR CÁLCULO</button>

            <div class="results-panel" id="resultsPanel">
                <strong>>> REPORTE DE CÁLCULO:</strong>
                <div class="result-item">LONG. ALAMBRE:  <span id="wireLength">--</span></div>
                <div class="result-item">VUELTAS/CAPA:   <span id="turnsPerLayer">--</span></div>
                <div class="result-item">CAPAS MÁX:      <span id="maxLayers">--</span></div>
                <div class="result-item">CAPACIDAD TOT:  <span id="totalCapacity">--</span></div>
                <div id="warningMsg" style="color:red;font-weight:bold;margin-top:5px;"></div>
            </div>

            <!-- MODO RECARGA — debajo del reporte de cálculo -->
            <div class="reload-card" id="reloadCard">
                <h2>[ MODO RECARGA DE CARRETE ]</h2>
                <div class="input-group">
                    <label>LONGITUD (cm)</label>
                    <input type="number" id="reloadLen" value="300" min="10" max="3000" step="10"
                           oninput="updateReloadCalc()">
                </div>
                <div style="font-size:0.78em;margin:4px 0 10px;font-weight:bold;">
                    VUELTAS CALCULADAS:
                    <span id="reloadCalcTurns" style="color:var(--azul-utb);">10</span>
                    &nbsp;(30 cm/vuelta)
                </div>

                <div class="reload-state-display" id="reloadStateDisplay">
                    ESTADO: <span id="reloadStateText">INACTIVO</span>
                </div>
                <div class="reload-progress-container" id="reloadProgressContainer">
                    <div class="reload-progress-bar" id="reloadProgressBar" style="width:0%;">
                        <span id="reloadProgressText">0%</span>
                    </div>
                </div>
                <div class="reload-info-grid" id="reloadInfoGrid" style="display:none;">
                    <div class="reload-info-item">VUELTAS: <span id="reloadDone">0</span></div>
                    <div class="reload-info-item">OBJ: <span id="reloadTarget">0</span></div>
                    <div class="reload-info-item">LEN: <span id="reloadLenDisplay">--</span></div>
                </div>

                <button class="btn-calculate btn-reload-start" onclick="reloadStart()">
                    &#8635; INICIAR RECARGA
                </button>
                <div class="button-group">
                    <button class="btn-pause btn-reload-pause" id="btnReloadPause"
                            onclick="reloadPause()" disabled>PAUSAR</button>
                    <button class="btn-reset btn-reload-cancel" id="btnReloadCancel"
                            onclick="reloadReset()">CANCELAR</button>
                </div>
                <div class="toast" id="reloadToast" style="margin-top:8px;"></div>
            </div>

        </div><!-- fin columna izquierda -->

        <!-- ═══ COLUMNA DERECHA: OPERACIÓN + ESTADO ═══ -->
        <div>
            <div class="block-wrap card" style="margin-bottom:20px;" id="cardOp">
                <div class="block-overlay" id="overlayOp">
                    <div class="block-msg">🔒 SISTEMA BLOQUEADO<span>Opción deshabilitada — falta filamento</span></div>
                </div>
                <h2>[ PANEL DE OPERACIÓN ]</h2>
                <div class="button-group">
                    <button class="btn-start" id="btnStart" onclick="startWinding()" disabled>START</button>
                    <button class="btn-pause" id="btnPause" onclick="sendCmd('pause')"  disabled>PAUSE</button>
                    <button class="btn-stop"  id="btnStop"  onclick="sendCmd('stop')"   disabled>STOP</button>
                    <button class="btn-reset" onclick="resetSystem()">RESET</button>
                </div>
                <div class="checklist">
                    <div class="checklist-title">▸ PRE-ARRANQUE</div>
                    <div class="check-item" id="chk-calc">
                        <span class="icon">✗</span><span>Cálculo ejecutado</span>
                    </div>
                    <div class="check-item" id="chk-endstop">
                        <span class="icon">✗</span><span>Final de carrera libre</span>
                    </div>
                    <div class="check-item" id="chk-capacity">
                        <span class="icon">—</span><span>Vueltas dentro de capacidad</span>
                    </div>
                    <div class="check-item" id="chk-wire">
                        <span class="icon">—</span><span>Longitud de cobre calculada</span>
                    </div>
                </div>
            </div>

            <div class="block-wrap" id="wrapStatus">
                <div class="block-overlay" id="overlayStatus">
                    <div class="block-msg">🔒 SISTEMA BLOQUEADO<span>Opción deshabilitada — falta filamento</span></div>
                </div>
                <div class="status-panel">
                    <div class="status-main">
                        <div style="font-size:0.7em;">MODO SISTEMA</div>
                        <div class="state-value" id="stateDisplay">READY</div>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar" id="progressBar" style="width:0%;">
                            <span id="progressText">0%</span>
                        </div>
                    </div>
                    <div class="info-grid">
                        <div class="info-item">HECHAS: <span id="turnsDone">0</span></div>
                        <div class="info-item">RESTAN: <span id="turnsRemaining">0</span></div>
                        <div class="info-item">META:   <span id="turnsTotal">0</span></div>
                        <div class="info-item">VEL:    <span id="speedValue">0%</span></div>
                        <div class="info-item">F.CARRERA: <span class="sensor-status" id="endstopStatus">OFF</span></div>
                        <div class="info-item">HALL: <span class="sensor-status" id="hallStatus">OFF</span></div>
                    </div>
                </div>
            </div>
        </div><!-- fin columna derecha -->

    </div><!-- fin grid -->

    <footer>
        LOG: HTTP POLLING // FLASK-MQTT BRIDGE // TOPIC: bobibobiutb/* // 2026 INDUSTRIAL CONTROL SYSTEMS
    </footer>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
//  ESTADO LOCAL
// ═══════════════════════════════════════════════════════════════
let calcDone       = false;
let calcResult     = null;
let currentState   = 'ready';
let endstopActive  = false;
let calcToastShown = false;

// ═══════════════════════════════════════════════════════════════
//  REGLAS DE VALIDACIÓN
// ═══════════════════════════════════════════════════════════════
const FIELD_RULES = {
    outer:  { min:1,    max:500,   step:0.1,  integer:false },
    inner:  { min:1,    max:499,   step:0.1,  integer:false },
    height: { min:0.1,  max:200,   step:0.1,  integer:false },
    wire:   { min:0.01, max:10,    step:0.01, integer:false },
    turns:  { min:1,    max:99999, step:1,    integer:true  },
    speed:  { min:10,   max:100,   step:1,    integer:true  },
};

function validateField(input) {
    const id = input.id, rules = FIELD_RULES[id];
    if (!rules) return true;
    const errEl = document.getElementById('err-' + id);
    const val   = parseFloat(input.value);
    let   msg   = '';

    if (input.value === '' || isNaN(val))          msg = '⚠ Campo obligatorio';
    else if (val < 0)                              msg = '✗ No se permiten negativos';
    else if (val < rules.min)                      msg = `✗ Mínimo: ${rules.min}`;
    else if (val > rules.max)                      msg = `✗ Máximo: ${rules.max}`;
    else if (rules.integer && !Number.isInteger(val)) msg = '✗ Debe ser entero';

    if (msg) {
        input.classList.add('input-error'); input.classList.remove('input-ok');
        errEl.textContent = msg; errEl.classList.add('visible');
    } else {
        input.classList.remove('input-error'); input.classList.add('input-ok');
        errEl.textContent = ''; errEl.classList.remove('visible');
    }
    validateGeometry();
    return msg === '';
}

function validateGeometry() {
    const outer = parseFloat(document.getElementById('outer').value);
    const inner = parseFloat(document.getElementById('inner').value);
    const wire  = parseFloat(document.getElementById('wire').value);
    if (!isNaN(outer) && !isNaN(inner) && inner >= outer) {
        document.getElementById('inner').classList.add('input-error');
        const e = document.getElementById('err-inner');
        e.textContent = '✗ Debe ser menor que D. Exterior'; e.classList.add('visible');
    }
    if (!isNaN(outer) && !isNaN(inner) && !isNaN(wire)) {
        const win = (outer - inner) / 2;
        if (wire > win) {
            document.getElementById('wire').classList.add('input-error');
            const e = document.getElementById('err-wire');
            e.textContent = `✗ No cabe en ventana (${win.toFixed(2)}mm)`; e.classList.add('visible');
        }
    }
}

function validateAll() {
    let ok = true;
    Object.keys(FIELD_RULES).forEach(id => { if (!validateField(document.getElementById(id))) ok = false; });
    const o = parseFloat(document.getElementById('outer').value);
    const i = parseFloat(document.getElementById('inner').value);
    if (!isNaN(o) && !isNaN(i) && i >= o) ok = false;
    return ok;
}

// ═══════════════════════════════════════════════════════════════
//  TOAST
// ═══════════════════════════════════════════════════════════════
function showToast(msg, type) {
    const t = document.getElementById('calcToast');
    t.textContent = msg; t.className = 'toast ' + type;
}
function showReloadToast(msg, type) {
    const el = document.getElementById('reloadToast');
    el.textContent = msg; el.className = 'toast ' + type;
    setTimeout(() => { el.className = 'toast'; }, 4000);
}

// ═══════════════════════════════════════════════════════════════
//  CHECKLIST PRE-ARRANQUE
// ═══════════════════════════════════════════════════════════════
function updateChecklist() {
    const turns = parseInt(document.getElementById('turns').value);
    setCheck('chk-calc',    calcDone,       calcDone ? 'Cálculo ejecutado' : 'Cálculo pendiente');
    setCheck('chk-endstop', !endstopActive, endstopActive ? 'Final de carrera ACTIVO ⚠' : 'Final de carrera libre');
    if (calcResult) {
        const ok = turns <= calcResult.total_capacity;
        setCheck('chk-capacity', ok,
            ok ? `Vueltas OK (cap: ${calcResult.total_capacity})`
               : `Excede capacidad (${calcResult.total_capacity} máx)`);
    } else {
        setCheckNeutral('chk-capacity', 'Vueltas dentro de capacidad');
    }
    if (calcResult && calcResult.wire_length_m > 0) {
        setCheck('chk-wire', true, `Cobre necesario: ${calcResult.wire_length_m.toFixed(2)} m`);
    } else {
        setCheckNeutral('chk-wire', 'Longitud de cobre calculada');
    }
    const canStart = calcDone && !endstopActive
                  && currentState !== 'running' && currentState !== 'emergency'
                  && (calcResult ? turns <= calcResult.total_capacity : false);
    document.getElementById('btnStart').disabled = !canStart;
}

function setCheck(id, ok, label) {
    const el = document.getElementById(id);
    el.className = 'check-item ' + (ok ? 'check-ok' : 'check-fail');
    el.innerHTML = `<span class="icon">${ok ? '✔' : '✗'}</span><span>${label}</span>`;
}
function setCheckNeutral(id, label) {
    const el = document.getElementById(id);
    el.className = 'check-item check-warn';
    el.innerHTML = `<span class="icon">—</span><span>${label}</span>`;
}

// ═══════════════════════════════════════════════════════════════
//  COMUNICACIÓN HTTP → FLASK
// ═══════════════════════════════════════════════════════════════
function postControl(payload) {
    fetch('/control', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload)
    }).catch(err => { console.error('[HTTP] Error:', err); showToast('✗ Sin conexión con el servidor', 'error'); });
}

// ═══════════════════════════════════════════════════════════════
//  ACCIONES
// ═══════════════════════════════════════════════════════════════
function calculate() {
    if (!validateAll()) { showToast('✗ Corrija los errores antes de calcular', 'error'); return; }
    const outer = parseFloat(document.getElementById('outer').value);
    const inner = parseFloat(document.getElementById('inner').value);
    if (inner >= outer) { showToast('✗ D. Interior debe ser menor que D. Exterior', 'error'); return; }
    calcToastShown = false;
    showToast('⟳ Enviando al ESP32...', 'warning');
    postControl({
        cmd: 'calculate',
        toroid: { outer_diameter: outer, inner_diameter: inner,
                  height: parseFloat(document.getElementById('height').value) },
        wire_diameter: parseFloat(document.getElementById('wire').value),
        target_turns:  parseInt(document.getElementById('turns').value)
    });
}

function startWinding() {
    if (!calcDone)       { showToast('✗ Ejecute el cálculo primero', 'error'); return; }
    if (endstopActive)   { showToast('✗ Final de carrera activo — libérelo antes', 'error'); return; }
    const turns = parseInt(document.getElementById('turns').value);
    if (calcResult && turns > calcResult.total_capacity) {
        showToast(`✗ Vueltas (${turns}) exceden capacidad (${calcResult.total_capacity})`, 'error'); return;
    }
    sendCmd('start');
}

function resetSystem() {
    calcDone = false; calcResult = null; calcToastShown = false;
    document.getElementById('resultsPanel').style.display = 'none';
    document.getElementById('warningMsg').textContent = '';
    Object.keys(FIELD_RULES).forEach(id => {
        const el = document.getElementById(id);
        el.classList.remove('input-ok', 'input-error');
        document.getElementById('err-' + id).classList.remove('visible');
    });
    showToast('Sistema reseteado', 'warning');
    sendCmd('reset');
    updateChecklist();
}

function sendCmd(cmd) {
    const payload = { cmd };
    if (cmd === 'start') payload.speed = parseInt(document.getElementById('speed').value) || 70;
    postControl(payload);
}

function updateButtons(state) {
    document.getElementById('btnPause').disabled = (state !== 'running');
    document.getElementById('btnStop').disabled  = (state === 'stopped' || state === 'ready' || state === 'complete');
}

// ═══════════════════════════════════════════════════════════════
//  MODO RECARGA
// ═══════════════════════════════════════════════════════════════
function updateReloadCalc() {
    const len = parseFloat(document.getElementById('reloadLen').value) || 0;
    document.getElementById('reloadCalcTurns').textContent = Math.ceil(len / 30);
}

function reloadStart() {
    const len = parseFloat(document.getElementById('reloadLen').value);
    if (!len || len < 10) { showReloadToast('✗ Longitud inválida (mín 10 cm)', 'error'); return; }
    postControl({ cmd: 'reload_start', length_cm: len,
                  target_turns: Math.ceil(len / 30),
                  speed: parseInt(document.getElementById('speed').value) || 70 });
    showReloadToast('⟳ Iniciando recarga...', 'warning');
}
function reloadPause() { postControl({ cmd: 'reload_pause' }); }
function reloadReset() {
    postControl({ cmd: 'reload_reset' });
    document.getElementById('reloadProgressContainer').style.display = 'none';
    document.getElementById('reloadInfoGrid').style.display          = 'none';
    document.getElementById('reloadStateDisplay').style.display      = 'none';
    showReloadToast('Recarga cancelada', 'warning');
}

function updateReloadUI(data) {
    const modo   = data.modo  || 'bobinado';
    const rDone  = data.reload_done       || 0;
    const rTotal = data.reload_target     || 0;
    const rLen   = data.reload_length_cm  || 0;
    const state  = data.state || 'ready';

    if (modo === 'recarga') {
        document.getElementById('reloadStateDisplay').style.display      = 'block';
        document.getElementById('reloadProgressContainer').style.display = 'block';
        document.getElementById('reloadInfoGrid').style.display          = 'grid';

        const labels = { running:'RECARGANDO', paused:'PAUSADO', complete:'COMPLETO ✔',
                         stopped:'DETENIDO', emergency:'EMERGENCIA' };
        document.getElementById('reloadStateText').textContent = labels[state] || state.toUpperCase();

        const pct = rTotal > 0 ? Math.round(rDone / rTotal * 100) : 0;
        document.getElementById('reloadProgressBar').style.width  = pct + '%';
        document.getElementById('reloadProgressText').textContent = pct + '%';
        document.getElementById('reloadDone').textContent         = rDone;
        document.getElementById('reloadTarget').textContent       = rTotal;
        document.getElementById('reloadLenDisplay').textContent   = rLen + ' cm';
        document.getElementById('btnReloadPause').disabled        = (state !== 'running');

        if (state === 'complete') showReloadToast('✔ Recarga completada — ' + rLen + ' cm', 'success');
    } else {
        document.getElementById('btnReloadPause').disabled = true;
    }
}

// ═══════════════════════════════════════════════════════════════
//  BLOQUEO POR FILAMENTO
// ═══════════════════════════════════════════════════════════════
function applySystemBlock(filamentLockActive, reloadRequired) {
    const banner = document.getElementById('globalBlockBanner');
    if (filamentLockActive) {
        banner.innerHTML = '🔒 &nbsp; SIN FILAMENTO — SISTEMA BLOQUEADO &nbsp; 🔒 &nbsp;&nbsp;|&nbsp;&nbsp; Inserte alambre para habilitar la recarga';
        banner.style.background = '#c0392b'; banner.className = 'active';
    } else if (reloadRequired) {
        banner.innerHTML = '♻ &nbsp; RECARGA OBLIGATORIA — Complete la recarga para volver al modo normal';
        banner.style.background = '#e67e22'; banner.className = 'active';
    } else {
        banner.className = ''; banner.style.background = '#c0392b';
    }

    const blocked = filamentLockActive || reloadRequired;
    ['overlayParams','overlayOp','overlayStatus'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.className = 'block-overlay' + (blocked ? ' active' : '');
    });

    const rc = document.getElementById('reloadCard');
    if (rc) {
        rc.style.opacity       = filamentLockActive ? '0.35' : '1';
        rc.style.pointerEvents = filamentLockActive ? 'none'  : 'auto';
    }
    const cancelBtn = document.getElementById('btnReloadCancel');
    if (cancelBtn) {
        cancelBtn.disabled = reloadRequired;
        cancelBtn.title    = reloadRequired ? 'Complete la recarga primero' : '';
    }
}

// ═══════════════════════════════════════════════════════════════
//  POLLING HTTP — actualiza estado cada 1 segundo
// ═══════════════════════════════════════════════════════════════
function updateStatus() {
    // ── Fetch estado principal ───────────────────────────────────────────────
    fetch('/status')
        .then(r => r.json())
        .then(data => {
            setSrvBadge(true);
            currentState  = data.state   || 'ready';
            endstopActive = data.endstop || false;

            document.getElementById('stateDisplay').textContent      = currentState.toUpperCase();
            document.getElementById('turnsDone').textContent         = data.turns_done      || 0;
            document.getElementById('turnsRemaining').textContent    = data.turns_remaining || 0;
            document.getElementById('turnsTotal').textContent        = data.turns_total     || 0;
            document.getElementById('speedValue').textContent        = (data.speed || 0) + '%';

            const pct = (data.turns_total || 0) > 0
                ? Math.round((data.turns_done / data.turns_total) * 100) : 0;
            document.getElementById('progressBar').style.width   = pct + '%';
            document.getElementById('progressText').textContent  = pct + '%';

            const endEl = document.getElementById('endstopStatus');
            endEl.textContent = data.endstop ? 'ON' : 'OFF';
            endEl.className   = data.endstop ? 'sensor-status sensor-active' : 'sensor-status';

            const hallEl = document.getElementById('hallStatus');
            hallEl.textContent = data.hall ? 'ON' : 'OFF';
            hallEl.className   = data.hall ? 'sensor-status sensor-active' : 'sensor-status';

            updateButtons(currentState);
            updateChecklist();
            updateReloadUI(data);
            applySystemBlock(data.filament_lock_active || false, data.reload_required || false);

            if (currentState === 'emergency')
                showToast('⚠ EMERGENCIA — Motor detenido por falta de filamento.', 'error');
        })
        .catch(() => setSrvBadge(false));

    // ── Fetch resultado de cálculo ────────────────────────────────────────────
    fetch('/calculation')
        .then(r => r.json())
        .then(data => {
            if (!data.wire_length_m || data.wire_length_m <= 0) return;
            calcDone   = true;
            calcResult = data;

            document.getElementById('resultsPanel').style.display     = 'block';
            document.getElementById('wireLength').textContent         = data.wire_length_m.toFixed(2) + ' m';
            document.getElementById('turnsPerLayer').textContent      = data.turns_per_layer;
            document.getElementById('maxLayers').textContent          = data.max_layers;
            document.getElementById('totalCapacity').textContent      = data.total_capacity;

            const warnEl = document.getElementById('warningMsg');
            if (data.warning) {
                warnEl.textContent = '⚠ ' + data.warning;
                if (!calcToastShown) {
                    showToast(`⚠ ${data.warning} — máx ${data.total_capacity} vueltas`, 'warning');
                    calcToastShown = true;
                }
            } else if (!calcToastShown) {
                warnEl.textContent = '';
                showToast(`✔ Cálculo OK — ${data.wire_length_m.toFixed(2)}m de cobre necesarios`, 'success');
                calcToastShown = true;
            }
            updateChecklist();
        });
}

function setSrvBadge(online) {
    const el = document.getElementById('srvBadge');
    if (online) { el.className = 'srv-badge online';  el.textContent = '● SERVIDOR OK'; }
    else        { el.className = 'srv-badge offline'; el.textContent = '○ SIN SERVIDOR'; }
}

// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════
window.onload = () => {
    Object.keys(FIELD_RULES).forEach(id => validateField(document.getElementById(id)));
    updateChecklist();
    updateReloadCalc();
};

setInterval(updateStatus, 1000);
</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────────────────
#  RUTAS FLASK
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/control', methods=['POST'])
def control():
    data = request.get_json()
    mqtt_client.publish(TOPIC_CMD, json.dumps(data))
    print(f"[MQTT→CMD] {json.dumps(data)}")
    return jsonify({'status': 'ok', 'command': data})

@app.route('/status')
def status():
    payload = dict(latest_status)
    payload['calculation'] = calculation_result
    return jsonify(payload)

@app.route('/calculation')
def calculation():
    return jsonify(calculation_result)

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("  SERVIDOR EMBOBINADORA INDUSTRIAL")
    print("=" * 60)
    print(f"  MQTT Broker : {MQTT_BROKER}:{MQTT_PORT}")
    print(f"  CMD topic   : {TOPIC_CMD}")
    print(f"  STATUS topic: {TOPIC_STATUS}")
    print(f"  Web UI      : http://localhost:5000")
    print(f"  Red local   : http://0.0.0.0:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
