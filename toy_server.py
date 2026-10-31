#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
啵啵贝 BLE 玩具控制服务
运行在 Operit Python 3.8 环境中
监听 localhost:8765

启动后用 Kiwi Browser 或 Edge 打开 http://localhost:8765
"""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ============================================================
# 全局状态
# ============================================================
state_lock = threading.Lock()
state = {
    "suction": 0,       # 吮吸 0-100
    "vibration": 0,     # 震动 0-100
    "electric": 0,      # 电流 0-100
    "connected": False,  # 浏览器桥连接状态
    "ble_connected": False  # 玩具BLE连接状态
}

# ============================================================
# 中继页面 HTML
# ============================================================
RELAY_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>啵啵贝桥接</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#1a1a2e;color:#e0e0e0;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:20px}
.container{max-width:480px;width:100%}
h1{font-size:18px;text-align:center;margin-bottom:20px;color:#7eb8da}
.status-bar{background:#16213e;border-radius:12px;padding:16px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between}
.status-dot{width:10px;height:10px;border-radius:50%;background:#555;transition:background .3s}
.status-dot.online{background:#4ecca3;box-shadow:0 0 8px #4ecca3}
.status-dot.ble{background:#4ecca3;box-shadow:0 0 8px #4ecca3}
.status-text{font-size:13px;flex:1;margin-left:12px}
.btn{width:100%;padding:14px;border:none;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer;transition:all .2s;margin-bottom:12px}
.btn-connect{background:#4ecca3;color:#1a1a2e}
.btn-connect:active{transform:scale(.97)}
.btn-connect:disabled{background:#333;color:#666;cursor:not-allowed}
.btn-stop{background:#e94560;color:#fff}
.btn-stop:active{transform:scale(.97)}
.motor-display{background:#16213e;border-radius:12px;padding:16px;margin-bottom:12px}
.motor-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #0f3460}
.motor-row:last-child{border-bottom:none}
.motor-label{font-size:14px;color:#a0a0a0}
.motor-value{font-size:18px;font-weight:700;color:#7eb8da;font-variant-numeric:tabular-nums}
.motor-value.active{color:#4ecca3}
.log{background:#0f0f23;border-radius:10px;padding:12px;font-size:11px;font-family:monospace;color:#666;max-height:150px;overflow-y:auto;margin-top:12px;border:1px solid #0f3460}
.log div{padding:2px 0;border-bottom:1px solid #111}
.log div:last-child{border-bottom:none}
.hint{font-size:12px;color:#555;text-align:center;margin-top:16px;line-height:1.6}
</style>
</head>
<body>
<div class="container">
<h1>啵啵贝 BLE 桥接</h1>

<div class="status-bar">
<div class="status-dot" id="dot-server"></div>
<div class="status-text" id="text-server">服务未连接</div>
</div>

<div class="status-bar">
<div class="status-dot" id="dot-ble"></div>
<div class="status-text" id="text-ble">玩具未连接</div>
</div>

<button class="btn btn-connect" id="btn-connect" onclick="connectBLE()">连接玩具</button>
<button class="btn btn-stop" id="btn-stop" onclick="stopAll()">全部停止</button>

<div class="motor-display">
<div class="motor-row">
<span class="motor-label">吮吸</span>
<span class="motor-value" id="val-suction">0</span>
</div>
<div class="motor-row">
<span class="motor-label">震动</span>
<span class="motor-value" id="val-vibration">0</span>
</div>
<div class="motor-row">
<span class="motor-label">电流</span>
<span class="motor-value" id="val-electric">0</span>
</div>
</div>

<div class="log" id="log"></div>

<div class="hint">
用 Kiwi Browser 或 Edge 打开此页面<br>
点击"连接玩具"后选择蓝牙设备（名称以 FUNE 或啵啵贝 开头）<br>
页面需保持前台，切后台可能断连<br>
自动保活：每25秒重发指令
</div>
</div>

<script>
// ============================================================
// 常量
// ============================================================
const SERVICE_UUID    = '0000ee01-0000-1000-8000-00805f9b34fb';
const WRITE_CHAR_UUID = '0000ee03-0000-1000-8000-00805f9b34fb';
const NOTIFY_CHAR_UUID= '0000ee02-0000-1000-8000-00805f9b34fb';

const SUCTION_MODE    = 7;
const VIBRATION_MODE  = 1;
const ELECTRIC_MODE   = 3;

const POLL_INTERVAL   = 500;   // 轮询间隔 ms
const KEEPALIVE_INTERVAL = 25000; // 保活间隔 ms
const MAX_WRITE_FAILS = 3;    // 连续写入失败上限

// ============================================================
// 帧构建
// ============================================================
function buildFrame(mode, level) {
    level = Math.max(0, Math.min(100, level | 0));
    return new Uint8Array([
        0x01, 0x01, 0x00, 0x02, 0x00,
        mode & 0xff,
        0x11,
        level & 0xff,
        0x00,
        (mode + 1) & 0xff,
        0x11,
        0x01
    ]);
}

const INIT_FRAME = new Uint8Array([0x01, 0x01, 0x00, 0x01, 0x00, 0xc8, 0x11, 0x01]);

// ============================================================
// 状态
// ============================================================
let btDevice = null;
let gattServer = null;
let writeChar = null;
let notifyChar = null;
let bleConnected = false;
let writeFailCount = 0;
let pollTimer = null;
let keepaliveTimer = null;
let watchdogTimer = null;
let wakeLock = null;

let lastSent = { suction: -1, vibration: -1, electric: -1 };

// ============================================================
// 日志
// ============================================================
function log(msg) {
    const el = document.getElementById('log');
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const div = document.createElement('div');
    div.textContent = '[' + time + '] ' + msg;
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
    // 保留最近30条
    while (el.children.length > 30) el.removeChild(el.firstChild);
}

// ============================================================
// UI 更新
// ============================================================
function updateUI() {
    const dotBle = document.getElementById('dot-ble');
    const textBle = document.getElementById('text-ble');
    const btnConnect = document.getElementById('btn-connect');

    if (bleConnected) {
        dotBle.className = 'status-dot ble';
        textBle.textContent = '玩具已连接';
        btnConnect.textContent = '断开玩具';
        btnConnect.disabled = false;
    } else {
        dotBle.className = 'status-dot';
        textBle.textContent = btDevice ? '玩具已断开 (点击重连)' : '玩具未连接';
        btnConnect.textContent = btDevice ? '重新连接' : '连接玩具';
        btnConnect.disabled = false;
    }
}

function updateMotorDisplay(data) {
    const s = document.getElementById('val-suction');
    const v = document.getElementById('val-vibration');
    const e = document.getElementById('val-electric');
    s.textContent = data.suction;
    v.textContent = data.vibration;
    e.textContent = data.electric;
    s.className = 'motor-value' + (data.suction > 0 ? ' active' : '');
    v.className = 'motor-value' + (data.vibration > 0 ? ' active' : '');
    e.className = 'motor-value' + (data.electric > 0 ? ' active' : '');
}

// ============================================================
// 写入 BLE
// ============================================================
async function writeFrame(frame) {
    if (!writeChar) return false;
    try {
        await writeChar.writeValueWithResponse(frame);
        writeFailCount = 0;
        return true;
    } catch (e) {
        log('writeWithResponse 失败: ' + (e.message || e));
        try {
            await writeChar.writeValueWithoutResponse(frame);
            writeFailCount = 0;
            return true;
        } catch (e2) {
            writeFailCount++;
            log('写入失败 x' + writeFailCount + ': ' + (e2.message || e2));
            if (writeFailCount >= MAX_WRITE_FAILS) {
                log('连续失败 ' + MAX_WRITE_FAILS + ' 次，判定僵尸连接');
                handleZombie();
            }
            return false;
        }
    }
}

async function sendMotor(mode, level) {
    const frame = buildFrame(mode, level);
    return await writeFrame(frame);
}

// ============================================================
// 僵尸连接处理
// ============================================================
function handleZombie() {
    if (btDevice && btDevice.gatt && btDevice.gatt.connected) {
        try { btDevice.gatt.disconnect(); } catch(e) {}
    }
    onBLEDisconnected();
}

// ============================================================
// 连接
// ============================================================
async function connectBLE() {
    if (bleConnected) {
        // 已连接则断开
        if (btDevice && btDevice.gatt && btDevice.gatt.connected) {
            btDevice.gatt.disconnect();
        }
        return;
    }

    if (!navigator.bluetooth) {
        log('此浏览器不支持 Web Bluetooth');
        alert('此浏览器不支持 Web Bluetooth API\n请使用 Kiwi Browser 或 Microsoft Edge');
        return;
    }

    log('正在选择设备...');
    try {
        btDevice = await navigator.bluetooth.requestDevice({
        filters: [{ namePrefix: 'SOSEXY' }],
            optionalServices: [SERVICE_UUID]
        });

        btDevice.addEventListener('gattserverdisconnected', onBLEDisconnected);
        log('设备: ' + btDevice.name);
        await doConnect();
    } catch (e) {
        if (e.name === 'NotFoundError') {
            log('未找到设备，请确认玩具已开机');
        } else {
            log('选择设备失败: ' + (e.message || e));
        }
    }
}

async function doConnect() {
    if (!btDevice) return;
    log('正在连接 GATT...');
    try {
        gattServer = await btDevice.gatt.connect();
        log('GATT 已连接');
        const service = await gattServer.getPrimaryService(SERVICE_UUID);
        writeChar = await service.getCharacteristic(WRITE_CHAR_UUID);
        log('写特征已获取');

        // 尝试订阅通知
        try {
            notifyChar = await service.getCharacteristic(NOTIFY_CHAR_UUID);
            await notifyChar.startNotifications();
            notifyChar.addEventListener('characteristicvaluechanged', onNotify);
            log('通知已订阅');
        } catch(e) {
            log('通知订阅跳过: ' + (e.message || e));
        }

        // 发送握手帧
        await writeFrame(INIT_FRAME);
        log('握手帧已发送');

        bleConnected = true;
        writeFailCount = 0;
        lastSent = { suction: -1, vibration: -1, electric: -1 };

        // 通知服务器
        await fetch('/connected', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ connected: true, ble: true })
        });

        // 启动轮询和保活
        startPolling();
        startKeepalive();
        startWatchdog();

        // 防熄屏
        requestWakeLock();

        updateUI();
        log('全部就绪');
    } catch(e) {
        log('连接失败: ' + (e.message || e));
    }
}

// ============================================================
// 断开处理
// ============================================================
function onBLEDisconnected() {
    bleConnected = false;
    writeChar = null;
    notifyChar = null;
    gattServer = null;
    stopPolling();
    stopKeepalive();
    stopWatchdog();
    releaseWakeLock();

    fetch('/connected', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ connected: false, ble: false })
    }).catch(()=>{});

    updateUI();
    log('玩具已断开');
}

// ============================================================
// 通知处理
// ============================================================
function onNotify(event) {
    const value = event.target.value;
    // 通知数据目前只记录，不做处理
}

// ============================================================
// 轮询
// ============================================================
function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollState, POLL_INTERVAL);
    pollState(); // 立即执行一次
}

function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function pollState() {
    try {
        const res = await fetch('/state');
        const data = await res.json();

        // 检测变化并发送
        if (data.suction !== lastSent.suction) {
            if (bleConnected) await sendMotor(SUCTION_MODE, data.suction);
            lastSent.suction = data.suction;
        }
        if (data.vibration !== lastSent.vibration) {
            if (bleConnected) await sendMotor(VIBRATION_MODE, data.vibration);
            lastSent.vibration = data.vibration;
        }
        if (data.electric !== lastSent.electric) {
            if (bleConnected) await sendMotor(ELECTRIC_MODE, data.electric);
            lastSent.electric = data.electric;
        }

        updateMotorDisplay(data);
    } catch(e) {
        // 轮询失败不报错，静默重试
    }
}

// ============================================================
// 保活
// ============================================================
function startKeepalive() {
    if (keepaliveTimer) clearInterval(keepaliveTimer);
    keepaliveTimer = setInterval(() => {
        // 重置 lastSent 强制重发当前状态
        lastSent = { suction: -1, vibration: -1, electric: -1 };
        pollState();
        log('保活: 重发指令');
    }, KEEPALIVE_INTERVAL);
}

function stopKeepalive() {
    if (keepaliveTimer) { clearInterval(keepaliveTimer); keepaliveTimer = null; }
}

// ============================================================
// 看门狗
// ============================================================
function startWatchdog() {
    if (watchdogTimer) clearInterval(watchdogTimer);
    watchdogTimer = setInterval(() => {
        if (btDevice && btDevice.gatt) {
            if (!btDevice.gatt.connected && bleConnected) {
                log('看门狗: 检测到断连');
                onBLEDisconnected();
            }
        }
    }, 3000);
}

function stopWatchdog() {
    if (watchdogTimer) { clearInterval(watchdogTimer); watchdogTimer = null; }
}

// ============================================================
// 防熄屏
// ============================================================
async function requestWakeLock() {
    try {
        if ('wakeLock' in navigator) {
            wakeLock = await navigator.wakeLock.request('screen');
            log('防熄屏已启用');
        }
    } catch(e) {
        log('防熄屏失败: ' + (e.message || e));
    }
}

function releaseWakeLock() {
    if (wakeLock) {
        try { wakeLock.release(); } catch(e) {}
        wakeLock = null;
    }
}

// 页面重新可见时重新获取 wakeLock
document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState === 'visible' && bleConnected && !wakeLock) {
        await requestWakeLock();
    }
});

// ============================================================
// 停止
// ============================================================
async function stopAll() {
    try {
        await fetch('/stop', { method: 'POST' });
        log('已停止');
    } catch(e) {
        log('停止失败: ' + (e.message || e));
    }
}

// ============================================================
// 服务器状态检查
// ============================================================
async function checkServer() {
    try {
        const res = await fetch('/state');
        const data = await res.json();
        document.getElementById('dot-server').className = 'status-dot online';
        document.getElementById('text-server').textContent = '服务在线';
        updateMotorDisplay(data);
    } catch(e) {
        document.getElementById('dot-server').className = 'status-dot';
        document.getElementById('text-server').textContent = '服务未连接';
    }
}

// 启动时检查服务器
checkServer();
setInterval(checkServer, 2000);

log('页面已加载');
if (!navigator.bluetooth) {
    log('警告: 此浏览器不支持 Web Bluetooth');
}
</script>
</body>
</html>
"""

# ============================================================
# HTTP 处理器
# ============================================================
class ToyHandler(BaseHTTPRequestHandler):

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/state':
            with state_lock:
                self._send_json(dict(state))

        elif parsed.path == '/' or parsed.path == '/relay':
            self._send_html(RELAY_HTML)

        else:
            self._send_json({"error": "not found", "path": parsed.path}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)

        # 读取 body
        content_length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b''
        try:
            body = json.loads(raw_body) if raw_body else {}
        except (json.JSONDecodeError, ValueError):
            body = {}

        if parsed.path == '/suction':
            level = self._clamp(body.get('level', 0))
            with state_lock:
                state['suction'] = level
            self._send_json({"ok": True, "suction": level})

        elif parsed.path == '/vibration':
            level = self._clamp(body.get('level', 0))
            with state_lock:
                state['vibration'] = level
            self._send_json({"ok": True, "vibration": level})

        elif parsed.path == '/electric':
            level = self._clamp(body.get('level', 0))
            with state_lock:
                state['electric'] = level
            self._send_json({"ok": True, "electric": level})

        elif parsed.path == '/stop':
            with state_lock:
                state['suction'] = 0
                state['vibration'] = 0
                state['electric'] = 0
            self._send_json({"ok": True, "suction": 0, "vibration": 0, "electric": 0})

        elif parsed.path == '/connected':
            with state_lock:
                state['connected'] = bool(body.get('connected', False))
                state['ble_connected'] = bool(body.get('ble', False))
            self._send_json({"ok": True})

        else:
            self._send_json({"error": "not found", "path": parsed.path}, 404)

    def log_message(self, fmt, *args):
        # 简洁日志
        import sys
        msg = fmt % args
        if 'POST' in msg or 'GET /state' in msg:
            pass  # 静默常规请求
        else:
            sys.stderr.write("[toy] " + msg + "\n")

    @staticmethod
    def _clamp(val):
        try:
            v = int(val)
        except (TypeError, ValueError):
            v = 0
        return max(0, min(100, v))


# ============================================================
# 主函数
# ============================================================
def main():
    host = '0.0.0.0'
    port = 8765

    # 尝试 ThreadingHTTPServer (Python 3.7+)
    try:
        from http.server import ThreadingHTTPServer
        server_cls = ThreadingHTTPServer
    except ImportError:
        server_cls = HTTPServer

    httpd = server_cls((host, port), ToyHandler)

    print("=" * 50)
    print("  啵啵贝 BLE 控制服务")
    print("  地址: http://localhost:%d" % port)
    print("  用 Kiwi Browser 或 Edge 打开上述地址")
    print("  点击「连接玩具」选择蓝牙设备")
    print("  设备名以 FUNE 开头")
    print("=" * 50)
    print()
    print("控制接口:")
    print("  吮吸:   POST /suction    {\"level\": 0-100}")
    print("  震动:   POST /vibration  {\"level\": 0-100}")
    print("  电流:   POST /electric   {\"level\": 0-100}")
    print("  停止:   POST /stop")
    print("  状态:   GET  /state")
    print()
    print("Ctrl+C 停止服务")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        httpd.shutdown()


if __name__ == '__main__':
    main()
