# ==============================================================================
# GEREKLİ KÜTÜPHANELER
# ==============================================================================
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
from dotenv import load_dotenv

# --- Bilimsel ve AI Kütüphaneleri (Hata Kontrolü ile) ---
try:
    from scipy.spatial import ConvexHull
    from sklearn.cluster import DBSCAN
except ImportError as e:
    print(f"UYARI: Bilimsel kütüphaneler yüklenemedi: {e}.")

try:
    import google.generativeai as genai
    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    print("UYARI: 'google.generativeai' kütüphanesi bulunamadı.")
    GOOGLE_GENAI_AVAILABLE = False
    genai = None

# --- Django Modelleri (Hata Kontrolü ile) ---
try:
    from django.db.models import Max
    from scanner.models import Scan, ScanPoint
    DJANGO_MODELS_AVAILABLE = True
    print("Bilgi: Django modelleri başarıyla import edildi.")
except Exception as e:
    print(f"UYARI: Django modelleri import edilemedi. Hata: {e}")
    DJANGO_MODELS_AVAILABLE = False
    Scan, ScanPoint = None, None

# --- Dash ve Plotly Kütüphaneleri ---
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, no_update, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

# ==============================================================================
# YAPILANDIRMA VE SABİTLER
# ==============================================================================
load_dotenv()
google_api_key = os.getenv("GOOGLE_API_KEY")
if GOOGLE_GENAI_AVAILABLE and google_api_key:
    try:
        genai.configure(api_key=google_api_key)
        print("Bilgi: Google Generative AI başarıyla yapılandırıldı.")
    except Exception as e:
        print(f"HATA: Google Generative AI yapılandırılamadı: {e}")
        GOOGLE_GENAI_AVAILABLE = False
elif GOOGLE_GENAI_AVAILABLE:
    print("UYARI: GOOGLE_API_KEY ortam değişkeni bulunamadı.")

SENSOR_SCRIPT_FILENAME = 'sensor_script.py'
APP_DIR = os.getcwd()
SENSOR_SCRIPT_PATH = os.path.join(APP_DIR, SENSOR_SCRIPT_FILENAME)
SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'
SENSOR_SCRIPT_LOCK_FILE = '/tmp/sensor_scan_script.lock'

# Varsayılan Arayüz Değerleri
DEFAULT_UI_SCAN_DURATION_ANGLE = 270.0
DEFAULT_UI_SCAN_STEP_ANGLE = 10.0
DEFAULT_UI_BUZZER_DISTANCE = 10
DEFAULT_UI_STEPS_PER_REVOLUTION = 4096

app = DjangoDash('RealtimeSensorDashboard', external_stylesheets=[dbc.themes.BOOTSTRAP])

# ==============================================================================
# ARAYÜZ (LAYOUT)
# ==============================================================================
navbar = dbc.NavbarSimple(brand="Dream Pi 3D Scanner", brand_href="/", color="primary", dark=True, sticky="top")

control_panel = dbc.Card([
    dbc.CardHeader("Kontrol ve Ayarlar", className="bg-primary text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col(html.Button('Başlat', id='start-scan-button', className="btn btn-success w-100"), width=6),
            dbc.Col(html.Button('Durdur', id='stop-scan-button', className="btn btn-danger w-100"), width=6)
        ]),
        html.Div(id='scan-status-message', className="text-center mt-3", style={'minHeight': '40px'}),
        html.Hr(),
        html.H6("Tarama Parametreleri:"),
        dbc.InputGroup([dbc.InputGroupText("Yatay Tarama Açısı (°)", style={"width": "180px"}), dbc.Input(id="scan-duration-angle-input", type="number", value=DEFAULT_UI_SCAN_DURATION_ANGLE)], className="mb-2"),
        dbc.InputGroup([dbc.InputGroupText("Yatay Adım Açısı (°)", style={"width": "180px"}), dbc.Input(id="step-angle-input", type="number", value=DEFAULT_UI_SCAN_STEP_ANGLE)], className="mb-2"),
        dbc.InputGroup([dbc.InputGroupText("Uyarı Mesafesi (cm)", style={"width": "180px"}), dbc.Input(id="buzzer-distance-input", type="number", value=DEFAULT_UI_BUZZER_DISTANCE)], className="mb-2"),
        dbc.InputGroup([dbc.InputGroupText("Motor Adım/Tur", style={"width": "180px"}), dbc.Input(id="steps-per-rev-input", type="number", value=DEFAULT_UI_STEPS_PER_REVOLUTION)], className="mb-2"),
    ])
])

stats_panel = dbc.Card([
    dbc.CardHeader("Anlık Sensör Değerleri", className="bg-info text-white"),
    dbc.CardBody(dbc.Row([
        dbc.Col(html.Div([html.H6("Yatay Açı:"), html.H4(id='current-angle', children="--°")]), className="text-center"),
        dbc.Col(html.Div([html.H6("Dikey Açı:"), html.H4(id='current-vertical-angle', children="--°")]), className="text-center"),
        dbc.Col(html.Div([html.H6("Mesafe:"), html.H4(id='current-distance', children="-- cm")]), id='current-distance-col', className="text-center"),
    ]))
])

system_card = dbc.Card([
    dbc.CardHeader("Sistem Durumu", className="bg-secondary text-white"),
    dbc.CardBody([
        dbc.Row([dbc.Col(html.Div([html.H6("Sensör Betiği:"), html.H5(id='script-status', children="Beklemede")]))], className="mb-2"),
        dbc.Row([
            dbc.Col(html.Div([html.H6("CPU:"), dbc.Progress(id='cpu-usage', label="0%", value=0)])),
            dbc.Col(html.Div([html.H6("RAM:"), dbc.Progress(id='ram-usage', label="0%", value=0)]))
        ])
    ])
])

ai_and_analysis_tabs = dbc.Tabs([
    dbc.Tab(dcc.Loading(html.Div(id='geometric-estimation-text', className="p-3 text-center")), label="Geometrik Tahmin"),
    dbc.Tab(dcc.Loading(html.Div(id='ai-commentary-text', className="p-3")), label="Gemini Yorumu"),
])

visualization_tabs = dbc.Tabs([
    dbc.Tab(dcc.Loading(dcc.Graph(id='graph-3d-map')), label="3D Harita"),
    dbc.Tab(dcc.Loading(dcc.Graph(id='graph-2d-map')), label="2D Üstten Görünüm"),
    dbc.Tab(dcc.Loading(dcc.Graph(id='graph-h-angle-dist')), label="Yatay Açı Grafiği"),
    dbc.Tab(dcc.Loading(dcc.Graph(id='graph-v-angle-dist')), label="Dikey Açı Grafiği"),
    dbc.Tab(dcc.Loading(html.Div(id='tab-content-datatable', className="p-2")), label="Veri Tablosu")
])

app.layout = html.Div(style={'padding': '20px'}, children=[
    navbar,
    html.H1("3D Tarayıcı Kontrol Paneli", className="text-center my-3"),
    html.Hr(),
    dbc.Row([
        dbc.Col([control_panel, html.Br(), stats_panel, html.Br(), system_card], md=4),
        dbc.Col([
            visualization_tabs, html.Br(), ai_and_analysis_tabs
        ], md=8)
    ]),
    dcc.Store(id='scan-data-store'),
    dcc.Interval(id='interval-component-main', interval=3500, n_intervals=0),
    dcc.Interval(id='interval-component-system', interval=5000, n_intervals=0),
])

# ==============================================================================
# YARDIMCI FONKSİYONLAR
# ==============================================================================

def is_process_running(pid):
    if pid is None: return False
    try: return psutil.pid_exists(pid)
    except: return False

def get_latest_scan():
    if not DJANGO_MODELS_AVAILABLE: return None
    try:
        running = Scan.objects.filter(status='RUNNING').order_by('-start_time').first()
        if running: return running
        return Scan.objects.order_by('-start_time').first()
    except Exception as e:
        print(f"DB Hatası (get_latest_scan): {e}"); return None

def estimate_geometric_shape(df):
    if df is None or len(df) < 10: return "Şekil tahmini için yetersiz nokta."
    try:
        points = df[['x_cm', 'y_cm']].values; hull = ConvexHull(points)
        width = df['y_cm'].max() - df['y_cm'].min(); depth = df['x_cm'].max()
        if width < 1 or depth < 1: return "Algılanan şekil çok küçük."
        fill_factor = hull.volume / (width * depth) if (width * depth) > 0 else 0
        if depth > 150 and width < 50 and fill_factor < 0.3: return "Tahmin: Dar ve derin bir boşluk (Koridor)."
        if fill_factor > 0.7: return "Tahmin: Dolgun, kutu/dairesel bir nesne."
        if fill_factor > 0.6 and width > depth * 2: return "Tahmin: Geniş bir yüzey (Duvar)."
        if fill_factor < 0.4: return "Tahmin: İçbükey bir yapı veya dağınık nesneler."
        return "Tahmin: Düzensiz veya karmaşık bir yapı."
    except Exception as e:
        print(f"Geometrik analiz hatası: {e}"); return "Geometrik analiz hatası."

def get_gemini_commentary(df):
    if not GOOGLE_GENAI_AVAILABLE or not google_api_key: return "Gemini servisi kullanılamıyor."
    if df is None or df.empty: return "Yorumlanacak veri yok."
    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        summary = df[['derece', 'dikey_aci', 'mesafe_cm']].describe().to_string()
        prompt = (f"Bir 3D sensör tarama verisi özeti:\n\n{summary}\n\nBu verilere dayanarak, taranan ortamın genel yapısını analiz et.")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e: return f"Gemini yorumu hatası: {e}"

# ==============================================================================
# CALLBACK FONKSİYONLARI
# ==============================================================================

@app.callback(Output('scan-status-message', 'children'),
    Input('start-scan-button', 'n_clicks'),
    [State('scan-duration-angle-input', 'value'), State('step-angle-input', 'value'),
     State('buzzer-distance-input', 'value'), State('steps-per-rev-input', 'value')],
    prevent_initial_call=True)
def handle_start_script(n_clicks, h_angle, h_step, buzzer, steps):
    if n_clicks is None: return no_update
    if os.path.exists(SENSOR_SCRIPT_PID_FILE): return dbc.Alert("Zaten bir betik çalışıyor.", color="warning")
    cmd = [sys.executable, SENSOR_SCRIPT_PATH, "--h-angle", str(h_angle), "--h-step", str(h_step), "--buzzer-distance", str(buzzer), "--steps-per-rev", str(steps)]
    try:
        subprocess.Popen(cmd, start_new_session=True)
        time.sleep(2)
        return dbc.Alert("Tarama modu başlatıldı.", color="success")
    except Exception as e:
        return dbc.Alert(f"Betik başlatma hatası: {e}", color="danger")

@app.callback(Output('scan-status-message', 'children', allow_duplicate=True), Input('stop-scan-button', 'n_clicks'), prevent_initial_call=True)
def handle_stop_script(n_clicks):
    if n_clicks is None: return no_update
    pid = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as f: pid = int(f.read().strip())
        except: pass
    if pid and is_process_running(pid):
        os.kill(pid, signal.SIGTERM); time.sleep(1)
        if is_process_running(pid): os.kill(pid, signal.SIGKILL)
        msg, color = f"Betik (PID: {pid}) durduruldu.", "info"
    else:
        msg, color = "Çalışan betik bulunamadı.", "warning"
    for f in [SENSOR_SCRIPT_PID_FILE, SENSOR_SCRIPT_LOCK_FILE]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass
    return dbc.Alert(msg, color=color)

@app.callback([Output('script-status', 'children'), Output('cpu-usage', 'value'), Output('ram-usage', 'value'), Output('cpu-usage', 'label'), Output('ram-usage', 'label')], Input('interval-component-system', 'n_intervals'))
def update_system_card(n):
    pid = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as f: pid = int(f.read().strip())
        except: pass
    status = f"Çalışıyor (PID: {pid})" if pid and is_process_running(pid) else "Çalışmıyor"
    cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
    return status, cpu, ram, f"{cpu:.1f}%", f"{ram:.1f}%"

# --- YENİ BİRLEŞİK ANA CALLBACK ---
# --- YENİ BİRLEŞİK ANA CALLBACK ---
@app.callback(
    [Output('scan-data-store', 'data'),
     Output('current-angle', 'children'), Output('current-vertical-angle', 'children'),
     Output('current-distance', 'children'), Output('current-distance-col', 'style'),
     Output('geometric-estimation-text', 'children'),
     Output('ai-commentary-text', 'children')],
    Input('interval-component-main', 'n_intervals')
)
def update_all_data_and_analysis(n):
    """
    Bu ana callback, periyodik olarak tüm veriyi çeker, anlık değerleri,
    geometrik tahmini ve Gemini yorumunu hesaplar. Diğer callback'ler bu veriyi kullanır.
    """
    scan = get_latest_scan()
    style = {'transition': 'background-color 0.5s ease'}
    default_return = [None, "--°", "--°", "-- cm", style, "Veri bekleniyor...", "Veri bekleniyor..."]
    if not scan: return default_return

    points_qs = scan.points.all().values('derece', 'dikey_aci', 'mesafe_cm', 'x_cm', 'y_cm', 'z_cm')
    if not points_qs.exists(): return default_return

    df = pd.DataFrame(list(points_qs))
    latest_point = df.iloc[-1]
    df_valid = df[df['mesafe_cm'] > 0]

    # Anlık değerler
    h_angle = f"{latest_point['derece']:.1f}°"
    v_angle = f"{latest_point['dikey_aci']:.1f}°"
    dist = f"{latest_point['mesafe_cm']:.1f} cm"
    if scan.buzzer_distance_setting and 0 < latest_point['mesafe_cm'] <= scan.buzzer_distance_setting:
        style.update({'backgroundColor': '#d9534f', 'color': 'white', 'borderRadius': '5px'})

    # Geometrik Tahmin
    estimation_text = estimate_geometric_shape(df_valid)

    # Gemini Yorumu
    gemini_commentary = get_gemini_commentary(df_valid.sample(n=min(len(df_valid), 500)) if len(df_valid) > 500 else df_valid)

    return df.to_json(orient='split'), h_angle, v_angle, dist, style, estimation_text, dcc.Markdown(gemini_commentary)

# --- GÖRSELLEŞTİRME CALLBACK'LERİ ---
@app.callback(Output('graph-3d-map', 'figure'), Input('scan-data-store', 'data'))
def update_3d_graph(json_data):
    if not json_data: return go.Figure(layout={'title': '3D Harita'})
    df = pd.read_json(json_data, orient='split')
    df_valid = df[df['mesafe_cm'] > 0]
    fig = go.Figure(layout=dict(title='3D Nokta Bulutu Haritası', margin=dict(l=0,r=0,b=0,t=40)))
    fig.add_trace(go.Scatter3d(x=df_valid['y_cm'], y=df_valid['x_cm'], z=df_valid['z_cm'], mode='markers',
                               marker=dict(size=2, color=df_valid['z_cm'], colorscale='Viridis', showscale=True, colorbar_title='Yükseklik')))
    fig.update_layout(scene=dict(xaxis_title='Y (cm)', yaxis_title='X (cm)', zaxis_title='Z (cm)', aspectmode='data'))
    return fig

@app.callback(Output('graph-2d-map', 'figure'), Input('scan-data-store', 'data'))
def update_2d_graph(json_data):
    if not json_data: return go.Figure(layout={'title': '2D Üstten Görünüm'})
    df = pd.read_json(json_data, orient='split')
    df_valid = df[df['mesafe_cm'] > 0]
    fig = go.Figure(layout=dict(title='2D Üstten Görünüm (X-Y Projeksiyonu)', yaxis_scaleanchor="x"))
    fig.add_trace(go.Scatter(x=df_valid['y_cm'], y=df_valid['x_cm'], mode='markers',
                             marker=dict(color=df_valid['dikey_aci'], colorscale='Cividis', showscale=True, colorbar_title='Dikey Açı')))
    return fig

@app.callback(Output('graph-h-angle-dist', 'figure'), Input('scan-data-store', 'data'))
def update_h_angle_graph(json_data):
    if not json_data: return go.Figure(layout={'title': 'Yatay Açı-Mesafe'})
    df = pd.read_json(json_data, orient='split')
    fig = go.Figure(layout=dict(title='Yatay Açıya Göre Mesafe'))
    fig.add_trace(go.Scatter(x=df['derece'], y=df['mesafe_cm'], mode='markers'))
    return fig

@app.callback(Output('graph-v-angle-dist', 'figure'), Input('scan-data-store', 'data'))
def update_v_angle_graph(json_data):
    if not json_data: return go.Figure(layout={'title': 'Dikey Açı-Mesafe'})
    df = pd.read_json(json_data, orient='split')
    fig = go.Figure(layout=dict(title='Dikey Açıya Göre Mesafe'))
    fig.add_trace(go.Scatter(x=df['dikey_aci'], y=df['mesafe_cm'], mode='markers'))
    return fig

@app.callback(Output('tab-content-datatable', 'children'), Input('scan-data-store', 'data'))
def render_data_table(json_data):
    if not json_data: return html.P("Görüntülenecek veri yok.")
    df = pd.read_json(json_data, orient='split')
    return dash_table.DataTable(data=df.to_dict('records'), columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                page_size=50, sort_action="native", filter_action="native", virtualization=True,
                                style_table={'height': '70vh', 'overflowY': 'auto'})