from flask import Flask, render_template_string, request, jsonify
import paho.mqtt.client as mqtt
import json
import threading
import time

app = Flask(__name__)

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_CMD = "bobibobiutb/cmd"      # Para enviar comandos
TOPIC_STATUS = "bobibobiutb/status"  # Para recibir estado
mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

latest_status = {
    "type": "status",
    "turns_done": 0,
    "turns_remaining": 0,
    "turns_total": 0,
    "state": "stopped",
    "endstop": False,
    "hall": False,
    "speed": 0,
    "direction": "S"
}

calculation_result = {
    "wire_length_m": 0,
    "turns_per_layer": 0,
    "max_layers": 0,
    "total_capacity": 0,
    "warning": ""
}

def on_message(client, userdata, msg):
    global latest_status, calculation_result, hall_pulse_time, endstop_last_seen
    try:
        data = json.loads(msg.payload.decode())
        print(f"[MQTT←{data}]")
        if data.get("type") == "status":
            latest_status.update(data)
            if data.get("hall"):
                hall_pulse_time = time.time()
            if data.get("endstop"):
                endstop_last_seen = time.time()
        elif data.get("type") == "calculation":
            calculation_result = {
                "wire_length_m": data.get("wire_length_m", 0),
                "turns_per_layer": data.get("turns_per_layer", 0),
                "max_layers": data.get("max_layers", 0),
                "total_capacity": data.get("total_capacity", 0),
                "warning": data.get("warning", "")
            }
    except Exception as e:
        print(f"Error procesando MQTT: {e}")

mqtt_client.on_message = on_message
mqtt_client.subscribe(TOPIC_STATUS)  # Solo suscribirse a status
mqtt_client.loop_start()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SISTEMA DE CONTROL - EMBOBINADORA TOROIDAL</title>
    <style>
        :root {
            --gris-maquina: #b0b0b0;
            --gris-oscuro: #808080;
            --gris-claro: #d9d9d9;
            --azul-utb: #0033a0;
            --negro-panel: #1a1a1a;
            --blanco-puro: #ffffff;
            --rojo-error: #c0392b;
            --verde-ok: #27ae60;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Courier New', Courier, monospace; }

        body { background-color: #2b2b2b; color: var(--negro-panel); padding: 20px; }

        .container {
            max-width: 1200px; margin: 0 auto;
            background-color: var(--gris-maquina);
            border: 4px solid var(--gris-claro);
            border-right-color: var(--gris-oscuro);
            border-bottom-color: var(--gris-oscuro);
            padding: 15px;
            box-shadow: 10px 10px 0px rgba(0,0,0,0.5);
        }

        header {
            background-color: var(--azul-utb); color: var(--blanco-puro);
            padding: 15px; border: 3px inset rgba(255,255,255,0.2);
            margin-bottom: 20px;
        }
        header h1 { font-size: 1.8em; letter-spacing: -1px; }
        header .subtitle {
            font-size: 0.8em; text-transform: uppercase;
            border-top: 1px solid var(--blanco-puro);
            padding-top: 5px; margin-top: 5px;
        }

        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

        .card {
            background-color: var(--gris-maquina);
            border: 3px outset var(--gris-claro); padding: 20px;
        }
        .card h2 {
            background-color: var(--gris-oscuro); color: var(--blanco-puro);
            font-size: 1em; padding: 5px 10px; margin-bottom: 15px;
            border: 2px inset var(--gris-claro);
        }

        .input-group {
            margin-bottom: 10px; display: flex;
            align-items: center; justify-content: space-between;
            flex-wrap: wrap; gap: 4px;
        }

        label { font-weight: bold; font-size: 0.85em; text-transform: uppercase; flex: 1; }

        input[type="number"] {
            width: 100px;
            background-color: var(--blanco-puro);
            border: 3px inset var(--gris-oscuro);
            padding: 5px; font-weight: bold;
            color: var(--negro-panel); text-align: center;
            transition: border-color 0.2s;
        }

        /* Estados visuales de los inputs */
        input.input-error  { border-color: var(--rojo-error) !important; background-color: #fdecea; }
        input.input-ok     { border-color: var(--verde-ok)   !important; }

        .field-error {
            font-size: 0.72em; color: var(--rojo-error);
            font-weight: bold; width: 100%;
            text-align: right; display: none;
        }
        .field-error.visible { display: block; }

        button {
            border: 4px outset var(--gris-claro);
            background-color: var(--gris-claro);
            padding: 12px; font-weight: bold;
            cursor: pointer; text-transform: uppercase; transition: all 0.1s;
        }
        button:active { border-style: inset; transform: translate(2px, 2px); }
        button:disabled { opacity: 0.4; cursor: not-allowed; transform: none !important; }

        .btn-calculate { background-color: var(--azul-utb); color: white; width: 100%; margin-top: 10px; }
        .button-group  { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .btn-start  { background-color: #2ecc71; color: white; }
        .btn-pause  { background-color: #f1c40f; color: black; }
        .btn-stop   { background-color: #e74c3c; color: white; }
        .btn-reset  { background-color: var(--gris-oscuro); color: white; }

        /* Toast de validación general */
        .toast {
            display: none; margin-top: 10px; padding: 8px 12px;
            font-size: 0.82em; font-weight: bold; border-left: 4px solid;
        }
        .toast.error   { background: #fdecea; border-color: var(--rojo-error); color: var(--rojo-error); display: block; }
        .toast.warning { background: #fff8e1; border-color: #f39c12;           color: #7d5a00;            display: block; }
        .toast.success { background: #eafaf1; border-color: var(--verde-ok);   color: #1a6e3a;            display: block; }

        /* Panel de estado */
        .status-panel {
            background-color: var(--negro-panel); color: #00ff00;
            border: 6px solid var(--gris-oscuro); padding: 15px;
        }
        .status-main {
            border: 2px solid #00ff00; padding: 10px;
            margin-bottom: 15px; text-align: center;
        }
        .state-value    { font-size: 2em; font-weight: bold; }
        .progress-bar-container { background: #222; border: 2px solid #00ff00; height: 30px; margin: 10px 0; }
        .progress-bar   { height: 100%; background-color: #00ff00; color: black; font-weight: bold; display: flex; align-items: center; justify-content: center; min-width: 30px; }
        .info-grid      { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
        .info-item      { border: 1px solid #004400; padding: 5px; font-size: 0.8em; }
        .sensor-status  { padding: 2px 5px; border: 1px solid #00ff00; }
        .sensor-active  { background-color: #00ff00; color: black; }

        /* Panel checklist pre-arranque */
        .checklist {
            background: var(--negro-panel); border: 2px solid #444;
            padding: 10px; margin-top: 12px;
        }
        .checklist-title { color: #aaa; font-size: 0.75em; margin-bottom: 6px; text-transform: uppercase; }
        .check-item {
            font-size: 0.78em; padding: 3px 0;
            display: flex; align-items: center; gap: 6px;
        }
        .check-item .icon { font-size: 1em; }
        .check-ok   { color: #00ff00; }
        .check-fail { color: #ff4444; }
        .check-warn { color: #f1c40f; }

        .results-panel {
            background-color: var(--blanco-puro); border: 3px inset var(--gris-oscuro);
            margin-top: 15px; padding: 10px; color: var(--negro-panel); display: none;
        }
        .result-item { border-bottom: 1px dashed var(--gris-oscuro); padding: 3px 0; font-size: 0.85em; }

        footer {
            margin-top: 20px; background-color: var(--gris-oscuro);
            color: var(--blanco-puro); padding: 10px;
            font-size: 0.7em; text-align: center;
            border: 2px inset var(--gris-claro);
        }
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>CONTROLADOR INDUSTRIAL V1.0 - UTB</h1>
        <div class="subtitle">Embedded System ESP32 // Toroidal Winding Control</div>
    </header>

    <div class="grid">
        <!-- ═══ PARÁMETROS ═══ -->
        <div class="card">
            <h2>[ PARÁMETROS DE ENTRADA ]</h2>

            <div class="input-group">
                <label>D. EXTERIOR (mm)</label>
                <input type="number" id="outer" value="50" min="1" step="0.1" oninput="validateField(this)">
                <span class="field-error" id="err-outer"></span>
            </div>
            <div class="input-group">
                <label>D. INTERIOR (mm)</label>
                <input type="number" id="inner" value="30" min="1" step="0.1" oninput="validateField(this)">
                <span class="field-error" id="err-inner"></span>
            </div>
            <div class="input-group">
                <label>ALTURA (mm)</label>
                <input type="number" id="height" value="20" min="0.1" step="0.1" oninput="validateField(this)">
                <span class="field-error" id="err-height"></span>
            </div>
            <div class="input-group">
                <label>D. ALAMBRE (mm)</label>
                <input type="number" id="wire" value="0.5" min="0.01" step="0.01" oninput="validateField(this)">
                <span class="field-error" id="err-wire"></span>
            </div>
            <div class="input-group">
                <label>VUELTAS OBJ.</label>
                <input type="number" id="turns" value="100" min="1" step="1" oninput="validateField(this)">
                <span class="field-error" id="err-turns"></span>
            </div>
            <div class="input-group">
                <label>MOTOR VEL (%)</label>
                <input type="number" id="speed" value="70" min="10" max="100" step="1" oninput="validateField(this)">
                <span class="field-error" id="err-speed"></span>
            </div>

            <!-- Toast mensajes globales -->
            <div class="toast" id="calcToast"></div>

            <button class="btn-calculate" onclick="calculate()">EJECUTAR CÁLCULO</button>

            <div class="results-panel" id="resultsPanel">
                <strong>>> REPORTE DE CÁLCULO:</strong>
                <div class="result-item">LONG. ALAMBRE: <span id="wireLength">--</span></div>
                <div class="result-item">VUELTAS/CAPA: <span id="turnsPerLayer">--</span></div>
                <div class="result-item">CAPAS MÁX:   <span id="maxLayers">--</span></div>
                <div class="result-item">CAPACIDAD TOT: <span id="totalCapacity">--</span></div>
                <div id="warningMsg" style="color:red;font-weight:bold;margin-top:5px;"></div>
            </div>
        </div>

        <!-- ═══ OPERACIÓN ═══ -->
        <div>
            <div class="card" style="margin-bottom:20px;">
                <h2>[ PANEL DE OPERACIÓN ]</h2>
                <div class="button-group">
                    <button class="btn-start" id="btnStart" onclick="startWinding()" disabled>START</button>
                    <button class="btn-pause" id="btnPause" onclick="sendCmd('pause')" disabled>PAUSE</button>
                    <button class="btn-stop"  id="btnStop"  onclick="sendCmd('stop')"  disabled>STOP</button>
                    <button class="btn-reset" onclick="resetSystem()">RESET</button>
                </div>

                <!-- Checklist pre-arranque -->
                <div class="checklist">
                    <div class="checklist-title">▸ PRE-ARRANQUE</div>
                    <div class="check-item" id="chk-calc">
                        <span class="icon">✗</span>
                        <span>Cálculo ejecutado</span>
                    </div>
                    <div class="check-item" id="chk-endstop">
                        <span class="icon">✗</span>
                        <span>Final de carrera libre</span>
                    </div>
                    <div class="check-item" id="chk-capacity">
                        <span class="icon">—</span>
                        <span>Vueltas dentro de capacidad</span>
                    </div>
                    <div class="check-item" id="chk-wire">
                        <span class="icon">—</span>
                        <span>Longitud de cobre calculada</span>
                    </div>
                </div>
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
                    <div class="info-item">META: <span id="turnsTotal">0</span></div>
                    <div class="info-item">VEL: <span id="speedValue">0%</span></div>
                    <div class="info-item">F. CARRERA: <span class="sensor-status" id="endstopStatus">OFF</span></div>
                    <div class="info-item">HALL: <span class="sensor-status" id="hallStatus">OFF</span></div>
                </div>
            </div>
        </div>
    </div>

    <footer>
        LOG: MQTT_BROKER_CONNECTED // TOPIC: bobibobiutb/* // 2026 INDUSTRIAL CONTROL SYSTEMS
    </footer>
</div>

<script>
// ═══════════════════════════════════════════════
//  ESTADO LOCAL
// ═══════════════════════════════════════════════
let calcDone        = false;
let calcResult      = null;
let currentState    = 'ready';
let endstopActive   = false;
let calcToastShown  = false;

// ═══════════════════════════════════════════════
//  REGLAS DE VALIDACIÓN POR CAMPO
// ═══════════════════════════════════════════════
const FIELD_RULES = {
    outer:  { label: 'D. Exterior', min: 1,    max: 500,  step: 0.1,  integer: false },
    inner:  { label: 'D. Interior', min: 1,    max: 499,  step: 0.1,  integer: false },
    height: { label: 'Altura',      min: 0.1,  max: 200,  step: 0.1,  integer: false },
    wire:   { label: 'D. Alambre',  min: 0.01, max: 10,   step: 0.01, integer: false },
    turns:  { label: 'Vueltas',     min: 1,    max: 99999,step: 1,    integer: true  },
    speed:  { label: 'Velocidad',   min: 10,   max: 100,  step: 1,    integer: true  },
};

function validateField(input) {
    const id    = input.id;
    const rules = FIELD_RULES[id];
    const errEl = document.getElementById('err-' + id);
    const val   = parseFloat(input.value);
    let   msg   = '';

    if (input.value === '' || isNaN(val)) {
        msg = '⚠ Campo obligatorio';
    } else if (val < 0) {
        msg = '✗ No se permiten valores negativos';
    } else if (val < rules.min) {
        msg = `✗ Mínimo: ${rules.min}`;
    } else if (val > rules.max) {
        msg = `✗ Máximo: ${rules.max}`;
    } else if (rules.integer && !Number.isInteger(val)) {
        msg = '✗ Debe ser número entero';
    }

    if (msg) {
        input.classList.add('input-error');
        input.classList.remove('input-ok');
        errEl.textContent = msg;
        errEl.classList.add('visible');
    } else {
        input.classList.remove('input-error');
        input.classList.add('input-ok');
        errEl.textContent = '';
        errEl.classList.remove('visible');
    }

    // Re-validar relación exterior > interior
    validateGeometry();
    return msg === '';
}

function validateGeometry() {
    const outer = parseFloat(document.getElementById('outer').value);
    const inner = parseFloat(document.getElementById('inner').value);
    const wire  = parseFloat(document.getElementById('wire').value);

    const errOuter = document.getElementById('err-outer');
    const errInner = document.getElementById('err-inner');

    // Limpiar errores geométricos previos
    ['outer','inner'].forEach(id => {
        const el = document.getElementById(id);
        if (!el.classList.contains('input-error') ||
            document.getElementById('err-'+id).textContent.includes('exterior')) {
            // solo limpiar si el error era geométrico
        }
    });

    if (!isNaN(outer) && !isNaN(inner)) {
        if (inner >= outer) {
            document.getElementById('inner').classList.add('input-error');
            errInner.textContent = '✗ Debe ser menor que D. Exterior';
            errInner.classList.add('visible');
        }
        if (outer <= inner) {
            document.getElementById('outer').classList.add('input-error');
            errOuter.textContent = '✗ Debe ser mayor que D. Interior';
            errOuter.classList.add('visible');
        }
        // Validar que el alambre quepa en la ventana del toroide
        if (!isNaN(wire)) {
            const window_mm = (outer - inner) / 2;
            if (wire > window_mm) {
                document.getElementById('wire').classList.add('input-error');
                document.getElementById('err-wire').textContent =
                    `✗ Alambre (${wire}mm) no cabe en ventana (${window_mm.toFixed(2)}mm)`;
                document.getElementById('err-wire').classList.add('visible');
            }
        }
    }
}

// Validar todos los campos y devolver true si todos pasan
function validateAll() {
    let allOk = true;
    Object.keys(FIELD_RULES).forEach(id => {
        const input = document.getElementById(id);
        if (!validateField(input)) allOk = false;
    });

    // Validación cruzada exterior/interior
    const outer = parseFloat(document.getElementById('outer').value);
    const inner = parseFloat(document.getElementById('inner').value);
    if (!isNaN(outer) && !isNaN(inner) && inner >= outer) allOk = false;

    return allOk;
}

// ═══════════════════════════════════════════════
//  TOAST GLOBAL
// ═══════════════════════════════════════════════
function showToast(msg, type) {
    const t = document.getElementById('calcToast');
    t.textContent = msg;
    t.className = 'toast ' + type;
}

// ═══════════════════════════════════════════════
//  CHECKLIST PRE-ARRANQUE
// ═══════════════════════════════════════════════
function updateChecklist() {
    const outer    = parseFloat(document.getElementById('outer').value);
    const inner    = parseFloat(document.getElementById('inner').value);
    const turns    = parseInt(document.getElementById('turns').value);

    // Check 1: Cálculo ejecutado
    setCheck('chk-calc', calcDone,
             calcDone ? 'Cálculo ejecutado' : 'Cálculo pendiente');

    // Check 2: Endstop libre
    setCheck('chk-endstop', !endstopActive,
             endstopActive ? 'Final de carrera ACTIVO ⚠' : 'Final de carrera libre');

    // Check 3: Vueltas dentro de capacidad
    if (calcResult) {
        const ok = turns <= calcResult.total_capacity;
        setCheck('chk-capacity', ok,
                 ok ? `Vueltas OK (cap: ${calcResult.total_capacity})`
                    : `Excede capacidad (${calcResult.total_capacity} máx)`);
    } else {
        setCheckNeutral('chk-capacity', 'Vueltas dentro de capacidad');
    }

    // Check 4: Longitud de cobre calculada
    if (calcResult && calcResult.wire_length_m > 0) {
        setCheck('chk-wire', true,
                 `Cobre necesario: ${calcResult.wire_length_m.toFixed(2)} m`);
    } else {
        setCheckNeutral('chk-wire', 'Longitud de cobre calculada');
    }

    // Habilitar START solo si todos los checks críticos pasan
    const canStart = calcDone
                  && !endstopActive
                  && currentState !== 'running'
                  && currentState !== 'emergency'
                  && (calcResult ? turns <= calcResult.total_capacity : false);

    document.getElementById('btnStart').disabled = !canStart;
}

function setCheck(id, ok, label) {
    const el   = document.getElementById(id);
    el.className = 'check-item ' + (ok ? 'check-ok' : 'check-fail');
    el.innerHTML = `<span class="icon">${ok ? '✔' : '✗'}</span><span>${label}</span>`;
}

function setCheckNeutral(id, label) {
    const el   = document.getElementById(id);
    el.className = 'check-item check-warn';
    el.innerHTML = `<span class="icon">—</span><span>${label}</span>`;
}

// ═══════════════════════════════════════════════
//  ACCIONES
// ═══════════════════════════════════════════════
function calculate() {
    if (!validateAll()) {
        showToast('✗ Corrija los errores antes de calcular', 'error');
        return;
    }

    const outer = parseFloat(document.getElementById('outer').value);
    const inner = parseFloat(document.getElementById('inner').value);
    const turns = parseInt(document.getElementById('turns').value);

    if (inner >= outer) {
        showToast('✗ D. Interior debe ser menor que D. Exterior', 'error');
        return;
    }

    calcToastShown = false;
    showToast('⟳ Enviando al ESP32...', 'warning');

    const payload = {
        cmd: 'calculate',
        toroid: {
            outer_diameter: outer,
            inner_diameter: inner,
            height: parseFloat(document.getElementById('height').value)
        },
        wire_diameter: parseFloat(document.getElementById('wire').value),
        target_turns:  turns
    };

    fetch('/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(() => showToast('⟳ Cálculo enviado — esperando resultado...', 'warning'))
    .catch(() => showToast('✗ Error de conexión con el servidor', 'error'));
}

function startWinding() {
    if (!calcDone) {
        showToast('✗ Ejecute el cálculo primero', 'error'); return;
    }
    if (endstopActive) {
        showToast('✗ Final de carrera activo — libérelo antes', 'error'); return;
    }
    const turns = parseInt(document.getElementById('turns').value);
    if (calcResult && turns > calcResult.total_capacity) {
        showToast(`✗ Vueltas (${turns}) exceden capacidad (${calcResult.total_capacity})`, 'error');
        return;
    }
    sendCmd('start');
}

function resetSystem() {
    calcDone        = false;
    calcResult      = null;
    calcToastShown  = false;
    document.getElementById('resultsPanel').style.display = 'none';
    document.getElementById('warningMsg').textContent = '';
    // Limpiar estados visuales de inputs
    Object.keys(FIELD_RULES).forEach(id => {
        const el = document.getElementById(id);
        el.classList.remove('input-ok', 'input-error');
        document.getElementById('err-'+id).classList.remove('visible');
    });
    showToast('Sistema reseteado', 'warning');
    sendCmd('reset');
    updateChecklist();
}

function sendCmd(cmd) {
    let payload = { cmd };
    if (cmd === 'start') payload.speed = parseInt(document.getElementById('speed').value) || 70;
    fetch('/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).catch(err => console.error('Error:', err));
}

// ═══════════════════════════════════════════════
//  ACTUALIZACIÓN DE ESTADO
// ═══════════════════════════════════════════════
function updateButtons(state) {
    document.getElementById('btnPause').disabled = (state !== 'running');
    document.getElementById('btnStop').disabled  = (state === 'stopped' || state === 'ready' || state === 'complete');
}

function updateStatus() {
    fetch('/status')
        .then(r => r.json())
        .then(data => {
            currentState  = data.state;
            endstopActive = data.endstop;

            document.getElementById('stateDisplay').textContent = data.state.toUpperCase();
            document.getElementById('turnsDone').textContent      = data.turns_done;
            document.getElementById('turnsRemaining').textContent = data.turns_remaining;
            document.getElementById('turnsTotal').textContent     = data.turns_total;
            document.getElementById('speedValue').textContent     = data.speed + '%';

            const pct = data.turns_total > 0
                ? Math.round((data.turns_done / data.turns_total) * 100) : 0;
            document.getElementById('progressBar').style.width = pct + '%';
            document.getElementById('progressText').textContent = pct + '%';

            const endstopEl = document.getElementById('endstopStatus');
            endstopEl.textContent = data.endstop ? 'ON' : 'OFF';
            endstopEl.className   = data.endstop ? 'sensor-status sensor-active' : 'sensor-status';

            const hallEl = document.getElementById('hallStatus');
            hallEl.textContent = data.hall ? 'ON' : 'OFF';
            hallEl.className   = data.hall ? 'sensor-status sensor-active' : 'sensor-status';

            updateButtons(data.state);
            updateChecklist();

            // Alerta visual de emergencia
            if (data.state === 'emergency') {
                showToast('⚠ EMERGENCIA — Final de carrera activado. Motor detenido.', 'error');
            }
        });

    fetch('/calculation')
        .then(r => r.json())
        .then(data => {
            if (data.wire_length_m > 0) {
                calcDone   = true;
                calcResult = data;

                document.getElementById('resultsPanel').style.display = 'block';
                document.getElementById('wireLength').textContent    = data.wire_length_m.toFixed(2) + ' m';
                document.getElementById('turnsPerLayer').textContent  = data.turns_per_layer;
                document.getElementById('maxLayers').textContent      = data.max_layers;
                document.getElementById('totalCapacity').textContent  = data.total_capacity;

                const turns = parseInt(document.getElementById('turns').value);
                const warnEl = document.getElementById('warningMsg');
                if (data.warning) {
                    warnEl.textContent = '⚠ ' + data.warning;
                    showToast(`⚠ ${data.warning} — máximo ${data.total_capacity} vueltas`, 'warning');
                    calcToastShown = true;
                } else if (!calcToastShown) {
                    warnEl.textContent = '';
                    showToast(`✔ Cálculo OK — ${data.wire_length_m.toFixed(2)}m de cobre necesarios`, 'success');
                    calcToastShown = true;
                }
                updateChecklist();
            }
        });
}

// Validar campos al cargar
window.onload = () => {
    Object.keys(FIELD_RULES).forEach(id => {
        validateField(document.getElementById(id));
    });
    updateChecklist();
};

setInterval(updateStatus, 1000);
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/control', methods=['POST'])
def control():
    data = request.get_json()
    # Enviar a topic de comandos
    mqtt_client.publish(TOPIC_CMD, json.dumps(data))
    print(f"[MQTT→CMD] {json.dumps(data)}")
    return jsonify({'status': 'ok', 'command': data})

@app.route('/status')
def status():
    return jsonify(latest_status)

@app.route('/calculation')
def calculation():
    return jsonify(calculation_result)

if __name__ == '__main__':
    print("=" * 60)
    print("🏭 SERVIDOR EMBOBINADORA INDUSTRIAL")
    print("=" * 60)
    print(f"📡 MQTT Broker: {MQTT_BROKER}")
    print(f"📤 Topic Comandos: {TOPIC_CMD}")
    print(f"📥 Topic Estado: {TOPIC_STATUS}")
    print(f"🌐 Servidor web: http://0.0.0.0:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
