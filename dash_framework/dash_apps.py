```python
# DreamPi Dash App (dashboard.py or similar)

# Standart ve Django'ya bağımlı olmayan kütüphaneler
import logging
import os
import sys
import subprocess
import time
import io
import signal
import traceback

import psutil
import pandas as pd
import numpy as np
import base64
import json

# Analiz kütüphaneleri
from scipy.spatial import ConvexHull
from sklearn.cluster import DBSCAN
from sklearn.linear_model import RANSACRegressor

# Dash ve Plotly Kütüphaneleri
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, no_update, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import matplotlib.pyplot as plt

# Google AI kütüphaneleri
import google.generativeai as genai
from google.generativeai import types
from dotenv import load_dotenv
import dash

load_dotenv()

# --- SABİTLER VE UYGULAMA BAŞLATMA ---
SENSOR_SCRIPT_FILENAME = 'sensor_script.py'
FREE_MOVEMENT_SCRIPT_FILENAME = 'free_movement_script.py'
SENSOR_SCRIPT_PATH = os.path.join(os.getcwd(), SENSOR_SCRIPT_FILENAME)
FREE_MOVEMENT_SCRIPT_PATH = os.path.join(os.getcwd(), FREE_MOVEMENT_SCRIPT_FILENAME)
SENSOR_SCRIPT_LOCK_FILE = '/tmp/sensor_scan_script.lock'
SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'
DEFAULT_UI_SCAN_DURATION_ANGLE = 270.0
DEFAULT_UI_SCAN_STEP_ANGLE = 10.0
DEFAULT_UI_BUZZER_DISTANCE = 10
DEFAULT_UI_INVERT_MOTOR = False
DEFAULT_UI_STEPS_PER_REVOLUTION = 4096

# dash_apps.py içine eklenecek sabitler
AUTONOMOUS_SCRIPT_FILENAME = 'autonomous_drive.py'
AUTONOMOUS_SCRIPT_PATH = os.path.join(os.getcwd(), AUTONOMOUS_SCRIPT_FILENAME)
AUTONOMOUS_SCRIPT_LOCK_FILE = '/tmp/autonomous_drive_script.lock'
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'

app = DjangoDash('DreamPi', external_stylesheets=[dbc.themes.BOOTSTRAP])

# --- NAVBAR ---
navbar = dbc.NavbarSimple(
    children=[dbc.NavItem(dbc.NavLink("Admin Paneli", href="/admin/", external_link=True, target="_blank"))],
    brand="Dream Pi", brand_href="/", color="primary", dark=True, sticky="top", fluid=True, className="mb-4"
)

# --- YARDIMCI FONKSİYONLAR ---
def get_ai_model_options():
    try:
        from scanner.models import AIModelConfiguration
        configs = AIModelConfiguration.objects.filter(is_active=True).order_by('name')
        if not configs.exists():
            return [{'label': 'Aktif AI Modeli Yok', 'value': '', 'disabled': True}]
        return [{'label': config.name, 'value': config.id} for config in configs]
    except Exception as e:
        print(f"AI Modeli seçenekleri alınırken veritabanı hatası: {e}")
        return [{'label': 'Seçenekler Yüklenemedi (DB Hatası)', 'value': '', 'disabled': True}]


def get_latest_scan():
    try:
        from scanner.models import Scan
        running_scan = Scan.objects.filter(status='RUN').order_by('-start_time').first()
        if running_scan: return running_scan
        return Scan.objects.order_by('-start_time').first()
    except Exception as e:
        print(f"DB Hatası (get_latest_scan): {e}");
        return None


def is_process_running(pid):
    if pid is None: return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def add_scan_rays(fig, df):
    if df.empty or not all(col in df.columns for col in ['x_cm', 'y_cm']): return
    x_lines, y_lines = [], []
    for _, row in df.iterrows():
        x_lines.extend([0, row['y_cm'], None]);
        y_lines.extend([0, row['x_cm'], None])
    fig.add_trace(
        go.Scatter(x=x_lines, y=y_lines, mode='lines', line=dict(color='rgba(255,100,100,0.4)', dash='dash', width=1),
                   showlegend=False))


def add_sector_area(fig, df):
    if df.empty or not all(col in df.columns for col in ['x_cm', 'y_cm']): return
    poly_x, poly_y = df['y_cm'].tolist(), df['x_cm'].tolist()
    fig.add_trace(go.Scatter(x=[0] + poly_x + [0], y=[0] + poly_y + [0], mode='lines', fill='toself',
                             fillcolor='rgba(255,0,0,0.15)', line=dict(color='rgba(255,0,0,0.4)'),
                             name='Taranan Sektör'))


def add_sensor_position(fig):
    fig.add_trace(
        go.Scatter(x=[0], y=[0], mode='markers', marker=dict(size=12, symbol='circle', color='red'), name='Sensör'))


def update_polar_graph(fig, df):
    if df.empty: return
    fig.add_trace(go.Scatterpolar(r=df['mesafe_cm'], theta=df['derece'], mode='lines+markers', name='Mesafe'))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 400]),
                                 angularaxis=dict(direction="clockwise", period=360, thetaunit="degrees")))


def update_time_series_graph(fig, df):
    if df.empty or len(df) < 2: return
    df_s = df.copy().sort_values(by='timestamp')
    fig.add_trace(go.Scatter(x=df_s['timestamp'], y=df_s['mesafe_cm'], mode='lines+markers', name='Mesafe'))
    fig.update_layout(xaxis_title="Zaman", yaxis_title="Mesafe (cm)", xaxis_tickformat='%H:%M:%S',
                      xaxis_rangeslider_visible=True)


def find_clearest_path(df_valid):
    if df_valid.empty: return "En açık yol için veri yok."
    try:
        return f"En Açık Yol: {df_valid.loc[df_valid['mesafe_cm'].idxmax()]['derece']:.1f}° yönünde, {df_valid['mesafe_cm'].max():.1f} cm."
    except Exception as e:
        return f"En açık yol hesaplanamadı: {e}"


def analyze_polar_regression(df_valid):
    if len(df_valid) < 5: return None, "Polar regresyon için yetersiz veri."
    try:
        X, y = df_valid[['derece']].values, df_valid['mesafe_cm'].values
        ransac = RANSACRegressor(random_state=42).fit(X, y)
        slope = ransac.estimator_.coef_[0]
        inf = f"Yüzey dairesel/paralel (Eğim:{slope:.3f})" if abs(slope) < 0.1 else (
            f"Yüzey açı arttıkça uzaklaşıyor (Eğim:{slope:.3f})" if slope > 0 else f"Yüzey açı arttıkça yaklaşıyor (Eğim:{slope:.3f})")
        xr = np.array([df_valid['derece'].min(), df_valid['derece'].max()]).reshape(-1, 1)
        return {'x': xr.flatten(), 'y': ransac.predict(xr)}, "Polar Regresyon: " + inf
    except Exception as e:
        return None, f"Polar regresyon hatası: {e}"


def analyze_environment_shape(fig, df_valid_input):
    df_valid = df_valid_input.copy()
    if len(df_valid) < 10:
        df_valid.loc[:, 'cluster'] = -2;
        return "Analiz için yetersiz veri.", df_valid
    try:
        points_all = df_valid[['y_cm', 'x_cm']].to_numpy()
        db = DBSCAN(eps=15, min_samples=3).fit(points_all)
        df_valid.loc[:, 'cluster'] = db.labels_
        unique_clusters = set(db.labels_)
        num_actual_clusters = len(unique_clusters - {-1})
        desc = f"{num_actual_clusters} potansiyel nesne kümesi bulundu." if num_actual_clusters > 0 else "Belirgin bir nesne kümesi bulunamadı."
        colors = plt.cm.get_cmap('viridis', num_actual_clusters if num_actual_clusters > 0 else 1)
        for k in unique_clusters:
            cluster_points_df = df_valid[df_valid['cluster'] == k]
            if cluster_points_df.empty: continue
            points = cluster_points_df[['y_cm', 'x_cm']].to_numpy()
            if k == -1:
                c, s, n = 'rgba(128,128,128,0.3)', 5, 'Gürültü/Diğer'
            else:
                norm_k = (k / (num_actual_clusters - 1)) if num_actual_clusters > 1 else 0.0
                rc = colors(np.clip(norm_k, 0.0, 1.0));
                c = f'rgba({rc[0] * 255:.0f},{rc[1] * 255:.0f},{rc[2] * 255:.0f},0.9)';
                s, n = 8, f'Küme {k}'
            fig.add_trace(
                go.Scatter(x=points[:, 0], y=points[:, 1], mode='markers', marker=dict(color=c, size=s), name=n,
                           customdata=[k] * len(points)))
        return desc, df_valid
    except Exception as e:
        df_valid.loc[:, 'cluster'] = -2;
        return f"DBSCAN kümeleme hatası: {e}", df_valid


def estimate_geometric_shape(df_input):
    df = df_input.copy()
    if len(df) < 15: return "Şekil tahmini için yetersiz nokta."
    try:
        hull = ConvexHull(df[['x_cm', 'y_cm']].values)
        width, depth = df['y_cm'].max() - df['y_cm'].min(), df['x_cm'].max()
        if width < 1 or depth < 1: return "Algılanan şekil çok küçük."
        fill_factor = hull.area / (depth * width) if (depth * width) > 0 else 0
        if depth > 150 and width < 50 and fill_factor < 0.3: return "Tahmin: Dar ve derin bir boşluk (Koridor)."
        if fill_factor > 0.7 and (
                0.8 < (width / depth if depth > 0 else 0) < 1.2): return "Tahmin: Dolgun, kutu/dairesel bir nesne."
        if fill_factor > 0.6 and width > depth * 2.5: return "Tahmin: Geniş bir yüzey (Duvar)."
        if fill_factor < 0.4: return "Tahmin: İçbükey bir yapı veya dağınık nesneler."
        return "Tahmin: Düzensiz veya karmaşık bir yapı."
    except Exception as e:
        return f"Geometrik analiz hatası: {e}"


# --- ARAYÜZ BİLEŞENLERİ (LAYOUT) ---
# Kontrol panelinde mod seçimi ekleyin
control_panel = dbc.Card([
    dbc.CardHeader("🎛️ Sistem Kontrolü"),
    dbc.CardBody([
        # Mod Seçimi
        dbc.Row([
            dbc.Col([
                html.Label("🔄 Çalışma Modu:", className="fw-bold mb-2"),
                dcc.RadioItems(
                    id='operation-mode',
                    options=[
                        {'label': '📊 Haritalama Modu', 'value': 'mapping'},
                        {'label': '🚗 Otonom Sürüş Modu', 'value': 'autonomous'},
                        {'label': '🎮 Manuel Kontrol', 'value': 'manual'}
                    ],
                    value='mapping',
                    labelStyle={'display': 'block', 'margin': '5px 0'},
                    className="mb-3"
                )
            ], width=12)
        ]),
        
        # Mevcut parametreler...
        # Otonom sürüş parametreleri (sadece autonomous modunda görünür)
        html.Div(id='autonomous-parameters', children=[
            dbc.Row([
                dbc.Col([
                    html.Label("🎯 Hedef Mesafe (cm):", className="fw-bold"),
                    dbc.Input(
                        id='target-distance',
                        type='number',
                        value=100,
                        min=10,
                        max=300,
                        step=5
                    )
                ], width=6),
                dbc.Col([
                    html.Label("⚡ Hız Seviyesi:", className="fw-bold"),
                    dcc.Slider(
                        id='speed-level',
                        min=1,
                        max=5,
                        step=1,
                        value=3,
                        marks={i: f'{i}' for i in range(1, 6)}
                    )
                ], width=6)
            ], className="mb-3"),
        ], style={'display': 'none'}),  # Başlangıçta gizli
        
        # Başlat/Durdur butonları
        dbc.Row([
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button(
                        "▶️ Başlat",
                        id="start-button",
                        color="success",
                        size="lg",
                        className="me-2"
                    ),
                    dbc.Button(
                        "⏹️ Durdur",
                        id="stop-button", 
                        color="danger",
                        size="lg",
                        disabled=True
                    )
                ])
            ], width=12, className="text-center")
        ])
    ])
])
stats_panel = dbc.Card([dbc.CardHeader("Anlık Sensör Değerleri", className="bg-info text-white"), dbc.CardBody(dbc.Row(
    [dbc.Col(html.Div([html.H6("Mevcut Açı:"), html.H4(id='current-angle', children="--°")]), width=3,
             className="text-center border-end"),
     dbc.Col(html.Div([html.H6("Mevcut Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
             id='current-distance-col', width=3, className="text-center rounded border-end"),
     dbc.Col(html.Div([html.H6("Anlık Hız:"), html.H4(id='current-speed', children="-- cm/s")]), width=3,
             className="text-center border-end"),
     dbc.Col(html.Div([html.H6("Max. Algılanan Mesafe:"), html.H4(id='max-detected-distance', children="-- cm")]),
             width=3, className="text-center")]))], className="mb-3")
system_card = dbc.Card([dbc.CardHeader("Sistem Durumu", className="bg-secondary text-white"), dbc.CardBody(
    [dbc.Row([dbc.Col(html.Div([html.H6("Sensör Betiği Durumu:"), html.H5(id='script-status', children="Beklemede")]))],
             className="mb-2"), dbc.Row([dbc.Col(html.Div([html.H6("Pi CPU Kullanımı:"),
                                                           dbc.Progress(id='cpu-usage', value=0, color="success",
                                                                        style={"height": "20px"}, className="mb-1",
                                                                        label="0%")])), dbc.Col(html.Div(
        [html.H6("Pi RAM Kullanımı:"),
         dbc.Progress(id='ram-usage', value=0, color="info", style={"height": "20px"}, className="mb-1",
                      label="0%")]))])])], className="mb-3")
export_card = dbc.Card([dbc.CardHeader("Veri Dışa Aktarma (En Son Tarama)", className="bg-light"), dbc.CardBody(
    [dbc.Button('En Son Taramayı CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
     dcc.Download(id='download-csv'),
     dbc.Button('En Son Taramayı Excel İndir', id='export-excel-button', color="success", className="w-100"),
     dcc.Download(id='download-excel')])], className="mb-3")
analysis_card = dbc.Card([dbc.CardHeader("Tarama Analizi (En Son Tarama)", className="bg-dark text-white"),
                          dbc.CardBody([dbc.Row(
                              [dbc.Col([html.H6("Hesaplanan Alan:"), html.H4(id='calculated-area', children="-- cm²")]),
                               dbc.Col(
                                   [html.H6("Çevre Uzunluğu:"), html.H4(id='perimeter-length', children="-- cm")])]),
                                        dbc.Row([dbc.Col(
                                            [html.H6("Max Genişlik:"), html.H4(id='max-width', children="-- cm")]),
                                                 dbc.Col([html.H6("Max Derinlik:"),
                                                          html.H4(id='max-depth', children="-- cm")])],
                                                className="mt-2")])])
estimation_card = dbc.Card([dbc.CardHeader("Akıllı Ortam Analizi", className="bg-success text-white"), dbc.CardBody(
    html.Div("Tahmin: Bekleniyor...", id='environment-estimation-text', className="text-center"))])
visualization_tabs = dbc.Tabs([dbc.Tab([dbc.Row([dbc.Col(dcc.Dropdown(id='graph-selector-dropdown', options=[
    {'label': '3D Harita', 'value': '3d_map'}, {'label': '2D Kartezyen Harita', 'value': 'map'},
    {'label': 'Regresyon Analizi', 'value': 'regression'}, {'label': 'Polar Grafik', 'value': 'polar'},
    {'label': 'Zaman Serisi (Mesafe)', 'value': 'time'}], value='3d_map', clearable=False, style={'marginTop': '10px'}),
                                                         width=6)], justify="center", className="mb-3"), html.Div(
    [html.Div(dcc.Graph(id='scan-map-graph-3d', style={'height': '75vh'}), id='container-map-graph-3d'),
     html.Div(dcc.Graph(id='scan-map-graph', style={'height': '75vh'}), id='container-map-graph'),
     html.Div(dcc.Graph(id='polar-regression-graph', style={'height': '75vh'}), id='container-regression-graph'),
     html.Div(dcc.Graph(id='polar-graph', style={'height': '75vh'}), id='container-polar-graph'),
     html.Div(dcc.Graph(id='time-series-graph', style={'height': '75vh'}), id='container-time-series-graph')])],
                                       label="Grafikler", tab_id="tab-graphics"), dbc.Tab(
    dcc.Loading(id="loading-datatable", children=[html.Div(id='tab-content-datatable')]), label="Veri Tablosu",
    tab_id="tab-datatable")], id="visualization-tabs-main", active_tab="tab-graphics")

# --- ANA UYGULAMA YERLEŞİMİ (LAYOUT) ---
app.layout = html.Div(
    style={'padding': '20px'},
    children=[
        navbar,
        dbc.Row([
            dbc.Col([control_panel, html.Br(), stats_panel, html.Br(), system_card, html.Br(), export_card], md=4,
                    className="mb-3"),
            dbc.Col([
                visualization_tabs, html.Br(),
                dbc.Row([dbc.Col(analysis_card, md=8), dbc.Col(estimation_card, md=4)]),
                dbc.Row([dbc.Col([dbc.Card(
                    [dbc.CardHeader("Akıllı Yorumlama (Yapay Zeka)", className="bg-info text-white"), dbc.CardBody(
                        dcc.Loading(id="loading-ai-comment", type="default", children=[html.Div(id='ai-yorum-sonucu',
                                                                                                children=[html.P(
                                                                                                    "Yorum almak için yukarıdan bir AI yapılandırması seçin."), ],
                                                                                                className="text-center mt-2"),
                                                                                       html.Div(id='ai-image',
                                                                                                className="text-center mt-3")]))],
                    className="mt-3")], md=12)], className="mt-3")
            ], md=8)
        ]),

        # --- MERKEZİ VERİ DEPOLARI ---
        dcc.Store(id='latest-scan-object-store'),
        dcc.Store(id='latest-scan-points-store'),
        dcc.Store(id='clustered-data-store'),

        dbc.Modal([dbc.ModalHeader(dbc.ModalTitle(id="modal-title")), dbc.ModalBody(id="modal-body")],
                  id="cluster-info-modal", is_open=False, centered=True),
        dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0),
        dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0)
    ]
)


# --- CALLBACK FONKSİYONLARI ---

# GÜNCELLENDİ: MERKEZİ VERİ ÇEKME CALLBACK'İ (HATA YÖNETİMİ EKLENDİ)
@app.callback(
    [Output('latest-scan-object-store', 'data'),
     Output('latest-scan-points-store', 'data')],
    Input('interval-component-main', 'n_intervals')
)
def update_data_stores(n):
    try:
        scan = get_latest_scan()
        if not scan:
            return None, None

        from django.forms.models import model_to_dict
        scan_dict = model_to_dict(scan)
        scan_json = json.dumps(scan_dict, default=str)

        points_qs = scan.points.all().values('id', 'x_cm', 'y_cm', 'z_cm', 'derece', 'dikey_aci', 'mesafe_cm',
                                             'hiz_cm_s', 'timestamp')
        if not points_qs.exists():
            return scan_json, None

        df_pts = pd.DataFrame(list(points_qs))
        df_pts['timestamp'] = pd.to_datetime(df_pts['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        points_json = df_pts.to_json(orient='split')

        return scan_json, points_json
    except Exception as e:
        print(f"HATA: Merkezi veri deposu güncellenemedi: {e}")
        return None, None

# Callback fonksiyonları ekleyin
@app.callback(
    Output('autonomous-parameters', 'style'),
    Output('mapping-parameters', 'style'),  # Mevcut haritalama parametreleri
    Input('operation-mode', 'value')
)
def toggle_mode_parameters(selected_mode):
    if selected_mode == 'autonomous':
        return {'display': 'block'}, {'display': 'none'}
    elif selected_mode == 'mapping':
        return {'display': 'none'}, {'display': 'block'}
    else:  # manual
        return {'display': 'none'}, {'display': 'none'}

@app.callback(
    [Output("start-button", "children"),
     Output("start-button", "disabled"),
     Output("stop-button", "disabled")],
    [Input("start-button", "n_clicks"),
     Input("stop-button", "n_clicks")],
    [State("operation-mode", "value"),
     State("target-distance", "value"),
     State("speed-level", "value"),
     State("scan-duration-angle-input", "value"),      # Haritalama parametreleri
     State("step-angle-input", "value"),
     State("buzzer-distance-input", "value")]
)
def handle_start_stop_operations(start_clicks, stop_clicks, mode, 
                                target_dist, speed, h_angle, h_step, buzzer_dist):
    ctx = dash.callback_context
    if not ctx.triggered:
        return "▶️ Başlat", False, True
    
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    
    if button_id == "start-button" and start_clicks:
        if mode == 'autonomous':
            return start_autonomous_mode(target_dist, speed)
        elif mode == 'mapping':
            return start_mapping_mode(h_angle, h_step, buzzer_dist)
        elif mode == 'manual':
            return start_manual_mode()
    
    elif button_id == "stop-button" and stop_clicks:
        return stop_current_operation(mode)
    
    return "▶️ Başlat", False, True

def start_autonomous_mode(target_distance, speed_level):
    """Otonom sürüş modunu başlatır"""
    try:
        # Önceki işlemleri durdur
        stop_all_scripts()
        
        # Otonom sürüş parametreleri
        cmd = [
            sys.executable, AUTONOMOUS_SCRIPT_PATH,
            f"--target-distance={target_distance}",
            f"--speed-level={speed_level}",
            f"--mode=autonomous"
        ]
        
        # Arka planda çalıştır
        subprocess.Popen(cmd, 
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL,
                        start_new_session=True)
        
        return "🔄 Otonom Sürüş Çalışıyor...", True, False
        
    except Exception as e:
        print(f"Otonom sürüş başlatma hatası: {e}")
        return "❌ Başlatma Hatası", False, True

def start_mapping_mode(h_angle, h_step, buzzer_dist):
    """Haritalama modunu başlatır (mevcut kod)"""
    # Mevcut sensor_script başlatma kodunuz
    pass

def start_manual_mode():
    """Manuel kontrol modunu başlatır"""
    return "🎮 Manuel Kontrol Aktif", True, False

def stop_current_operation(mode):
    """Mevcut işlemi durdurur"""
    try:
        if mode == 'autonomous':
            # Otonom sürüş script'ini durdur
            if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE):
                with open(AUTONOMOUS_SCRIPT_PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                try:
                    os.kill(pid, 15)  # SIGTERM
                except ProcessLookupError:
                    pass
        elif mode == 'mapping':
            # Haritalama script'ini durdur (mevcut kodunuz)
            pass
            
        return "▶️ Başlat", False, True
        
    except Exception as e:
        print(f"Durdurma hatası: {e}")
        return "▶️ Başlat", False, True

def stop_all_scripts():
    """Tüm çalışan script'leri durdurur"""
    for script_pid_file in [SENSOR_SCRIPT_PID_FILE, AUTONOMOUS_SCRIPT_PID_FILE]:
        if os.path.exists(script_pid_file):
            try:
                with open(script_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                os.kill(pid, 15)
            except:
                pass

@app.callback(Output('scan-parameters-wrapper', 'style'), Input('mode-selection-radios', 'value'))
def toggle_parameter_visibility(selected_mode):
    return {'display': 'block'} if selected_mode == 'scan_and_map' else {'display': 'none'}


@app.callback(
    [Output('ai-model-dropdown', 'options'), Output('ai-model-dropdown', 'disabled'),
     Output('ai-model-dropdown', 'placeholder')],
    Input('interval-component-main', 'n_intervals')
)
def populate_ai_model_dropdown(n):
    if n > 0: raise PreventUpdate
    options = get_ai_model_options()
    if options and not options[0].get('disabled'):
        return options, False, "Analiz için bir AI yapılandırması seçin..."
    return [], True, "Aktif AI Modeli Bulunamadı"


@app.callback(
    Output('scan-status-message', 'children'),
    Input('start-scan-button', 'n_clicks'),
    [State('mode-selection-radios', 'value'),
     State('scan-duration-angle-input', 'value'),
     State('step-angle-input', 'value'),
     State('buzzer-distance-input', 'value'),
     State('steps-per-rev-input', 'value'),
     State('invert-motor-checkbox', 'value')],
    prevent_initial_call=True
)
def handle_start_scan_script(n_clicks, selected_mode, duration, step, buzzer_dist, steps_per_rev, invert_motor):
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

    for fp in [SENSOR_SCRIPT_LOCK_FILE, SENSOR_SCRIPT_PID_FILE]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError as e_rm:
                print(f"Eski dosya silinemedi ({fp}): {e_rm}")

    cmd = []
    if selected_mode == 'scan_and_map':
        try:
            h_angle = float(duration)
            h_step = float(step)
            buzz_dist = int(buzzer_dist)
            steps = int(steps_per_rev)

            if not (10 <= h_angle <= 720 and 0.1 <= h_step <= 45 and 0 <= buzz_dist <= 200):
                return dbc.Alert("Tarama parametreleri beklenen aralıkların dışında!", color="danger")

            if not (500 <= steps <= 10000):
                return dbc.Alert("Motor Adım/Tur değeri beklenen aralıkların dışında!", color="danger")

        except (ValueError, TypeError):
            return dbc.Alert("Lütfen tüm parametreler için geçerli sayılar girin.", color="danger")

        cmd = [sys.executable, SENSOR_SCRIPT_PATH,
               "--h-angle", str(h_angle),
               "--h-step", str(h_step),
               "--buzzer-distance", str(buzz_dist),
               "--steps-per-rev", str(steps)]

        if invert_motor:
            cmd.append("--invert-motor")

    elif selected_mode == 'free_movement':
        cmd = [sys.executable, FREE_MOVEMENT_SCRIPT_PATH]
    else:
        return dbc.Alert("Geçersiz mod seçildi!", color="danger")

    try:
        if not os.path.exists(cmd[1]):
            return dbc.Alert(f"HATA: Betik dosyası bulunamadı: {cmd[1]}", color="danger")

        subprocess.Popen(cmd, start_new_session=True)

        return dbc.Alert(
            f"{'3D Haritalama' if selected_mode == 'scan_and_map' else 'Serbest Hareket'} modu başlatıldı.",
            color="success")
    except Exception as e:
        return dbc.Alert(f"Betik başlatma hatası: {e}", color="danger")


@app.callback(Output('scan-status-message', 'children', allow_duplicate=True), Input('stop-scan-button', 'n_clicks'),
              prevent_initial_call=True)
def handle_stop_scan_script(n_clicks):
    if n_clicks == 0: return no_update
    pid_to_kill = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                pid_to_kill = int(pf.read().strip())