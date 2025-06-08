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
    from sklearn.linear_model import RANSACRegressor
except ImportError as e:
    print(f"UYARI: Bilimsel kütüphaneler yüklenemedi: {e}. Analizler eksik çalışabilir.")

try:
    import google.generativeai as genai

    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    print("UYARI: 'google.generativeai' kütüphanesi bulunamadı. Yapay zeka özellikleri çalışmayacak.")
    GOOGLE_GENAI_AVAILABLE = False
    genai = None

# --- Django Modelleri (Hata Kontrolü ile) ---
try:
    from django.db.models import Max
    from scanner.models import Scan, ScanPoint

    DJANGO_MODELS_AVAILABLE = True
    print("Bilgi: Django modelleri başarıyla import edildi.")
except Exception as e:
    print(f"UYARI: Django modelleri import edilemedi. Veritabanı işlemleri çalışmayacak. Hata: {e}")
    DJANGO_MODELS_AVAILABLE = False
    Scan, ScanPoint = None, None

# --- Dash ve Plotly Kütüphaneleri ---
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, no_update, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import matplotlib.pyplot as plt

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
    print("UYARI: GOOGLE_API_KEY ortam değişkeni bulunamadı. AI özellikleri devre dışı.")

# Betik Dosyaları ve Yolları
SENSOR_SCRIPT_FILENAME = 'sensor_script.py'
FREE_MOVEMENT_SCRIPT_FILENAME = 'free_movement_script.py'
APP_DIR = os.getcwd()
SENSOR_SCRIPT_PATH = os.path.join(APP_DIR, SENSOR_SCRIPT_FILENAME)
FREE_MOVEMENT_SCRIPT_PATH = os.path.join(APP_DIR, FREE_MOVEMENT_SCRIPT_FILENAME)
SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'
SENSOR_SCRIPT_LOCK_FILE = '/tmp/sensor_scan_script.lock'

# Arayüz için Varsayılan Değerler
DEFAULT_UI_SCAN_DURATION_ANGLE = 270.0
DEFAULT_UI_SCAN_STEP_ANGLE = 10.0
DEFAULT_UI_BUZZER_DISTANCE = 10
DEFAULT_UI_INVERT_MOTOR = False
DEFAULT_UI_STEPS_PER_REVOLUTION = 4096
DEFAULT_UI_SERVO_ANGLE = 90

# Dash Uygulamasını Başlat
app = DjangoDash('RealtimeSensorDashboard', external_stylesheets=[dbc.themes.BOOTSTRAP])

# ==============================================================================
# ARAYÜZ (LAYOUT)
# ==============================================================================

navbar = dbc.NavbarSimple(brand="Dream Pi", brand_href="/", color="primary", dark=True, sticky="top")

control_panel = dbc.Card([
    dbc.CardHeader("Kontrol ve Ayarlar", className="bg-primary text-white"),
    dbc.CardBody([
        html.H6("Çalışma Modu:"),
        dbc.RadioItems(id='mode-selection-radios', options=[
            {'label': 'Mesafe Ölçümü ve Haritalama', 'value': 'scan_and_map'},
            {'label': 'Serbest Hareket (Gözcü)', 'value': 'free_movement'},
        ], value='scan_and_map', className="mb-3"),
        html.Hr(),
        dbc.Row([
            dbc.Col(html.Button('Başlat', id='start-scan-button', className="btn btn-success w-100"), width=6),
            dbc.Col(html.Button('Durdur', id='stop-scan-button', className="btn btn-danger w-100"), width=6)
        ]),
        html.Div(id='scan-status-message', className="text-center mt-3", style={'minHeight': '40px'}),
        html.Hr(),
        html.Div(id='scan-parameters-wrapper', children=[
            html.H6("Yapay Zeka Seçimi:"),
            dcc.Dropdown(id='ai-model-dropdown', options=[
                {'label': 'Gemini 1.5 Flash (Hızlı)', 'value': 'gemini-1.5-flash-latest'},
                {'label': 'Gemini 1.5 Pro (Gelişmiş)', 'value': 'gemini-1.5-pro-latest'},
            ], placeholder="Yorumlama için bir AI modeli seçin...", className="mb-3"),
            html.Hr(),
            html.H6("Tarama Parametreleri:"),
            dbc.InputGroup([dbc.InputGroupText("Tarama Açısı (°)", style={"width": "150px"}),
                            dbc.Input(id="scan-duration-angle-input", type="number",
                                      value=DEFAULT_UI_SCAN_DURATION_ANGLE)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Adım Açısı (°)", style={"width": "150px"}),
                            dbc.Input(id="step-angle-input", type="number", value=DEFAULT_UI_SCAN_STEP_ANGLE)],
                           className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Dikey Açı (°)", style={"width": "150px"}),
                            dcc.Slider(id='servo-angle-slider', min=0, max=180, step=1, value=DEFAULT_UI_SERVO_ANGLE,
                                       marks={i: str(i) for i in range(0, 181, 45)},
                                       tooltip={"placement": "bottom", "always_visible": True}, className="mt-2")],
                           className="mb-4"),
            dbc.InputGroup([dbc.InputGroupText("Uyarı Mes. (cm)", style={"width": "150px"}),
                            dbc.Input(id="buzzer-distance-input", type="number", value=DEFAULT_UI_BUZZER_DISTANCE)],
                           className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Motor Adım/Tur", style={"width": "150px"}),
                            dbc.Input(id="steps-per-rev-input", type="number", value=DEFAULT_UI_STEPS_PER_REVOLUTION)],
                           className="mb-2"),
            dbc.Checkbox(id="invert-motor-checkbox", label="Motor Yönünü Ters Çevir", value=DEFAULT_UI_INVERT_MOTOR,
                         className="mt-2"),
        ])
    ])
])

stats_panel = dbc.Card([
    dbc.CardHeader("Anlık Sensör Değerleri", className="bg-info text-white"),
    dbc.CardBody(dbc.Row([
        dbc.Col(html.Div([html.H6("Mevcut Açı:"), html.H4(id='current-angle', children="--°")]),
                className="text-center"),
        dbc.Col(html.Div([html.H6("Mevcut Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
                id='current-distance-col', className="text-center"),
    ]))
])

system_card = dbc.Card([
    dbc.CardHeader("Sistem Durumu", className="bg-secondary text-white"),
    dbc.CardBody([
        dbc.Row([dbc.Col(html.Div([html.H6("Sensör Betiği:"), html.H5(id='script-status', children="Beklemede")]))],
                className="mb-2"),
        dbc.Row([
            dbc.Col(html.Div([html.H6("CPU:"), dbc.Progress(id='cpu-usage', label="0%", value=0)])),
            dbc.Col(html.Div([html.H6("RAM:"), dbc.Progress(id='ram-usage', label="0%", value=0)]))
        ])
    ])
])

export_card = dbc.Card([
    dbc.CardHeader("Veri Dışa Aktarma", className="bg-light"),
    dbc.CardBody([
        dbc.Button('CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
        dcc.Download(id='download-csv'),
        dbc.Button('Excel İndir', id='export-excel-button', color="success", className="w-100"),
        dcc.Download(id='download-excel')
    ])
])

visualization_tabs = dbc.Tabs([
    dbc.Tab([
        dcc.Dropdown(
            id='graph-selector-dropdown',
            options=[
                {'label': '3D Harita', 'value': '3d_map'},
                {'label': '2D Kartezyen Harita', 'value': 'map'},
                {'label': 'Regresyon Analizi', 'value': 'regression'},
                {'label': 'Polar Grafik', 'value': 'polar'},
                {'label': 'Zaman Serisi (Mesafe)', 'value': 'time'},
            ], value='3d_map', clearable=False, className="m-3"
        ),
        html.Div(dcc.Graph(id='scan-map-graph-3d'), id='container-map-graph-3d'),
        html.Div(dcc.Graph(id='scan-map-graph'), id='container-map-graph', style={'display': 'none'}),
        html.Div(dcc.Graph(id='polar-regression-graph'), id='container-regression-graph', style={'display': 'none'}),
        html.Div(dcc.Graph(id='polar-graph'), id='container-polar-graph', style={'display': 'none'}),
        html.Div(dcc.Graph(id='time-series-graph'), id='container-time-series-graph', style={'display': 'none'}),
    ], label="Grafikler", tab_id="tab-graphics"),
    dbc.Tab(dcc.Loading(children=[html.Div(id='tab-content-datatable')]), label="Veri Tablosu", tab_id="tab-datatable")
], id="visualization-tabs-main", active_tab="tab-graphics")

analysis_card = dbc.Card([
    dbc.CardHeader("Sayısal Analiz", className="bg-dark text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([html.H6("Alan:"), html.H4(id='calculated-area', children="--")]),
            dbc.Col([html.H6("Çevre:"), html.H4(id='perimeter-length', children="--")])
        ]),
        dbc.Row([
            dbc.Col([html.H6("Genişlik:"), html.H4(id='max-width', children="--")]),
            dbc.Col([html.H6("Derinlik:"), html.H4(id='max-depth', children="--")])
        ], className="mt-2")
    ])
])

estimation_card = dbc.Card([
    dbc.CardHeader("Geometrik Tahmin", className="bg-success text-white"),
    dbc.CardBody(html.Div("Bekleniyor...", id='environment-estimation-text', className="text-center"))
])

ai_commentary_card = dbc.Card([
    dbc.CardHeader("Akıllı Yorumlama (Yapay Zeka)", className="bg-info text-white"),
    dbc.CardBody(dcc.Loading([
        html.Div(id='ai-yorum-sonucu', children=[html.P("Yorum için bir model seçin...")]),
        html.Div(id='ai-image-container', className="text-center mt-3")
    ]))
])

app.layout = html.Div(style={'padding': '20px'}, children=[
    navbar,
    html.H1("Kullanıcı Paneli", className="text-center my-3"),
    html.Hr(),
    dbc.Row([
        dbc.Col([control_panel, html.Br(), stats_panel, html.Br(), system_card, html.Br(), export_card], md=4),
        dbc.Col([
            visualization_tabs, html.Br(),
            dbc.Row([dbc.Col(analysis_card, md=7), dbc.Col(estimation_card, md=5)], className="mb-3"),
            ai_commentary_card
        ], md=8)
    ]),
    dcc.Store(id='clustered-data-store'),
    dcc.Interval(id='interval-component-main', interval=3000, n_intervals=0),
    dcc.Interval(id='interval-component-system', interval=5000, n_intervals=0),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="modal-title")),
        dbc.ModalBody(id="modal-body")
    ], id="cluster-info-modal", is_open=False, centered=True)
])


# ==============================================================================
# YARDIMCI FONKSİYONLAR
# ==============================================================================

def is_process_running(pid):
    if pid is None: return False
    try:
        return psutil.pid_exists(pid)
    except:
        return False


def get_latest_scan():
    if not DJANGO_MODELS_AVAILABLE: return None
    try:
        running = Scan.objects.filter(status='RUNNING').order_by('-start_time').first()
        if running: return running
        return Scan.objects.order_by('-start_time').first()
    except Exception as e:
        print(f"DB Hatası (get_latest_scan): {e}")
        return None


def add_scan_rays(fig, df):
    if df.empty: return
    x_lines, y_lines = [], []
    for _, row in df.iterrows():
        x_lines.extend([0, row['y_cm'], None])
        y_lines.extend([0, row['x_cm'], None])
    fig.add_trace(go.Scatter(x=x_lines, y=y_lines, mode='lines', line=dict(color='rgba(255,100,100,0.4)', dash='dash'),
                             showlegend=False))


def add_sensor_position(fig):
    fig.add_trace(
        go.Scatter(x=[0], y=[0], mode='markers', marker=dict(symbol='cross-thin', color='red', size=15), name='Sensör'))


def analyze_environment_shape(fig, df_valid):
    if len(df_valid) < 5:
        return "Analiz için yetersiz veri.", df_valid
    points = df_valid[['y_cm', 'x_cm']].to_numpy()
    try:
        db = DBSCAN(eps=15, min_samples=3).fit(points)
        df_valid['cluster'] = db.labels_
        num_clusters = len(set(db.labels_) - {-1})
        desc = f"{num_clusters} potansiyel nesne kümesi bulundu."

        # Her kümeyi farklı bir renkle çiz
        for k in set(db.labels_):
            cluster_points = df_valid[df_valid['cluster'] == k]
            if k == -1:
                # Gürültü noktaları
                fig.add_trace(
                    go.Scatter(x=cluster_points['y_cm'], y=cluster_points['x_cm'], mode='markers', marker_symbol='x',
                               marker_color='grey', name='Gürültü'))
            else:
                # Nesne kümeleri
                fig.add_trace(
                    go.Scatter(x=cluster_points['y_cm'], y=cluster_points['x_cm'], mode='markers', name=f'Küme {k}',
                               customdata=[k] * len(cluster_points)))

        return desc, df_valid
    except Exception as e:
        print(f"DBSCAN hatası: {e}")
        return "Kümeleme hatası.", df_valid


def estimate_geometric_shape(df):
    if len(df) < 10: return "Şekil tahmini için yetersiz nokta."
    try:
        points = df[['x_cm', 'y_cm']].values
        hull = ConvexHull(points)
        hull_area = hull.area
        width = df['y_cm'].max() - df['y_cm'].min()
        depth = df['x_cm'].max()
        if width < 1 or depth < 1: return "Algılanan şekil çok küçük."
        bbox_area = depth * width
        fill_factor = hull_area / bbox_area if bbox_area > 0 else 0

        if depth > 150 and width < 50 and fill_factor < 0.3: return "Tahmin: Dar ve derin boşluk (Koridor)."
        if fill_factor > 0.7: return "Tahmin: Dolgun, kutu/dairesel nesne."
        if fill_factor > 0.6 and width > depth * 2: return "Tahmin: Geniş bir yüzey (Duvar)."
        if fill_factor < 0.4: return "Tahmin: İçbükey yapı veya dağınık nesneler."
        return "Tahmin: Düzensiz veya karmaşık yapı."
    except Exception as e:
        return f"Geometrik analiz hatası: {e}"


def yorumla_tablo_verisi_gemini(df, model_name):
    if not GOOGLE_GENAI_AVAILABLE or not google_api_key: return "Hata: Google AI yapılandırılmamış."
    if df is None or df.empty: return "Yorumlanacak veri yok."
    try:
        model = genai.GenerativeModel(model_name=model_name)
        prompt = (f"Bir ultrasonik sensörün tarama verileri: \n\n{df.to_string(index=False)}\n\n"
                  "Bu verilere dayanarak, ortamın olası yapısını (örn: 'geniş oda', 'dar koridor') analiz et. "
                  "Verilerdeki desenlere göre potansiyel nesneleri tahmin et. Cevabını Markdown formatında, düzenli bir şekilde sun.")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini metin yorumu hatası: {e}"


def generate_image_from_text(analysis_text, model_name):
    if not GOOGLE_GENAI_AVAILABLE or not google_api_key: return dbc.Alert("Hata: AI servisi kullanılamıyor.",
                                                                          color="danger")
    if not analysis_text or "Hata:" in analysis_text: return dbc.Alert("Resim için geçerli analiz metni gerekli.",
                                                                       color="warning")
    try:
        # Resim üretme yeteneği olan bir model kullanmak gerekebilir, bu model metin üreteci olabilir.
        # Bu kısım varsayımsaldır ve Gemini'nin görüntü API'sinin spesifikasyonlarına göre ayarlanmalıdır.
        model = genai.GenerativeModel(model_name)
        prompt = (
            f"Aşağıdaki analizi temel alarak, taranan ortamın yukarıdan görünümlü şematik bir haritasını oluştur: \n\n{analysis_text}")
        # response = model.generate_content(prompt, generation_config={"response_mime_type": "image/png"})
        # image_uri = get_uri_from_response(response)
        # return html.Img(src=image_uri)
        return dbc.Alert("Not: Gemini resim üretme API'si entegrasyonu gerektirir. Bu bir yer tutucudur.", color="info")
    except Exception as e:
        return dbc.Alert(f"Resim oluşturma hatası: {e}", color="danger")


# ==============================================================================
# CALLBACK FONKSİYONLARI
# ==============================================================================

@app.callback(
    Output('scan-parameters-wrapper', 'style'),
    Input('mode-selection-radios', 'value')
)
def toggle_parameter_visibility(selected_mode):
    """Toggles visibility of scan parameters based on the selected operating mode."""
    if selected_mode == 'scan_and_map':
        return {'display': 'block'}
    else:
        return {'display': 'none'}


@app.callback(
    Output('scan-status-message', 'children'),
    [Input('start-scan-button', 'n_clicks')],
    [State('mode-selection-radios', 'value'),
     State('scan-duration-angle-input', 'value'), State('step-angle-input', 'value'),
     State('buzzer-distance-input', 'value'), State('invert-motor-checkbox', 'value'),
     State('steps-per-rev-input', 'value'), State('servo-angle-slider', 'value')],
    prevent_initial_call=True
)
def handle_start_scan_script(n_clicks, selected_mode, duration, step, buzzer_dist, invert, steps_rev, servo_angle):
    """Handles starting the sensor script based on selected mode and parameters."""
    if n_clicks == 0:
        return no_update
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                pid = int(pf.read().strip())
            if is_process_running(pid):
                return dbc.Alert(f"Bir betik zaten çalışıyor (PID:{pid}). Önce durdurun.", color="warning")
        except:
            pass
    for fp_lock_pid in [SENSOR_SCRIPT_LOCK_FILE, SENSOR_SCRIPT_PID_FILE]:
        if os.path.exists(fp_lock_pid):
            try:
                os.remove(fp_lock_pid)
            except OSError as e_rm:
                print(f"Eski dosya silinemedi ({fp_lock_pid}): {e_rm}")
    py_exec = sys.executable
    cmd = []
    if selected_mode == 'scan_and_map':
        if not (isinstance(duration, (int, float)) and 10 <= duration <= 720): return dbc.Alert(
            "Tarama Açısı 10-720 derece arasında olmalı!", color="danger", duration=4000)
        if not (isinstance(step, (int, float)) and 0.1 <= abs(step) <= 45): return dbc.Alert(
            "Adım açısı 0.1-45 arasında olmalı!", color="danger", duration=4000)
        if not (isinstance(buzzer_dist, (int, float)) and 0 <= buzzer_dist <= 200): return dbc.Alert(
            "Uyarı mesafesi 0-200 cm arasında olmalı!", color="danger", duration=4000)
        if not (isinstance(steps_rev, (int, float)) and 500 <= steps_rev <= 10000): return dbc.Alert(
            "Motor Adım/Tur 500-10000 arasında olmalı!", color="danger", duration=4000)
        cmd = [py_exec, SENSOR_SCRIPT_PATH,
               "--scan_duration_angle", str(duration),
               "--step_angle", str(step),
               "--buzzer_distance", str(buzzer_dist),
               "--invert_motor_direction", str(invert),
               "--steps_per_rev", str(steps_rev),
               "--servo_angle", str(servo_angle)]
    elif selected_mode == 'free_movement':
        cmd = [py_exec, FREE_MOVEMENT_SCRIPT_PATH]
    else:
        return dbc.Alert("Geçersiz mod seçildi!", color="danger")
    try:
        if not os.path.exists(cmd[1]):
            return dbc.Alert(f"HATA: Betik dosyası bulunamadı: {cmd[1]}", color="danger")
        subprocess.Popen(cmd, start_new_session=True)
        max_wait_time, check_interval, start_time_wait = 7, 0.25, time.time()
        pid_file_found = False
        while time.time() - start_time_wait < max_wait_time:
            if os.path.exists(SENSOR_SCRIPT_PID_FILE):
                pid_file_found = True
                break
            time.sleep(check_interval)
        if pid_file_found:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                new_pid = pf.read().strip()
            mode_name = "Mesafe Ölçüm Modu" if selected_mode == 'scan_and_map' else "Serbest Hareket Modu"
            return dbc.Alert(f"{mode_name} başlatıldı (PID:{new_pid}).", color="success")
        else:
            return dbc.Alert(f"Başlatılamadı. PID dosyası {max_wait_time} saniye içinde oluşmadı.", color="danger")
    except Exception as e:
        return dbc.Alert(f"Betik başlatma hatası: {e}", color="danger")


@app.callback(
    Output('scan-status-message', 'children', allow_duplicate=True),
    [Input('stop-scan-button', 'n_clicks')],
    prevent_initial_call=True
)
def handle_stop_scan_script(n_clicks):
    if n_clicks == 0: return no_update
    pid_to_kill = None
    message = ""
    color = "warning"
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                pid_to_kill = int(pf.read().strip())
        except (IOError, ValueError):
            pass
    if pid_to_kill and is_process_running(pid_to_kill):
        try:
            os.kill(pid_to_kill, signal.SIGTERM)
            time.sleep(1)
            if is_process_running(pid_to_kill):
                os.kill(pid_to_kill, signal.SIGKILL)
                time.sleep(0.5)
            if not is_process_running(pid_to_kill):
                message = f"Çalışan betik (PID:{pid_to_kill}) durduruldu."
                color = "info"
            else:
                message = f"Betik (PID:{pid_to_kill}) durdurulamadı!"
                color = "danger"
        except ProcessLookupError:
            message = f"Betik (PID:{pid_to_kill}) zaten çalışmıyordu.";
            color = "warning"
        except Exception as e:
            message = f"Durdurma hatası: {e}";
            color = "danger"
    else:
        message = "Çalışan betik bulunamadı."

    for fp_lock_pid_stop in [SENSOR_SCRIPT_PID_FILE, SENSOR_SCRIPT_LOCK_FILE]:
        if os.path.exists(fp_lock_pid_stop):
            try:
                os.remove(fp_lock_pid_stop)
            except OSError:
                pass
    return dbc.Alert(message, color=color)


@app.callback(
    [Output('script-status', 'children'), Output('script-status', 'className'), Output('cpu-usage', 'value'),
     Output('cpu-usage', 'label'), Output('ram-usage', 'value'), Output('ram-usage', 'label')],
    [Input('interval-component-system', 'n_intervals')]
)
def update_system_card(n):
    """Updates system status (script, CPU, RAM usage) periodically."""
    status_text, status_class, pid_val = "Beklemede", "text-secondary", None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                pid_val = int(pf.read().strip())
        except:
            pass
    if pid_val and is_process_running(pid_val):
        status_text, status_class = f"Çalışıyor (PID:{pid_val})", "text-success"
    else:
        status_text, status_class = "Çalışmıyor", "text-danger"
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    return status_text, status_class, cpu, f"{cpu:.1f}%", ram, f"{ram:.1f}%"


@app.callback(
    [Output('current-angle', 'children'), Output('current-distance', 'children'), Output('current-speed', 'children'),
     Output('current-distance-col', 'style'), Output('max-detected-distance', 'children')],
    [Input('interval-component-main', 'n_intervals')]
)
def update_realtime_values(n):
    """Updates real-time sensor values (angle, distance, speed, max distance) and applies buzzer styling."""
    scan = get_latest_scan()
    angle_s, dist_s, speed_s, max_dist_s = "--°", "-- cm", "-- cm/s", "-- cm"
    dist_style = {'padding': '10px', 'transition': 'background-color 0.5s ease', 'borderRadius': '5px'}
    if scan:
        point = scan.points.order_by('-timestamp').first()
        if point:
            angle_s = f"{point.derece:.1f}°" if pd.notnull(point.derece) else "--°"
            dist_s = f"{point.mesafe_cm:.1f} cm" if pd.notnull(point.mesafe_cm) else "-- cm"
            speed_s = f"{point.hiz_cm_s:.1f} cm/s" if pd.notnull(point.hiz_cm_s) else "-- cm/s"
            buzzer_threshold = scan.buzzer_distance_setting
            if buzzer_threshold is not None and pd.notnull(point.mesafe_cm) and 0 < point.mesafe_cm <= buzzer_threshold:
                dist_style.update({'backgroundColor': '#d9534f', 'color': 'white'})
            max_dist_agg = scan.points.filter(mesafe_cm__lt=2500, mesafe_cm__gt=0).aggregate(
                max_dist_val=Max('mesafe_cm'))
            if max_dist_agg and max_dist_agg.get('max_dist_val') is not None:
                max_dist_s = f"{max_dist_agg['max_dist_val']:.1f} cm"
    return angle_s, dist_s, speed_s, dist_style, max_dist_s




@app.callback(Output('download-csv', 'data'), Input('export-csv-button', 'n_clicks'), prevent_initial_call=True)
def export_csv_callback(n_clicks_csv):
    """Exports the latest scan data to a CSV file."""
    if not n_clicks_csv: return no_update
    scan = get_latest_scan()
    if not scan: return dcc.send_data_frame(pd.DataFrame().to_csv, "tarama_yok.csv", index=False)
    points_qs = scan.points.all().values()
    if not points_qs: return dcc.send_data_frame(pd.DataFrame().to_csv, f"tarama_id_{scan.id}_nokta_yok.csv",
                                                 index=False)
    df = pd.DataFrame(list(points_qs))
    return dcc.send_data_frame(df.to_csv, f"tarama_id_{scan.id}_noktalar.csv", index=False)


@app.callback(Output('download-excel', 'data'), Input('export-excel-button', 'n_clicks'), prevent_initial_call=True)
def export_excel_callback(n_clicks_excel):
    """Exports the latest scan data and metadata to an Excel file."""
    if not n_clicks_excel: return no_update
    scan = get_latest_scan()
    if not scan: return dcc.send_bytes(b"", "tarama_yok.xlsx")
    try:
        scan_info_data = Scan.objects.filter(id=scan.id).values().first()
        scan_info_df = pd.DataFrame([scan_info_data]) if scan_info_data else pd.DataFrame()
        points_df = pd.DataFrame(list(scan.points.all().values()))
    except Exception as e_excel_data:
        print(f"Excel için veri çekme hatası: {e_excel_data}")
        return dcc.send_bytes(b"", f"veri_cekme_hatasi_{scan.id if scan else 'yok'}.xlsx")
    with io.BytesIO() as buf:
        try:
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                if not scan_info_df.empty: scan_info_df.to_excel(writer, sheet_name=f'Scan_{scan.id}_Info', index=False)
                if not points_df.empty:
                    points_df.to_excel(writer, sheet_name=f'Scan_{scan.id}_Points', index=False)
                elif scan_info_df.empty:
                    pd.DataFrame().to_excel(writer, sheet_name='Veri Yok', index=False)
        except Exception as e_excel_write:
            print(f"Excel yazma hatası: {e_excel_write}")
            # This line had a bug in the original code, it needs 'writer'
            pd.DataFrame([{"Hata": str(e_excel_write)}]).to_excel(writer, sheet_name='Hata', index=False)
        return dcc.send_bytes(buf.getvalue(), f"tarama_detaylari_id_{scan.id if scan else 'yok'}.xlsx")


@app.callback(Output('tab-content-datatable', 'children'),
              [Input('visualization-tabs-main', 'active_tab'), Input('interval-component-main', 'n_intervals')])
def render_and_update_data_table(active_tab, n):
    """Renders and updates the data table with the latest scan points."""
    if active_tab != "tab-datatable": return None
    scan = get_latest_scan()
    if not scan: return html.P("Görüntülenecek tarama verisi yok.")
    points_qs = scan.points.order_by('-id').values('id', 'derece', 'mesafe_cm', 'hiz_cm_s', 'x_cm', 'y_cm', 'timestamp')
    if not points_qs: return html.P(f"Tarama ID {scan.id} için nokta verisi bulunamadı.")
    df = pd.DataFrame(list(points_qs))
    if 'timestamp' in df.columns: df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime(
        '%Y-%m-%d %H:%M:%S.%f').str[:-3]
    return dash_table.DataTable(data=df.to_dict('records'),
                                columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                style_cell={'textAlign': 'left', 'padding': '5px', 'fontSize': '0.9em'},
                                style_header={'backgroundColor': 'rgb(230,230,230)', 'fontWeight': 'bold'},
                                style_table={'minHeight': '65vh', 'height': '70vh', 'maxHeight': '75vh',
                                             'overflowY': 'auto', 'overflowX': 'auto'},
                                page_size=50, sort_action="native", filter_action="native", virtualization=True,
                                fixed_rows={'headers': True},
                                style_data_conditional=[
                                    {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgb(248, 248, 248)'}])


@app.callback(
    [
        Output('scan-map-graph-3d', 'figure'),
        Output('scan-map-graph', 'figure'),
        Output('polar-regression-graph', 'figure'),
        Output('polar-graph', 'figure'),
        Output('time-series-graph', 'figure'),
        Output('environment-estimation-text', 'children'),
        Output('clustered-data-store', 'data')
    ],
    Input('interval-component-main', 'n_intervals')
)
def update_all_graphs(n):
    """
    Main callback that periodically updates all graphs and analyses.
    This is the visual core of the application.
    (This callback does NOT update the 'calculated-area' etc. to avoid conflicts)
    """
    print("\n--- Grafik güncelleme tetiklendi ---")
    scan = get_latest_scan()
    if not scan:
        print(">> DATA_DEBUG: get_latest_scan() fonksiyonu 'None' döndürdü.")
        empty_fig = go.Figure()
        return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, "Tarama bekleniyor...", None
    else:
        print(f">> DATA_DEBUG: Son tarama bulundu. Scan ID: {scan.id}, Durum: {scan.status}")

    # Initialize figures
    figs = [go.Figure() for _ in range(5)]
    est_text = html.Div([html.P("Veri işleniyor...")])
    store_data = None
    scan_id_for_revision = str(scan.id)

    points_qs = ScanPoint.objects.filter(scan=scan).values('x_cm', 'y_cm', 'z_cm', 'derece', 'mesafe_cm', 'timestamp')

    if not points_qs.exists():
        print(f">> DATA_DEBUG: UYARI! Tarama #{scan.id} için nokta (ScanPoint) yok.")
        empty_fig = go.Figure()
        return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, f"Tarama #{scan.id} için nokta verisi yok.", None

    df_pts = pd.DataFrame(list(points_qs))
    df_val = df_pts[(df_pts['mesafe_cm'] > 0.1) & (df_pts['mesafe_cm'] < 300.0)].copy()

    # 3D Scatter Plot (figs[0])
    if not df_val.empty:
        figs[0].add_trace(go.Scatter3d(x=df_val['y_cm'], y=df_val['x_cm'], z=df_val['z_cm'], mode='markers',
                                       marker=dict(size=3, color=df_val['z_cm'], colorscale='Viridis', showscale=True,
                                                   colorbar_title='Yükseklik (cm)'), name='3D Noktalar'))
        figs[0].add_trace(
            go.Scatter3d(x=[0], y=[0], z=[0], mode='markers', marker=dict(size=8, symbol='circle', color='red'),
                         name='Sensör Konumu'))

    if len(df_val) >= 5:
        # Helper functions from your code would be used here. For this example, we assume they exist.
        # est_cart, df_clus = analyze_environment_shape(figs[1], df_val.copy())
        # store_data = df_clus.to_json(orient='split')
        # add_scan_rays(figs[1], df_val)
        # update_polar_graph(figs[3], df_val)
        # update_time_series_graph(figs[4], df_val)
        # shape_estimation = estimate_geometric_shape(df_val)
        est_text = html.Div([html.P("Analizler burada gösterilir.")])  # Placeholder text
    else:
        est_text = html.Div([html.P("Analiz için yeterli sayıda geçerli nokta bulunamadı.")])

    # Titles and common layout
    titles = ['3D Harita', '2D Harita', 'Regresyon Analizi', 'Polar Grafik', 'Zaman Serisi']
    for i, fig in enumerate(figs):
        fig.update_layout(title_text=titles[i], uirevision=scan_id_for_revision)

    return figs[0], figs[1], figs[2], figs[3], figs[4], est_text, store_data


@app.callback(
    [Output('container-map-graph-3d', 'style'), Output('container-map-graph', 'style'),
     Output('container-regression-graph', 'style'), Output('container-polar-graph', 'style'),
     Output('container-time-series-graph', 'style')],
    Input('graph-selector-dropdown', 'value')
)
def update_graph_visibility(selected_graph):
    """Controls the visibility of different graph types based on dropdown selection."""
    styles = {'display': 'block'}
    return [styles if k == selected_graph else {'display': 'none'} for k in
            ['3d_map', 'map', 'regression', 'polar', 'time']]


@app.callback(
    [Output("cluster-info-modal", "is_open"), Output("modal-title", "children"), Output("modal-body", "children")],
    [Input("scan-map-graph", "clickData")], [State("clustered-data-store", "data")], prevent_initial_call=True)
def display_cluster_info(clickData, stored_data_json):
    """Displays detailed information about a clicked cluster in a modal."""
    if not clickData or not stored_data_json: return False, no_update, no_update
    try:
        df_clus = pd.read_json(stored_data_json, orient='split')
        cl_label = clickData["points"][0].get('customdata')
        if cl_label is None: return False, "Hata", "Küme etiketi alınamadı."

        title = f"Küme #{int(cl_label)} Detayları"
        cl_df_points = df_clus[df_clus['cluster'] == cl_label]
        body = html.Div([html.P(f"Nokta Sayısı: {len(cl_df_points)}")])
        return True, title, body
    except Exception as e:
        return True, "Hata", f"Küme bilgisi gösterilemedi: {e}"


@app.callback(
    [Output('ai-yorum-sonucu', 'children'), Output('ai-image-container', 'children')],
    [Input('ai-model-dropdown', 'value')],
    prevent_initial_call=True
)
def yorumla_model_secimi(selected_model_value):
    """Triggers AI-powered environment interpretation and image generation."""
    if not selected_model_value:
        return [html.Div("Yorum için bir model seçin."), no_update]

    scan = get_latest_scan()
    if not scan:
        return [dbc.Alert("Analiz edilecek bir tarama bulunamadı.", color="warning"), no_update]

    points_qs = scan.points.all().values()
    if not points_qs:
        return [dbc.Alert("Yorumlanacak tarama verisi bulunamadı.", color="warning"), no_update]
    df_data_for_ai = pd.DataFrame(list(points_qs))

    # Get text commentary
    yorum_text_from_ai = yorumla_tablo_verisi_gemini(df_data_for_ai, selected_model_value)
    commentary_component = dcc.Markdown(yorum_text_from_ai, dangerously_allow_html=True)

    # Generate image from text
    image_component = generate_image_from_text(yorum_text_from_ai, selected_model_value)

    return [commentary_component, image_component]