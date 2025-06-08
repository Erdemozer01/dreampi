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
        dbc.Col(html.Div([html.H6("Anlık Hız:"), html.H4(id='current-speed', children="-- cm/s")]),
                className="text-center"),
        dbc.Col(html.Div([html.H6("Max. Algılanan Mesafe:"), html.H4(id='max-detected-distance', children="-- cm")]),
                className="text-center")
    ]))
])

system_card = dbc.Card([
    dbc.CardHeader("Sistem Durumu", className="bg-secondary text-white"),
    dbc.CardBody([
        dbc.Row([dbc.Col(html.Div([html.H6("Sensör Betiği:"), html.H5(id='script-status', children="Beklemede")]))],
                className="mb-2"),
        dbc.Row([
            dbc.Col(html.Div([html.H6("Pi CPU Kullanımı:"), dbc.Progress(id='cpu-usage', label="0%", value=0)])),
            dbc.Col(html.Div([html.H6("Pi RAM Kullanımı:"), dbc.Progress(id='ram-usage', label="0%", value=0)]))
        ])
    ])
])

export_card = dbc.Card([
    dbc.CardHeader("Veri Dışa Aktarma", className="bg-light"),
    dbc.CardBody([
        dbc.Button('En Son Taramayı CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
        dcc.Download(id='download-csv'),
        dbc.Button('En Son Taramayı Excel İndir', id='export-excel-button', color="success", className="w-100"),
        dcc.Download(id='download-excel')
    ])
])

visualization_tabs = dbc.Tabs([
    dbc.Tab([
        dcc.Dropdown(id='graph-selector-dropdown', options=[
            {'label': '3D Harita', 'value': '3d_map'},
            {'label': '2D Kartezyen Harita', 'value': 'map'},
            {'label': 'Regresyon Analizi', 'value': 'regression'},
            {'label': 'Polar Grafik', 'value': 'polar'},
            {'label': 'Zaman Serisi (Mesafe)', 'value': 'time'},
        ], value='3d_map', clearable=False, className="m-3"),
        html.Div(dcc.Graph(id='scan-map-graph-3d'), id='container-map-graph-3d'),
        html.Div(dcc.Graph(id='scan-map-graph'), id='container-map-graph', style={'display': 'none'}),
        html.Div(dcc.Graph(id='polar-regression-graph'), id='container-regression-graph', style={'display': 'none'}),
        html.Div(dcc.Graph(id='polar-graph'), id='container-polar-graph', style={'display': 'none'}),
        html.Div(dcc.Graph(id='time-series-graph'), id='container-time-series-graph', style={'display': 'none'}),
    ], label="Grafikler", tab_id="tab-graphics"),
    dbc.Tab(dcc.Loading(children=[html.Div(id='tab-content-datatable')]), label="Veri Tablosu", tab_id="tab-datatable")
], id="visualization-tabs-main", active_tab="tab-graphics")

analysis_card = dbc.Card([
    dbc.CardHeader("Tarama Analizi (Sayısal)", className="bg-dark text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([html.H6("Hesaplanan Alan:"), html.H4(id='calculated-area', children="--")]),
            dbc.Col([html.H6("Çevre Uzunluğu:"), html.H4(id='perimeter-length', children="--")])
        ]),
        dbc.Row([
            dbc.Col([html.H6("Max Genişlik:"), html.H4(id='max-width', children="--")]),
            dbc.Col([html.H6("Max Derinlik:"), html.H4(id='max-depth', children="--")])
        ], className="mt-2")
    ])
])

estimation_card = dbc.Card([
    dbc.CardHeader("Akıllı Ortam Analizi", className="bg-success text-white"),
    dbc.CardBody(html.Div("Tahmin: Bekleniyor...", id='environment-estimation-text', className="text-center"))
])

ai_commentary_card = dbc.Card([
    dbc.CardHeader("Akıllı Yorumlama (Yapay Zeka)", className="bg-info text-white"),
    dbc.CardBody(dcc.Loading(children=[
        html.Div(id='ai-yorum-sonucu', children=[html.P("Yorum almak için bir model seçin...")]),
        html.Div(id='ai-image-container', className="text-center mt-2")
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
            dbc.Row([dbc.Col(analysis_card, md=8), dbc.Col(estimation_card, md=4)], className="mb-3"),
            dbc.Row([dbc.Col(ai_commentary_card, md=12)], className="mt-3")
        ], md=8)
    ]),
    dcc.Store(id='clustered-data-store'),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="modal-title")),
        dbc.ModalBody(id="modal-body")
    ], id="cluster-info-modal", is_open=False, centered=True),
    dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0),
    dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0),
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
    fig.add_trace(go.Scatter(x=[0], y=[0], mode='markers', marker=dict(symbol='cross-thin-open', color='red', size=15),
                             name='Sensör'))


def analyze_environment_shape(fig, df_valid):
    if len(df_valid) < 5: return "Analiz için yetersiz veri.", df_valid
    points = df_valid[['y_cm', 'x_cm']].to_numpy()
    try:
        db = DBSCAN(eps=15, min_samples=3).fit(points)
        df_valid['cluster'] = db.labels_
        num_clusters = len(set(db.labels_) - {-1})
        desc = f"{num_clusters} potansiyel nesne kümesi bulundu."
        for k in set(db.labels_):
            cluster_points = df_valid[df_valid['cluster'] == k]
            fig.add_trace(go.Scatter(x=cluster_points['y_cm'], y=cluster_points['x_cm'], mode='markers',
                                     name=f'Küme {k}' if k != -1 else 'Gürültü', customdata=[k] * len(cluster_points),
                                     marker_symbol='x' if k == -1 else 'circle'))
        return desc, df_valid
    except Exception as e:
        print(f"DBSCAN hatası: {e}");
        return "Kümeleme hatası.", df_valid


def estimate_geometric_shape(df):
    if df is None or len(df) < 10: return "Şekil tahmini için yetersiz nokta."
    try:
        points = df[['x_cm', 'y_cm']].values
        hull = ConvexHull(points)
        width = df['y_cm'].max() - df['y_cm'].min()
        depth = df['x_cm'].max()
        if width < 1 or depth < 1: return "Algılanan şekil çok küçük."
        fill_factor = hull.volume / (width * depth) if (width * depth) > 0 else 0
        if depth > 150 and width < 50 and fill_factor < 0.3: return "Tahmin: Dar ve derin bir boşluk (Koridor)."
        if fill_factor > 0.7: return "Tahmin: Dolgun, kutu/dairesel bir nesne."
        if fill_factor > 0.6 and width > depth * 2: return "Tahmin: Geniş bir yüzey (Duvar)."
        if fill_factor < 0.4: return "Tahmin: İçbükey bir yapı veya dağınık nesneler."
        return "Tahmin: Düzensiz veya karmaşık bir yapı."
    except Exception as e:
        print(f"Geometrik analiz hatası: {e}");
        return "Geometrik analiz hatası."


def yorumla_tablo_verisi_gemini(df, model_name):
    if not GOOGLE_GENAI_AVAILABLE or not google_api_key: return "Hata: Google AI yapılandırılmamış."
    if df is None or df.empty: return "Yorumlanacak veri yok."
    try:
        model = genai.GenerativeModel(model_name=model_name)
        prompt = (f"Bir sensör tarama verisi: \n\n{df.to_string(index=False)}\n\n"
                  "Bu verilere dayanarak, ortamın olası yapısını (örn: 'geniş oda', 'dar koridor') analiz et. "
                  "Verilerdeki desenlere göre potansiyel nesneleri tahmin et. Cevabını Markdown formatında, düzenli bir şekilde sun.")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini metin yorumu hatası: {e}"


def generate_image_from_text(analysis_text, model_name):
    return dbc.Alert("Not: Gemini resim üretme API'si henüz tam olarak entegre edilmemiştir.", color="info")


# ==============================================================================
# CALLBACK FONKSİYONLARI
# ==============================================================================

@app.callback(Output('scan-parameters-wrapper', 'style'), Input('mode-selection-radios', 'value'))
def toggle_parameter_visibility(selected_mode):
    return {'display': 'block'} if selected_mode == 'scan_and_map' else {'display': 'none'}


@app.callback(Output('scan-status-message', 'children'),
              Input('start-scan-button', 'n_clicks'),
              [State('mode-selection-radios', 'value'), State('scan-duration-angle-input', 'value'),
               State('step-angle-input', 'value'),
               State('buzzer-distance-input', 'value'), State('invert-motor-checkbox', 'value'),
               State('steps-per-rev-input', 'value'), State('servo-angle-slider', 'value')],
              prevent_initial_call=True)
def handle_start_scan_script(n_clicks, mode, duration, step, buzzer, invert, steps, servo):
    if n_clicks is None: return no_update
    if os.path.exists(SENSOR_SCRIPT_PID_FILE): return dbc.Alert("Zaten bir betik çalışıyor. Önce durdurun.",
                                                                color="warning")
    cmd_map = {
        'scan_and_map': [sys.executable, SENSOR_SCRIPT_PATH, "--scan_duration_angle", str(duration), "--step_angle",
                         str(step), "--buzzer_distance", str(buzzer), "--invert_motor_direction", str(invert),
                         "--steps_per_rev", str(steps), "--servo_angle", str(servo)],
        'free_movement': [sys.executable, FREE_MOVEMENT_SCRIPT_PATH]
    }
    cmd = cmd_map.get(mode)
    if not cmd: return dbc.Alert("Geçersiz mod.", color="danger")
    try:
        subprocess.Popen(cmd, start_new_session=True)
        time.sleep(2)
        return dbc.Alert(f"{mode.replace('_', ' ').title()} modu başlatıldı.", color="success")
    except Exception as e:
        return dbc.Alert(f"Betik başlatma hatası: {e}", color="danger")


@app.callback(Output('scan-status-message', 'children', allow_duplicate=True), Input('stop-scan-button', 'n_clicks'),
              prevent_initial_call=True)
def handle_stop_scan_script(n_clicks):
    if n_clicks is None: return no_update
    pid = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
        except (IOError, ValueError):
            pass
    if pid and is_process_running(pid):
        os.kill(pid, signal.SIGTERM);
        time.sleep(1)
        if is_process_running(pid): os.kill(pid, signal.SIGKILL)
        msg, color = f"Betik (PID: {pid}) durduruldu.", "info"
    else:
        msg, color = "Çalışan betik bulunamadı.", "warning"
    for f in [SENSOR_SCRIPT_PID_FILE, SENSOR_SCRIPT_LOCK_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass
    return dbc.Alert(msg, color=color)


@app.callback([Output('script-status', 'children'), Output('cpu-usage', 'value'), Output('ram-usage', 'value'),
               Output('cpu-usage', 'label'), Output('ram-usage', 'label')],
              Input('interval-component-system', 'n_intervals'))
def update_system_card(n):
    pid = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
        except:
            pass
    status = f"Çalışıyor (PID: {pid})" if pid and is_process_running(pid) else "Çalışmıyor"
    cpu = psutil.cpu_percent();
    ram = psutil.virtual_memory().percent
    return status, cpu, ram, f"{cpu:.1f}%", f"{ram:.1f}%"


@app.callback(
    [Output('current-angle', 'children'), Output('current-distance', 'children'), Output('current-speed', 'children'),
     Output('max-detected-distance', 'children'), Output('current-distance-col', 'style')],
    Input('interval-component-main', 'n_intervals'))
def update_realtime_values(n):
    scan = get_latest_scan()
    style = {'transition': 'background-color 0.5s ease'}
    if not scan: return "--°", "-- cm", "-- cm/s", "-- cm", style
    point = scan.points.order_by('-timestamp').first()
    if not point: return "--°", "-- cm", "-- cm/s", "-- cm", style
    angle = f"{point.derece:.1f}°" if pd.notnull(point.derece) else "--"
    dist = f"{point.mesafe_cm:.1f} cm" if pd.notnull(point.mesafe_cm) else "--"
    speed = f"{point.hiz_cm_s:.1f} cm/s" if hasattr(point, 'hiz_cm_s') and pd.notnull(point.hiz_cm_s) else "--"
    max_dist_agg = scan.points.aggregate(Max('mesafe_cm'))
    max_dist = f"{max_dist_agg['mesafe_cm__max']:.1f} cm" if max_dist_agg['mesafe_cm__max'] else "--"
    if scan.buzzer_distance_setting and pd.notnull(
            point.mesafe_cm) and 0 < point.mesafe_cm <= scan.buzzer_distance_setting:
        style.update({'backgroundColor': '#d9534f', 'color': 'white', 'borderRadius': '5px'})
    return angle, dist, speed, max_dist, style


# BİLGİ: 'update_analysis_panel' isimli çakışan callback, 'KeyError' hatasını çözmek için bu bölümden kaldırılmıştır.
# Görevini artık aşağıdaki 'update_all_outputs' callback'i üstlenmektedir.

@app.callback(Output('download-csv', 'data'), Input('export-csv-button', 'n_clicks'), prevent_initial_call=True)
def export_csv_callback(n_clicks):
    scan = get_latest_scan();
    if not scan: return dcc.send_data_frame(pd.DataFrame().to_csv, "tarama_yok.csv", index=False)
    df = pd.DataFrame(list(scan.points.all().values()))
    return dcc.send_data_frame(df.to_csv, f"tarama_{scan.id}.csv", index=False)


@app.callback(Output('download-excel', 'data'), Input('export-excel-button', 'n_clicks'), prevent_initial_call=True)
def export_excel_callback(n_clicks):
    scan = get_latest_scan()
    if not scan: return dcc.send_bytes(b"", "tarama_yok.xlsx")
    with io.BytesIO() as buffer:
        pd.DataFrame(list(scan.points.all().values())).to_excel(buffer, sheet_name='ScanPoints', index=False)
        return dcc.send_bytes(buffer.getvalue(), f"tarama_{scan.id}.xlsx")


@app.callback(Output('tab-content-datatable', 'children'),
              [Input('visualization-tabs-main', 'active_tab'), Input('interval-component-main', 'n_intervals')])
def render_and_update_data_table(active_tab, n):
    if active_tab != "tab-datatable": return no_update
    scan = get_latest_scan()
    if not scan: return html.P("Görüntülenecek veri yok.")
    points_qs = scan.points.order_by('-id').values()
    if not points_qs.exists(): return html.P("Nokta verisi bulunamadı.")
    df = pd.DataFrame(list(points_qs))
    if 'timestamp' in df.columns: df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
    return dash_table.DataTable(data=df.to_dict('records'),
                                columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                page_size=50, sort_action="native", filter_action="native", virtualization=True)


@app.callback(
    [Output('scan-map-graph-3d', 'figure'), Output('scan-map-graph', 'figure'),
     Output('polar-regression-graph', 'figure'),
     Output('polar-graph', 'figure'), Output('time-series-graph', 'figure'),
     Output('environment-estimation-text', 'children'),
     Output('clustered-data-store', 'data'), Output('calculated-area', 'children'),
     Output('perimeter-length', 'children'),
     Output('max-width', 'children'), Output('max-depth', 'children')],
    Input('interval-component-main', 'n_intervals'))
def update_all_outputs(n):
    scan = get_latest_scan()
    empty_fig = go.Figure(
        layout={'title': 'Veri Bekleniyor...', 'xaxis': dict(visible=False), 'yaxis': dict(visible=False)})
    default_return = [empty_fig] * 5 + ["Bekleniyor..."] + [None] + ["--"] * 4
    if not scan: return default_return

    points = scan.points.all().values('x_cm', 'y_cm', 'z_cm', 'derece', 'mesafe_cm', 'timestamp')
    if not points.exists(): return default_return

    df = pd.DataFrame(list(points));
    df_valid = df[df['mesafe_cm'] > 0].copy()
    if df_valid.empty: return default_return

    figs = [go.Figure(), go.Figure(), go.Figure(), go.Figure(), go.Figure()]

    # 3D Harita
    figs[0].add_trace(go.Scatter3d(x=df_valid['y_cm'], y=df_valid['x_cm'], z=df_valid['z_cm'], mode='markers',
                                   marker=dict(size=2, color=df_valid['z_cm'], colorscale='Viridis')))
    figs[0].add_trace(
        go.Scatter3d(x=[0], y=[0], z=[0], mode='markers', marker=dict(symbol='diamond', color='red', size=5),
                     name='Sensör'))

    # 2D Harita ve Analizler
    est_text_cluster, df_clustered = analyze_environment_shape(figs[1], df_valid)
    add_scan_rays(figs[1], df_valid)
    add_sensor_position(figs[1])

    # Diğer grafikler
    figs[2].add_trace(go.Scatter(x=df_valid['derece'], y=df_valid['mesafe_cm'], mode='markers', name='Data'))
    figs[3].add_trace(go.Scatterpolar(r=df_valid['mesafe_cm'], theta=df_valid['derece'], mode='markers', name='Data'))
    figs[4].add_trace(
        go.Scatter(x=pd.to_datetime(df_valid['timestamp']), y=df_valid['mesafe_cm'], mode='lines', name='Data'))

    # Sayısal Analizler
    area = f"{scan.calculated_area_cm2:.1f} cm²" if pd.notnull(scan.calculated_area_cm2) else "--"
    perim = f"{scan.perimeter_cm:.1f} cm" if pd.notnull(scan.perimeter_cm) else "--"
    width = f"{scan.max_width_cm:.1f} cm" if pd.notnull(scan.max_width_cm) else "--"
    depth = f"{scan.max_depth_cm:.1f} cm" if pd.notnull(scan.max_depth_cm) else "--"

    estimation_text = estimate_geometric_shape(df_valid)

    return figs[0], figs[1], figs[2], figs[3], figs[4], estimation_text, df_clustered.to_json(
        orient='split'), area, perim, width, depth


@app.callback([Output('container-map-graph-3d', 'style'), Output('container-map-graph', 'style'),
               Output('container-regression-graph', 'style'), Output('container-polar-graph', 'style'),
               Output('container-time-series-graph', 'style')], Input('graph-selector-dropdown', 'value'))
def update_graph_visibility(selected_graph):
    styles = {'display': 'block'}
    return [styles if k == selected_graph else {'display': 'none'} for k in
            ['3d_map', 'map', 'regression', 'polar', 'time']]


@app.callback(
    [Output("cluster-info-modal", "is_open"), Output("modal-title", "children"), Output("modal-body", "children")],
    Input("scan-map-graph", "clickData"), State("clustered-data-store", "data"), prevent_initial_call=True)
def display_cluster_info(clickData, stored_data):
    if not clickData or not stored_data: return False, "", ""
    try:
        df = pd.read_json(stored_data, orient='split')
        cluster_id = clickData['points'][0].get('customdata')
        if cluster_id is None: return False, "", ""
        title = f"Küme #{cluster_id} Detayları";
        cluster_df = df[df['cluster'] == cluster_id]
        body = f"{len(cluster_df)} noktadan oluşuyor."
        return True, title, body
    except Exception as e:
        return True, "Hata", str(e)


@app.callback([Output('ai-yorum-sonucu', 'children'), Output('ai-image-container', 'children')],
              Input('ai-model-dropdown', 'value'), prevent_initial_call=True)
def get_ai_commentary(selected_model):
    if not selected_model: return "Yorum için bir model seçin.", None
    scan = get_latest_scan()
    if not scan: return dbc.Alert("Analiz için tarama verisi yok.", color="warning"), None
    df = pd.DataFrame(list(scan.points.all().values()))
    yorum = yorumla_tablo_verisi_gemini(df, selected_model)
    resim = generate_image_from_text(yorum, selected_model)
    return dcc.Markdown(yorum), resim