import logging
import os
import sys
import subprocess
import time
import io
import signal
import psutil
import pandas as pd
import numpy as np
import matplotlib

# Django Modelleri ve Bilimsel Kütüphaneler (Hata kontrolü ile)
try:
    from django.db.models import Max
    from scanner.models import Scan, ScanPoint
    from scipy.spatial import ConvexHull
    from sklearn.cluster import DBSCAN
    from sklearn.linear_model import RANSACRegressor

    DJANGO_MODELS_AVAILABLE = True
    print("Dashboard: Django ve bilimsel kütüphaneler başarıyla import edildi.")
except Exception as e:
    print(f"UYARI: Gerekli kütüphaneler import edilemedi: {e}.")
    DJANGO_MODELS_AVAILABLE = False
    Scan, ScanPoint, ConvexHull, DBSCAN, RANSACRegressor = None, None, None, None, None

# Dash Kütüphaneleri
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, no_update, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

# Google AI Kütüphanesi (Opsiyonel)
try:
    import google.generativeai as genai

    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    print("UYARI: 'google.generativeai' kütüphanesi bulunamadı. AI özellikleri çalışmayacak.")
    GOOGLE_GENAI_AVAILABLE = False

from dotenv import load_dotenv

load_dotenv()
google_api_key = os.getenv("GOOGLE_API_KEY")

# --- SABİTLER VE UYGULAMA BAŞLATMA ---
SENSOR_SCRIPT_FILENAME = 'sensor_script.py'
AUTONOMOUS_DRIVE_SCRIPT_FILENAME = 'autonomous_drive.py'

APP_DIR = os.getcwd()
SENSOR_SCRIPT_PATH = os.path.join(APP_DIR, SENSOR_SCRIPT_FILENAME)
AUTONOMOUS_DRIVE_SCRIPT_PATH = os.path.join(APP_DIR, AUTONOMOUS_DRIVE_SCRIPT_FILENAME)

SENSOR_PID_FILE = '/tmp/sensor_scan_script.pid'
SENSOR_LOCK_FILE = '/tmp/sensor_scan_script.lock'
AUTONOMOUS_PID_FILE = '/tmp/autonomous_drive.pid'
AUTONOMOUS_LOCK_FILE = '/tmp/autonomous_drive.lock'

DEFAULT_UI_SCAN_DURATION_ANGLE = 270.0
DEFAULT_UI_SCAN_STEP_ANGLE = 10.0
DEFAULT_UI_BUZZER_DISTANCE = 10
DEFAULT_UI_INVERT_MOTOR = False
DEFAULT_UI_STEPS_PER_REVOLUTION = 4096

app = DjangoDash('RealtimeSensorDashboard', external_stylesheets=[dbc.themes.BOOTSTRAP])

# --- LAYOUT OLUŞTURMA (TAM SÜRÜM) ---
navbar = dbc.NavbarSimple(brand="Dream Pi", brand_href="/", color="primary", dark=True, sticky="top")
title_card = dbc.Row([dbc.Col(html.H1("Kullanıcı Paneli", className="text-center my-3"), width=12), html.Hr()])

control_panel = dbc.Card([
    dbc.CardHeader("Kontrol ve Ayarlar"),
    dbc.CardBody([
        html.H6("Çalışma Modu:"),
        dbc.RadioItems(id='mode-selection-radios', options=[
            {'label': '3D Haritalama Modu', 'value': 'scan_and_map'},
            {'label': 'Otonom Sürüş Modu', 'value': 'autonomous_drive'},
        ], value='scan_and_map', className="mb-3"),
        html.Hr(),
        dbc.Row([
            dbc.Col(html.Button('Başlat', id='start-scan-button', className="btn btn-success w-100"), width=6),
            dbc.Col(html.Button('Durdur', id='stop-scan-button', className="btn btn-danger w-100"), width=6)
        ]),
        html.Div(id='scan-status-message', className="text-center mt-3"),
        html.Hr(),
        html.Div(id='scan-parameters-wrapper', children=[
            html.H6("Haritalama Parametreleri:"),
            dbc.InputGroup([dbc.InputGroupText("Tarama Açısı (°)"),
                            dbc.Input(id="scan-duration-angle-input", type="number",
                                      value=DEFAULT_UI_SCAN_DURATION_ANGLE)]),
            dbc.InputGroup([dbc.InputGroupText("Adım Açısı (°)"),
                            dbc.Input(id="step-angle-input", type="number", value=DEFAULT_UI_SCAN_STEP_ANGLE)],
                           className="mt-2"),
            dbc.InputGroup([dbc.InputGroupText("Uyarı Mes. (cm)"),
                            dbc.Input(id="buzzer-distance-input", type="number", value=DEFAULT_UI_BUZZER_DISTANCE)],
                           className="mt-2"),
            dbc.InputGroup([dbc.InputGroupText("Motor Adım/Tur"),
                            dbc.Input(id="steps-per-rev-input", type="number", value=DEFAULT_UI_STEPS_PER_REVOLUTION)],
                           className="mt-2"),
            dbc.Checkbox(id="invert-motor-checkbox", label="Motor Yönünü Ters Çevir", value=DEFAULT_UI_INVERT_MOTOR,
                         className="mt-2"),
        ])
    ])
])

stats_panel = dbc.Card([
    dbc.CardHeader("Anlık Sensör Değerleri"),
    dbc.CardBody(dbc.Row([
        dbc.Col(html.Div([html.H6("Mevcut Açı:"), html.H4(id='current-angle', children="--°")]),
                className="text-center"),
        dbc.Col(html.Div([html.H6("Mevcut Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
                id='current-distance-col', className="text-center"),
        dbc.Col(html.Div([html.H6("Anlık Hız:"), html.H4(id='current-speed', children="-- cm/s")]),
                className="text-center"),
        dbc.Col(html.Div([html.H6("Max Mesafe:"), html.H4(id='max-detected-distance', children="-- cm")]),
                className="text-center")
    ]))
])

system_card = dbc.Card([
    dbc.CardHeader("Sistem Durumu"),
    dbc.CardBody([
        dbc.Row([dbc.Col(html.Div([html.H6("Aktif Mod Durumu:"), html.H5(id='script-status', children="Beklemede")]))]),
        dbc.Row([
            dbc.Col(html.Div([html.H6("CPU:"), dbc.Progress(id='cpu-usage', label="0%", value=0)])),
            dbc.Col(html.Div([html.H6("RAM:"), dbc.Progress(id='ram-usage', label="0%", value=0)]))
        ])
    ])
])

export_card = dbc.Card([
    dbc.CardHeader("Veri Dışa Aktarma"),
    dbc.CardBody([
        dbc.Button('CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
        dcc.Download(id='download-csv'),
        dbc.Button('Excel İndir', id='export-excel-button', color="success", className="w-100"),
        dcc.Download(id='download-excel')
    ])
])

analysis_card = dbc.Card([
    dbc.CardHeader("Tarama Analizi (En Son Tarama)"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([html.H6("Hesaplanan Alan:"), html.H4(id='calculated-area', children="-- cm²")]),
            dbc.Col([html.H6("Çevre Uzunluğu:"), html.H4(id='perimeter-length', children="-- cm")])
        ]),
        dbc.Row([
            dbc.Col([html.H6("Max Genişlik:"), html.H4(id='max-width', children="-- cm")]),
            dbc.Col([html.H6("Max Derinlik:"), html.H4(id='max-depth', children="-- cm")])
        ], className="mt-2")
    ])
])

estimation_card = dbc.Card([
    dbc.CardHeader("Akıllı Ortam Analizi"),
    dbc.CardBody(html.Div("Tahmin: Bekleniyor...", id='environment-estimation-text'))
])

visualization_tabs = dbc.Tabs([
    dbc.Tab(dcc.Graph(id='scan-map-graph-3d', style={'height': '75vh'}), label="3D Harita"),
    dbc.Tab(dcc.Graph(id='scan-map-graph', style={'height': '75vh'}), label="2D Harita"),
    # Diğer grafikler için tablar eklenebilir
])

app.layout = html.Div(style={'padding': '20px'}, children=[
    navbar,
    title_card,
    dbc.Row([
        dbc.Col([
            control_panel, html.Br(),
            stats_panel, html.Br(),
            system_card, html.Br(),
            export_card, html.Br(),
            analysis_card, html.Br(),
            estimation_card
        ], md=4),
        dbc.Col(visualization_tabs, md=8)
    ]),
    dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0),
    dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0),
    dcc.Store(id='clustered-data-store')
])


# --- YARDIMCI FONKSİYONLAR ---
def is_process_running(pid):
    if pid is None: return False
    try:
        return psutil.pid_exists(pid)
    except:
        return False


def get_latest_scan():
    if not DJANGO_MODELS_AVAILABLE: return None
    try:
        running = Scan.objects.filter(status=Scan.Status.RUNNING).order_by('-start_time').first()
        if running: return running
        return Scan.objects.order_by('-start_time').first()
    except Exception as e:
        print(f"DB Hatası (get_latest_scan): {e}")
        return None


# --- CALLBACKS (TAM VE DÜZELTİLMİŞ) ---

# Callback: Mod seçimine göre parametre görünürlüğü
@app.callback(
    Output('scan-parameters-wrapper', 'style'),
    Input('mode-selection-radios', 'value')
)
def toggle_parameter_visibility(selected_mode):
    return {'display': 'block'} if selected_mode == 'scan_and_map' else {'display': 'none'}


# Callback: Script başlatma
@app.callback(
    Output('scan-status-message', 'children'),
    [Input('start-scan-button', 'n_clicks')],
    [State('mode-selection-radios', 'value'),
     State('scan-duration-angle-input', 'value'),
     State('step-angle-input', 'value'),
     State('buzzer-distance-input', 'value'),
     State('invert-motor-checkbox', 'value'),
     State('steps-per-rev-input', 'value')],
    prevent_initial_call=True
)
def handle_start_script(n_clicks, mode, duration, step, buzzer, invert, steps_rev):
    if n_clicks == 0: return no_update

    pid_file, script_path, cmd = None, None, []
    py_exec = sys.executable

    if mode == 'scan_and_map':
        pid_file, script_path = SENSOR_PID_FILE, SENSOR_SCRIPT_PATH
        cmd = [py_exec, script_path, "--h-angle", str(duration), "--h-step", str(step), "--buzzer-distance",
               str(buzzer), "--invert-motor-direction", str(bool(invert)), "--steps-per-rev", str(steps_rev)]
    elif mode == 'autonomous_drive':
        pid_file, script_path = AUTONOMOUS_PID_FILE, AUTONOMOUS_DRIVE_SCRIPT_PATH
        cmd = [py_exec, script_path]
    else:
        return dbc.Alert("Geçersiz mod.", color="danger")

    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as pf:
                pid = int(pf.read().strip())
            if is_process_running(pid):
                return dbc.Alert(f"Mod zaten çalışıyor (PID:{pid}).", color="warning")
        except:
            pass

    try:
        print(f"Çalıştırılacak komut: {' '.join(cmd)}")
        subprocess.Popen(cmd, start_new_session=True)
        time.sleep(2)
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as pf:
                pid = pf.read().strip()
            return dbc.Alert(f"{mode.replace('_', ' ').title()} başlatıldı (PID:{pid}).", color="success")
        return dbc.Alert("Başlatılamadı.", color="danger")
    except Exception as e:
        return dbc.Alert(f"Başlatma hatası: {e}", color="danger")


# Callback: Script durdurma
@app.callback(
    Output('scan-status-message', 'children', allow_duplicate=True),
    Input('stop-scan-button', 'n_clicks'),
    State('mode-selection-radios', 'value'),
    prevent_initial_call=True
)
def handle_stop_script(n_clicks, mode):
    if n_clicks == 0: return no_update

    pid_file = SENSOR_PID_FILE if mode == 'scan_and_map' else AUTONOMOUS_PID_FILE
    lock_file = SENSOR_LOCK_FILE if mode == 'scan_and_map' else AUTONOMOUS_LOCK_FILE

    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as pf:
                pid = int(pf.read().strip())
            if is_process_running(pid):
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                if is_process_running(pid): os.kill(pid, signal.SIGKILL)
                msg = f"Betik (PID:{pid}) durduruldu."
                color = "info"
            else:
                msg = "PID dosyası var ama süreç çalışmıyor. Temizleniyor."
                color = "warning"
        except Exception as e:
            msg = f"Durdurma hatası: {e}";
            color = "danger"
    else:
        msg = "Çalışan betik bulunamadı.";
        color = "warning"

    for fp in [pid_file, lock_file]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except:
                pass

    return dbc.Alert(msg, color=color)


# Callback: Sistem durumu (CPU, RAM, Aktif Mod)
@app.callback(
    [Output('script-status', 'children'), Output('script-status', 'className'),
     Output('cpu-usage', 'value'), Output('cpu-usage', 'label'),
     Output('ram-usage', 'value'), Output('ram-usage', 'label')],
    Input('interval-component-system', 'n_intervals'),
    State('mode-selection-radios', 'value')
)
def update_system_card(n, mode):
    pid_file = SENSOR_PID_FILE if mode == 'scan_and_map' else AUTONOMOUS_PID_FILE
    mode_name = "Haritalama" if mode == 'scan_and_map' else "Otonom Sürüş"

    status_text, status_class = f"{mode_name}: Çalışmıyor", "text-danger"
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as pf:
                pid = int(pf.read().strip())
            if is_process_running(pid):
                status_text, status_class = f"{mode_name}: Çalışıyor (PID:{pid})", "text-success"
        except:
            pass

    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    return status_text, status_class, cpu, f"{cpu:.1f}%", ram, f"{ram:.1f}%"


# Callback: Anlık değerler (Açı, Mesafe vb.)
@app.callback(
    [Output('current-angle', 'children'), Output('current-distance', 'children'),
     Output('current-speed', 'children'), Output('current-distance-col', 'style'),
     Output('max-detected-distance', 'children')],
    Input('interval-component-main', 'n_intervals')
)
def update_realtime_values(n):
    scan = get_latest_scan()
    if not scan or not DJANGO_MODELS_AVAILABLE: return "--°", "-- cm", "-- cm/s", {}, "-- cm"

    point = scan.points.order_by('-timestamp').first()
    if not point: return "--°", "-- cm", "-- cm/s", {}, "-- cm"

    angle = f"{point.derece:.1f}°" if pd.notnull(point.derece) else "--°"
    dist = f"{point.mesafe_cm:.1f} cm" if pd.notnull(point.mesafe_cm) else "-- cm"
    speed = f"{getattr(point, 'hiz_cm_s', 0):.1f} cm/s" if hasattr(point, 'hiz_cm_s') and pd.notnull(
        getattr(point, 'hiz_cm_s', 0)) else "-- cm/s"

    style = {'padding': '5px', 'borderRadius': '5px', 'transition': 'background-color 0.5s ease'}
    if scan.buzzer_distance_setting and pd.notnull(
            point.mesafe_cm) and 0 < point.mesafe_cm <= scan.buzzer_distance_setting:
        style.update({'backgroundColor': '#d9534f', 'color': 'white'})

    max_dist_agg = scan.points.filter(mesafe_cm__lt=3000, mesafe_cm__gt=0).aggregate(Max('mesafe_cm'))
    max_dist = f"{max_dist_agg['mesafe_cm__max']:.1f} cm" if max_dist_agg and max_dist_agg.get(
        'mesafe_cm__max') else "-- cm"

    return angle, dist, speed, style, max_dist


# Callback: Analiz paneli
@app.callback(
    [Output('calculated-area', 'children'), Output('perimeter-length', 'children'),
     Output('max-width', 'children'), Output('max-depth', 'children')],
    Input('interval-component-main', 'n_intervals')
)
def update_analysis_panel(n):
    scan = get_latest_scan()
    if not scan or not DJANGO_MODELS_AVAILABLE: return "N/A", "N/A", "N/A", "N/A"

    area = f"{scan.calculated_area_cm2:.1f} cm²" if pd.notnull(scan.calculated_area_cm2) else "N/A"
    perim = f"{scan.perimeter_cm:.1f} cm" if pd.notnull(scan.perimeter_cm) else "N/A"
    width = f"{scan.max_width_cm:.1f} cm" if pd.notnull(scan.max_width_cm) else "N/A"
    depth = f"{scan.max_depth_cm:.1f} cm" if pd.notnull(scan.max_depth_cm) else "N/A"
    return area, perim, width, depth


# Callback: Veri İndirme (CSV ve Excel)
@app.callback(
    Output('download-csv', 'data'),
    Input('export-csv-button', 'n_clicks'),
    prevent_initial_call=True)
def export_csv(n_clicks):
    if not n_clicks: return no_update
    scan = get_latest_scan()
    if not scan: return dcc.send_data_frame(pd.DataFrame().to_csv, "tarama_yok.csv")
    points = scan.points.all().values()
    df = pd.DataFrame(list(points))
    return dcc.send_data_frame(df.to_csv, f"scan_{scan.id}.csv", index=False)


@app.callback(
    Output('download-excel', 'data'),
    Input('export-excel-button', 'n_clicks'),
    prevent_initial_call=True)
def export_excel(n_clicks):
    if not n_clicks: return no_update
    scan = get_latest_scan()
    if not scan: return dcc.send_bytes(b"", "tarama_yok.xlsx")
    points_df = pd.DataFrame(list(scan.points.all().values()))
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            points_df.to_excel(writer, sheet_name='ScanPoints', index=False)
        return dcc.send_bytes(buffer.getvalue(), f"scan_{scan.id}.xlsx")


# Callback: Grafik Güncelleme ve Akıllı Tahmin
@app.callback(
    [Output('scan-map-graph-3d', 'figure'),
     Output('scan-map-graph', 'figure'),
     Output('environment-estimation-text', 'children')],
    Input('interval-component-main', 'n_intervals')
)
def update_all_graphs_and_estimation(n):
    scan = get_latest_scan()
    if not scan or not DJANGO_MODELS_AVAILABLE:
        empty_fig = go.Figure().update_layout(title="Veri Bekleniyor...")
        return empty_fig, empty_fig, "Veri bekleniyor..."

    points = scan.points.filter(mesafe_cm__gt=0).values('x_cm', 'y_cm', 'z_cm')
    if not points.exists():
        empty_fig = go.Figure().update_layout(title=f"Tarama #{scan.id} için nokta verisi yok")
        return empty_fig, empty_fig, "Nokta verisi yok."

    df = pd.DataFrame(list(points))

    fig_3d = go.Figure(data=[go.Scatter3d(
        x=df['y_cm'], y=df['x_cm'], z=df['z_cm'], mode='markers',
        marker=dict(size=2, color=df['z_cm'], colorscale='Viridis', showscale=True)
    )])
    fig_3d.update_layout(title_text='3D Harita', scene=dict(aspectmode='data'))

    fig_2d = go.Figure(data=[go.Scatter(
        x=df['y_cm'], y=df['x_cm'], mode='markers', marker=dict(size=4)
    )])
    fig_2d.update_layout(title_text='2D Projeksiyon', yaxis_scaleanchor="x", yaxis_scaleratio=1)

    # Basit bir tahmin mantığı
    estimation_text = "Analiz için yetersiz veri."
    if len(df) > 10:
        if df['y_cm'].std() > df['x_cm'].std() * 2:
            estimation_text = "Tahmin: Geniş bir alan veya duvar."
        elif df['x_cm'].std() > df['y_cm'].std() * 2:
            estimation_text = "Tahmin: Dar bir koridor veya geçit."
        else:
            estimation_text = "Tahmin: Düzensiz veya kutu benzeri bir alan."

    return fig_3d, fig_2d, estimation_text
