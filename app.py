from flask import Flask, render_template_string, request, jsonify
import subprocess
import time
import paramiko
from datetime import datetime
import os
import socket

app = Flask(__name__)

# ================= CONFIGURACIÓN =================
# ¡CAMBIAR ESTOS VALORES CON LOS DE TU ROUTER!
ROUTER_IP = "192.168.0.1"        # IP de tu Mercusys
ROUTER_USER = "admin"            # Usuario del router
ROUTER_PASS = "admin"            # Contraseña del router
RED = "192.168.0."               # Rango de red (192.168.0. o 192.168.1.)
# =================================================

dispositivos = {}
dispositivos_bloqueados = set()
ultima_actualizacion = ""

# ========== FUNCIONES ==========
def ejecutar_en_router(comando):
    """Ejecuta un comando SSH en el router"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ROUTER_IP, username=ROUTER_USER, password=ROUTER_PASS, timeout=5)
        stdin, stdout, stderr = ssh.exec_command(comando)
        salida = stdout.read().decode('utf-8')
        ssh.close()
        return salida
    except Exception as e:
        return f"ERROR: {str(e)}"

def escanear_red():
    """Escanea la red y devuelve dispositivos activos"""
    global dispositivos, ultima_actualizacion
    
    dispositivos_activos = []
    
    # Intentar método 1: ARP desde el router (más preciso)
    salida = ejecutar_en_router("arp -a")
    
    if "ERROR" not in salida and salida.strip():
        # Parsear salida ARP
        lineas = salida.split('\n')
        for linea in lineas:
            if '(' in linea and ')' in linea:
                inicio = linea.find('(') + 1
                fin = linea.find(')')
                if inicio > 0 and fin > inicio:
                    ip = linea[inicio:fin]
                    if ip.startswith(RED):
                        dispositivos_activos.append(ip)
        
        # Actualizar diccionario
        for ip in dispositivos_activos:
            if ip not in dispositivos:
                dispositivos[ip] = {
                    'nombre': f"Dispositivo {ip.split('.')[-1]}",
                    'ip': ip,
                    'mac': 'Desconocida',
                    'ultima_vez': datetime.now().strftime("%H:%M:%S"),
                    'bloqueado': ip in dispositivos_bloqueados
                }
            else:
                dispositivos[ip]['ultima_vez'] = datetime.now().strftime("%H:%M:%S")
                dispositivos[ip]['bloqueado'] = ip in dispositivos_bloqueados
    
    else:
        # Método 2: Ping local (alternativa si SSH falla)
        for i in range(1, 255):
            ip = f"{RED}{i}"
            # Ping rápido (1 segundo de timeout)
            if os.name == 'nt':  # Windows
                comando = f"ping -n 1 -w 1000 {ip}"
            else:  # Linux/Mac
                comando = f"ping -c 1 -W 1 {ip}"
            
            resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)
            if resultado.returncode == 0:
                if ip not in dispositivos:
                    dispositivos[ip] = {
                        'nombre': f"Equipo {i}",
                        'ip': ip,
                        'mac': 'Desconocida',
                        'ultima_vez': datetime.now().strftime("%H:%M:%S"),
                        'bloqueado': ip in dispositivos_bloqueados
                    }
                else:
                    dispositivos[ip]['ultima_vez'] = datetime.now().strftime("%H:%M:%S")
                    dispositivos[ip]['bloqueado'] = ip in dispositivos_bloqueados
    
    ultima_actualizacion = datetime.now().strftime("%H:%M:%S")
    return list(dispositivos.values())

def bloquear_ip(ip):
    """Bloquea una IP en el router usando iptables"""
    if ip in dispositivos_bloqueados:
        return False, "⚠️ Ya está bloqueado"
    
    comando = f"iptables -I FORWARD -s {ip} -j DROP"
    resultado = ejecutar_en_router(comando)
    
    if "ERROR" not in resultado:
        dispositivos_bloqueados.add(ip)
        if ip in dispositivos:
            dispositivos[ip]['bloqueado'] = True
        return True, "🚫 Dispositivo BLOQUEADO"
    else:
        return False, f"❌ Error: {resultado[:100]}"

def desbloquear_ip(ip):
    """Desbloquea una IP en el router"""
    if ip not in dispositivos_bloqueados:
        return False, "⚠️ No estaba bloqueado"
    
    comando = f"iptables -D FORWARD -s {ip} -j DROP"
    resultado = ejecutar_en_router(comando)
    
    if "ERROR" not in resultado:
        dispositivos_bloqueados.discard(ip)
        if ip in dispositivos:
            dispositivos[ip]['bloqueado'] = False
        return True, "✅ Dispositivo DESBLOQUEADO"
    else:
        return False, f"❌ Error: {resultado[:100]}"

# ========== INTERFAZ WEB ==========
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>🏠 Control WiFi</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: #0a0e17; color: #e0e0e0; padding: 16px; min-height: 100vh; }
        .container { max-width: 600px; margin: 0 auto; }
        .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
        h1 { font-size: 24px; font-weight: 700; color: #00d4ff; }
        .badge-cloud { background: #00d4ff22; border: 1px solid #00d4ff44; padding: 4px 14px; border-radius: 30px; font-size: 10px; color: #00d4ff; display: inline-block; margin-bottom: 8px; }
        .subtitle { color: #8899aa; font-size: 14px; margin-bottom: 16px; }
        .card { background: #141b2b; border-radius: 14px; padding: 16px; margin-bottom: 12px; border: 1px solid #1e2a3a; transition: all 0.2s; }
        .card:active { transform: scale(0.98); }
        .card-header { display: flex; justify-content: space-between; align-items: center; }
        .device-name { font-size: 16px; font-weight: 600; color: #fff; }
        .device-ip { font-size: 12px; color: #7a8a9e; font-family: monospace; margin-top: 2px; }
        .device-status { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 13px; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .status-dot.online { background: #00e676; box-shadow: 0 0 12px #00e67666; }
        .status-dot.blocked { background: #ff9100; box-shadow: 0 0 12px #ff910066; }
        .btn { padding: 8px 18px; border: none; border-radius: 30px; font-weight: 600; font-size: 13px; cursor: pointer; min-width: 90px; transition: all 0.2s; }
        .btn-block { background: #ff1744; color: white; }
        .btn-block:hover { background: #d50000; transform: scale(1.02); }
        .btn-unblock { background: #00e676; color: #0a0e17; }
        .btn-unblock:hover { background: #00c853; transform: scale(1.02); }
        .btn-refresh { background: #00d4ff; color: #0a0e17; padding: 12px; width: 100%; border: none; border-radius: 30px; font-weight: 700; font-size: 16px; cursor: pointer; margin-top: 8px; transition: all 0.2s; }
        .btn-refresh:hover { background: #00b8d4; transform: scale(1.01); }
        .btn-refresh:active { transform: scale(0.97); }
        .badge-mac { background: #1e2a3a; padding: 3px 12px; border-radius: 30px; font-size: 10px; color: #7a8a9e; }
        .last-seen { font-size: 11px; color: #556677; margin-top: 6px; }
        .input-group { display: flex; gap: 8px; margin-top: 8px; }
        .input-group input { flex: 1; background: #0a0e17; border: 1px solid #1e2a3a; color: white; padding: 6px 12px; border-radius: 30px; font-size: 13px; }
        .input-group input:focus { outline: none; border-color: #00d4ff; }
        .input-group button { background: #00d4ff; color: #0a0e17; border: none; border-radius: 30px; padding: 6px 16px; font-weight: 600; cursor: pointer; }
        .toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #1e2a3a; color: white; padding: 12px 24px; border-radius: 30px; font-size: 14px; display: none; z-index: 999; border: 1px solid #00d4ff44; max-width: 90%; text-align: center; }
        .count { color: #7a8a9e; font-size: 14px; }
        .update-time { color: #556677; font-size: 11px; margin-top: 12px; text-align: center; }
        .empty-state { text-align: center; padding: 40px 20px; color: #556677; }
        .empty-state .icon { font-size: 48px; margin-bottom: 12px; }
        .loading { text-align: center; padding: 20px; color: #556677; }
        .spinner { display: inline-block; animation: spin 1s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>📡 Mi Red</h1>
        <span class="badge-cloud">☁️ Cloud</span>
    </div>
    <div class="subtitle">Dispositivos conectados <span class="count" id="count">0</span></div>
    
    <div id="device-list"><div class="loading"><span class="spinner">🔄</span> Cargando...</div></div>
    
    <button class="btn-refresh" onclick="refresh()">🔄 Actualizar</button>
    <div class="update-time" id="update-time">Última actualización: --</div>
</div>

<div id="toast" class="toast"></div>

<script>
    let isLoading = false;
    
    async function refresh() {
        if (isLoading) return;
        isLoading = true;
        
        try {
            const res = await fetch('/api/devices');
            const data = await res.json();
            renderDevices(data);
            document.getElementById('count').textContent = data.length;
            document.getElementById('update-time').textContent = 'Última actualización: ' + new Date().toLocaleTimeString();
        } catch (e) {
            showToast('❌ Error al conectar');
        }
        isLoading = false;
    }
    
    function renderDevices(devices) {
        const container = document.getElementById('device-list');
        if (!devices || devices.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="icon">📭</div>
                    <div>No hay dispositivos activos</div>
                    <div style="font-size:12px;margin-top:8px;">Prueba a actualizar</div>
                </div>
            `;
            return;
        }
        
        container.innerHTML = devices.map(d => {
            const isBlocked = d.bloqueado || false;
            const statusClass = isBlocked ? 'blocked' : 'online';
            const statusText = isBlocked ? '🚫 Bloqueado' : '✅ Conectado';
            const btnHtml = isBlocked 
                ? `<button class="btn btn-unblock" onclick="toggleBlock('${d.ip}')">Desbloquear</button>`
                : `<button class="btn btn-block" onclick="toggleBlock('${d.ip}')">Bloquear</button>`;
            
            return `
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="device-name">${d.nombre || 'Sin nombre'}</div>
                            <div class="device-ip">${d.ip}</div>
                        </div>
                        ${btnHtml}
                    </div>
                    <div class="device-status">
                        <span class="status-dot ${statusClass}"></span>
                        <span>${statusText}</span>
                        <span class="badge-mac">${d.mac || 'MAC'}</span>
                    </div>
                    <div class="last-seen">Última vez: ${d.ultima_vez || 'hace un momento'}</div>
                    <div class="input-group">
                        <input type="text" placeholder="Poner nombre..." id="name-${d.ip}" value="${d.nombre || ''}">
                        <button onclick="rename('${d.ip}')">Guardar</button>
                    </div>
                </div>
            `;
        }).join('');
    }
    
    async function toggleBlock(ip) {
        try {
            const res = await fetch('/api/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip: ip })
            });
            const data = await res.json();
            showToast(data.message);
            refresh();
        } catch (e) {
            showToast('❌ Error al ejecutar');
        }
    }
    
    async function rename(ip) {
        const input = document.getElementById(`name-${ip}`);
        if (!input) return;
        
        try {
            const res = await fetch('/api/rename', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip: ip, nombre: input.value })
            });
            const data = await res.json();
            showToast(data.message);
            refresh();
        } catch (e) {
            showToast('❌ Error al guardar');
        }
    }
    
    function showToast(msg) {
        const t = document.getElementById('toast');
        t.textContent = msg;
        t.style.display = 'block';
        clearTimeout(t._timeout);
        t._timeout = setTimeout(() => t.style.display = 'none', 3000);
    }
    
    // Cargar al inicio
    refresh();
    // Actualizar cada 15 segundos
    setInterval(refresh, 15000);
</script>
</body>
</html>
"""

# ========== RUTAS DE LA API ==========
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/devices')
def api_devices():
    return jsonify(escanear_red())

@app.route('/api/toggle', methods=['POST'])
def api_toggle():
    data = request.json
    ip = data.get('ip')
    
    if not ip:
        return jsonify({'success': False, 'message': 'IP no proporcionada'})
    
    if ip in dispositivos_bloqueados:
        success, msg = desbloquear_ip(ip)
    else:
        success, msg = bloquear_ip(ip)
    
    return jsonify({'success': success, 'message': msg})

@app.route('/api/rename', methods=['POST'])
def api_rename():
    data = request.json
    ip = data.get('ip')
    nombre = data.get('nombre')
    
    if ip in dispositivos:
        dispositivos[ip]['nombre'] = nombre
        return jsonify({'success': True, 'message': f'✅ Nombre actualizado a "{nombre}"'})
    
    return jsonify({'success': False, 'message': '❌ Dispositivo no encontrado'})

# ========== INICIAR SERVIDOR ==========
if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════╗
║   🚀 PANEL DE CONTROL WIFI EN LA NUBE              ║
║   Servidor iniciado en: http://0.0.0.0:10000       ║
║   ¡Desplegar en Render.com!                        ║
╚══════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=10000)