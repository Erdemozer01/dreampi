import base64
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

from scipy.spatial import ConvexHull
from sklearn.cluster import DBSCAN
from sklearn.linear_model import RANSACRegressor
from google.genai import types

import google.generativeai as genai
# Django modellerini ve AI servisini import etme
try:
    from django.db.models import Max
    from scanner.models import Scan, ScanPoint, AIModelConfiguration
    from scanner.ai_analyzer import AIAnalyzerService

    DJANGO_MODELS_AVAILABLE = True
    print("Dashboard: Django modelleri ve AI Servisi başarıyla import edildi.")
except ModuleNotFoundError:
    print("UYARI: Gerekli Django modülleri veya AI Servisi (scanner.models, scanner.ai_analyzer) bulunamadı.")
    print("Lütfen proje yapınızı ve PYTHONPATH'ı kontrol edin.")
    DJANGO_MODELS_AVAILABLE = False
    Scan, ScanPoint, AIModelConfiguration, AIAnalyzerService = None, None, None, None
except Exception as e:
    print(f"Django modülleri veya AI Servisi import edilirken bir hata oluştu: {e}")
    DJANGO_MODELS_AVAILABLE = False
    Scan, ScanPoint, AIModelConfiguration, AIAnalyzerService = None, None, None, None

# Dash ve Plotly Kütüphaneleri
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, no_update, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import matplotlib.pyplot as plt

from dotenv import load_dotenv

# .env dosyasından ortam değişkenlerini yükler (varsa)
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

app = DjangoDash('RealtimeSensorDashboard', external_stylesheets=[dbc.themes.BOOTSTRAP])

# --- NAVBAR OLUŞTURMA ---
navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("Admin Paneli", href="/admin/", external_link=True, target="_blank")),
    ],
    brand="Dream Pi",
    brand_href="/",
    color="primary",
    dark=True,
    sticky="top",
    fluid=True,
    className="mb-4"
)


# --- YARDIMCI FONKSİYON: Dinamik AI Modeli Seçenekleri için ---
def get_ai_model_options():
    """
    Veritabanındaki aktif AI yapılandırmalarını Dash dropdown formatında döndürür.
    """
    if not DJANGO_MODELS_AVAILABLE:
        return [{'label': 'Veritabanı Bağlantısı Yok', 'value': '', 'disabled': True}]
    try:
        configs = AIModelConfiguration.objects.filter(is_active=True).order_by('name')
        if not configs.exists():
            return [{'label': 'Aktif AI Modeli Yok (Admin Panelinden Ekleyin)', 'value': '', 'disabled': True}]

        options = [{'label': config.name, 'value': config.id} for config in configs]
        return options
    except Exception as e:
        print(f"AI Modeli seçenekleri alınırken hata: {e}")
        return [{'label': 'Seçenekler Yüklenemedi', 'value': '', 'disabled': True}]


# --- ARAYÜZ BİLEŞENLERİ ---
title_card = dbc.Row(
    [dbc.Col(html.H1("Kullanıcı Paneli", className="text-center my-3 mb-5"), width=12), html.Hr()]
)

control_panel = dbc.Card([
    dbc.CardHeader("Kontrol ve Ayarlar", className="bg-primary text-white"),
    dbc.CardBody([
        html.H6("Çalışma Modu:", className="mt-1"),
        dbc.RadioItems(
            id='mode-selection-radios',
            options=[
                {'label': '3D Haritalama', 'value': 'scan_and_map'},
                {'label': 'Serbest Hareket (Gözcü)', 'value': 'free_movement'},
            ],
            value='scan_and_map',
            inline=False,
            className="mb-3",
        ),
        html.Hr(),
        dbc.Row([
            dbc.Col(html.Button('Başlat', id='start-scan-button', n_clicks=0,
                                className="btn btn-success btn-lg w-100 mb-2"), width=6),
            dbc.Col(html.Button('Durdur', id='stop-scan-button', n_clicks=0,
                                className="btn btn-danger btn-lg w-100 mb-2"), width=6)
        ]),
        html.Div(id='scan-status-message', style={'marginTop': '10px', 'minHeight': '40px', 'textAlign': 'center'},
                 className="mb-3"),
        html.Hr(),
        html.Div(id='scan-parameters-wrapper', children=[
            html.H6("Yapay Zeka Seçimi:", className="mt-3"),
            dcc.Dropdown(
                id='ai-model-dropdown',
                options=get_ai_model_options(),
                placeholder="Analiz için bir AI yapılandırması seçin...",
                clearable=True,
                className="mb-3"
            ),
            html.Hr(),
            html.H6("Tarama Parametreleri:", className="mt-2"),
            dbc.InputGroup([dbc.InputGroupText("Yatay Tarama Açısı (°)", style={"width": "180px"}),
                            dbc.Input(id="scan-duration-angle-input", type="number",
                                      value=DEFAULT_UI_SCAN_DURATION_ANGLE,
                                      min=10, max=720, step=1)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Yatay Adım Açısı (°)", style={"width": "180px"}),
                            dbc.Input(id="step-angle-input", type="number", value=DEFAULT_UI_SCAN_STEP_ANGLE, min=0.1,
                                      max=45, step=0.1)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Uyarı Mes. (cm)", style={"width": "180px"}),
                            dbc.Input(id="buzzer-distance-input", type="number", value=DEFAULT_UI_BUZZER_DISTANCE,
                                      min=0,
                                      max=200, step=1)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Motor Adım/Tur", style={"width": "180px"}),
                            dbc.Input(id="steps-per-rev-input", type="number", value=DEFAULT_UI_STEPS_PER_REVOLUTION,
                                      min=500, max=10000, step=1)], className="mb-2"),
            dbc.Checkbox(id="invert-motor-checkbox", label="Motor Yönünü Ters Çevir", value=DEFAULT_UI_INVERT_MOTOR,
                         className="mt-2 mb-2"),
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
             className="mb-2"),
     dbc.Row([dbc.Col(html.Div([html.H6("Pi CPU Kullanımı:"),
                                dbc.Progress(id='cpu-usage', value=0, color="success", style={"height": "20px"},
                                             className="mb-1", label="0%")])),
              dbc.Col(html.Div([html.H6("Pi RAM Kullanımı:"),
                                dbc.Progress(id='ram-usage', value=0, color="info", style={"height": "20px"},
                                             className="mb-1", label="0%")]))])])], className="mb-3")

export_card = dbc.Card([dbc.CardHeader("Veri Dışa Aktarma (En Son Tarama)", className="bg-light"), dbc.CardBody(
    [dbc.Button('En Son Taramayı CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
     dcc.Download(id='download-csv'),
     dbc.Button('En Son Taramayı Excel İndir', id='export-excel-button', color="success", className="w-100"),
     dcc.Download(id='download-excel')])], className="mb-3")

analysis_card = dbc.Card([
    dbc.CardHeader("Tarama Analizi (En Son Tarama)", className="bg-dark text-white"),
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
    dbc.CardHeader("Akıllı Ortam Analizi", className="bg-success text-white"),
    dbc.CardBody(html.Div("Tahmin: Bekleniyor...", id='environment-estimation-text', className="text-center"))
])

visualization_tabs = dbc.Tabs([
    dbc.Tab([
        dbc.Row([
            dbc.Col(
                dcc.Dropdown(
                    id='graph-selector-dropdown',
                    options=[
                        {'label': '3D Harita', 'value': '3d_map'},
                        {'label': '2D Kartezyen Harita', 'value': 'map'},
                        {'label': 'Regresyon Analizi', 'value': 'regression'},
                        {'label': 'Polar Grafik', 'value': 'polar'},
                        {'label': 'Zaman Serisi (Mesafe)', 'value': 'time'},
                    ],
                    value='3d_map',
                    clearable=False,
                    style={'marginTop': '10px'}
                ),
                width=6,
            )
        ], justify="center", className="mb-3"),
        html.Div([
            html.Div(dcc.Graph(id='scan-map-graph-3d', style={'height': '75vh'}), id='container-map-graph-3d'),
            html.Div(dcc.Graph(id='scan-map-graph', style={'height': '75vh'}), id='container-map-graph'),
            html.Div(dcc.Graph(id='polar-regression-graph', style={'height': '75vh'}), id='container-regression-graph'),
            html.Div(dcc.Graph(id='polar-graph', style={'height': '75vh'}), id='container-polar-graph'),
            html.Div(dcc.Graph(id='time-series-graph', style={'height': '75vh'}), id='container-time-series-graph'),
        ])
    ], label="Grafikler", tab_id="tab-graphics"),
    dbc.Tab(
        dcc.Loading(id="loading-datatable", children=[html.Div(id='tab-content-datatable')]),
        label="Veri Tablosu",
        tab_id="tab-datatable"
    )
], id="visualization-tabs-main", active_tab="tab-graphics")

app.layout = html.Div(
    style={'padding': '20px'},
    children=[
        navbar,
        dbc.Row([
            dbc.Col([
                control_panel,
                html.Br(),
                stats_panel,
                html.Br(),
                system_card,
                html.Br(),
                export_card
            ], md=4, className="mb-3"),
            dbc.Col([
                visualization_tabs,
                html.Br(),
                dbc.Row([
                    dbc.Col(analysis_card, md=8),
                    dbc.Col(estimation_card, md=4)
                ]),
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader("Akıllı Yorumlama (Yapay Zeka)", className="bg-info text-white"),
                            dbc.CardBody(
                                dcc.Loading(
                                    id="loading-ai-comment",
                                    type="default",
                                    children=[
                                        html.Div(id='ai-yorum-sonucu', children=[
                                            html.P("Yorum almak için yukarıdan bir AI yapılandırması seçin."),
                                        ], className="text-center mt-2")
                                    ]
                                )
                            )
                        ], className="mt-3")
                    ], md=12)
                ], className="mt-3")
            ], md=8)
        ]),
        dcc.Store(id='clustered-data-store'),
        dbc.Modal(
            [dbc.ModalHeader(dbc.ModalTitle(id="modal-title")), dbc.ModalBody(id="modal-body")],
            id="cluster-info-modal",
            is_open=False,
            centered=True
        ),
        dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0),
        dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0),
    ]
)


# --- YARDIMCI FONKSİYONLAR ---
def is_process_running(pid):
    if pid is None: return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def get_latest_scan():
    if not DJANGO_MODELS_AVAILABLE: return None
    try:
        running_scan = Scan.objects.filter(status='RUNNING').order_by('-start_time').first()
        if running_scan: return running_scan
        return Scan.objects.order_by('-start_time').first()
    except Exception as e:
        print(f"DB Hatası (get_latest_scan): {e}")
        return None


def add_scan_rays(fig, df):
    if df.empty or not all(col in df.columns for col in ['x_cm', 'y_cm']): return
    x_lines, y_lines = [], []
    for _, row in df.iterrows():
        x_lines.extend([0, row['y_cm'], None])
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
    if df.empty or not all(col in df.columns for col in ['mesafe_cm', 'derece']): return
    fig.add_trace(go.Scatterpolar(r=df['mesafe_cm'], theta=df['derece'], mode='lines+markers', name='Mesafe'))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 250]),
                                 angularaxis=dict(direction="clockwise", period=360, thetaunit="degrees")))


def update_time_series_graph(fig, df):
    if df.empty or 'timestamp' not in df.columns or 'mesafe_cm' not in df.columns:
        fig.add_trace(go.Scatter(x=[], y=[], mode='lines', name='Veri Yok'))
        return
    try:
        df_s = df.copy()
        df_s['timestamp'] = pd.to_datetime(df_s['timestamp'], errors='coerce')
        df_s.dropna(subset=['timestamp'], inplace=True)
        if len(df_s) < 2: return
        df_s = df_s.sort_values(by='timestamp')
        fig.add_trace(go.Scatter(x=df_s['timestamp'], y=df_s['mesafe_cm'], mode='lines+markers', name='Mesafe'))
        fig.update_layout(
            xaxis_title="Zaman", yaxis_title="Mesafe (cm)",
            xaxis_tickformat='%d %b %Y<br>%H:%M:%S',
            xaxis_rangeslider_visible=True
        )
    except Exception as e:
        logging.error(f"Zaman serisi grafiği hatası: {e}")
        fig.add_trace(go.Scatter(x=[], y=[], mode='lines', name='Grafik Hatası'))


def find_clearest_path(df_valid):
    if df_valid.empty or not all(
        col in df_valid.columns for col in ['mesafe_cm', 'derece']): return "En açık yol için veri yok."
    try:
        cp = df_valid.loc[df_valid['mesafe_cm'].idxmax()]
        return f"En Açık Yol: {cp['derece']:.1f}° yönünde, {cp['mesafe_cm']:.1f} cm."
    except Exception as e:
        print(f"En açık yol hesaplama hatası: {e}")
        return "En açık yol hesaplanamadı."


def analyze_polar_regression(df_valid):
    if len(df_valid) < 5: return None, "Polar regresyon için yetersiz veri."
    X, y = df_valid[['derece']].values, df_valid['mesafe_cm'].values
    try:
        ransac = RANSACRegressor(random_state=42)
        ransac.fit(X, y)
        slope = ransac.estimator_.coef_[0]
        inf = f"Yüzey dairesel/paralel (Eğim:{slope:.3f})" if abs(slope) < 0.1 else (
            f"Yüzey açı arttıkça uzaklaşıyor (Eğim:{slope:.3f})" if slope > 0 else f"Yüzey açı arttıkça yaklaşıyor (Eğim:{slope:.3f})")
        xr = np.array([df_valid['derece'].min(), df_valid['derece'].max()]).reshape(-1, 1)
        return {'x': xr.flatten(), 'y': ransac.predict(xr)}, "Polar Regresyon: " + inf
    except Exception as e:
        print(f"Polar regresyon hatası: {e}")
        return None, "Polar regresyon hatası."


def analyze_environment_shape(fig, df_valid_input):
    df_valid = df_valid_input.copy()
    if len(df_valid) < 10:
        df_valid.loc[:, 'cluster'] = -2
        return "Analiz için yetersiz veri.", df_valid
    points_all = df_valid[['y_cm', 'x_cm']].to_numpy()
    try:
        db = DBSCAN(eps=15, min_samples=3).fit(points_all)
        df_valid.loc[:, 'cluster'] = db.labels_
    except Exception as e:
        print(f"DBSCAN hatası: {e}")
        df_valid.loc[:, 'cluster'] = -2
        return "DBSCAN kümeleme hatası.", df_valid
    unique_clusters = set(df_valid['cluster'].unique())
    num_actual_clusters = len(unique_clusters - {-1, -2})
    desc = f"{num_actual_clusters} potansiyel nesne kümesi bulundu." if num_actual_clusters > 0 else "Belirgin bir nesne kümesi bulunamadı."
    colors = plt.cm.get_cmap('viridis', num_actual_clusters if num_actual_clusters > 0 else 1)
    for k_label in unique_clusters:
        if k_label == -2: continue
        cluster_points_df = df_valid[df_valid['cluster'] == k_label]
        if cluster_points_df.empty: continue
        cluster_points_np = cluster_points_df[['y_cm', 'x_cm']].to_numpy()
        if k_label == -1:
            color_val, point_size, name_val = 'rgba(128,128,128,0.3)', 5, 'Gürültü/Diğer'
        else:
            norm_k = (k_label / (num_actual_clusters - 1)) if num_actual_clusters > 1 else 0.0
            raw_col = colors(np.clip(norm_k, 0.0, 1.0))
            color_val = f'rgba({raw_col[0] * 255:.0f},{raw_col[1] * 255:.0f},{raw_col[2] * 255:.0f},0.9)'
            point_size, name_val = 8, f'Küme {k_label}'
        fig.add_trace(go.Scatter(x=cluster_points_np[:, 0], y=cluster_points_np[:, 1], mode='markers',
                                 marker=dict(color=color_val, size=point_size), name=name_val,
                                 customdata=[k_label] * len(cluster_points_np)))
    return desc, df_valid


def estimate_geometric_shape(df_input):
    df = df_input.copy()
    if len(df) < 15: return "Şekil tahmini için yetersiz nokta."
    try:
        points = df[['x_cm', 'y_cm']].values
        hull = ConvexHull(points)
        min_y_val, max_y_val = df['y_cm'].min(), df['y_cm'].max()
        width = max_y_val - min_y_val
        depth = df['x_cm'].max()
        if width < 1 or depth < 1: return "Algılanan şekil çok küçük."
        fill_factor = hull.area / (depth * width) if (depth * width) > 0 else 0
        if depth > 150 and width < 50 and fill_factor < 0.3: return "Tahmin: Dar ve derin bir boşluk (Koridor)."
        if fill_factor > 0.7 and (
                0.8 < (width / depth if depth > 0 else 0) < 1.2): return "Tahmin: Dolgun, kutu/dairesel bir nesne."
        if fill_factor > 0.6 and width > depth * 2.5: return "Tahmin: Geniş bir yüzey (Duvar)."
        if fill_factor < 0.4: return "Tahmin: İçbükey bir yapı veya dağınık nesneler."
        return "Tahmin: Düzensiz veya karmaşık bir yapı."
    except Exception as e:
        print(f"Geometrik analiz hatası: {e}")
        return "Geometrik analiz hatası."


# --- CALLBACK FONKSİYONLARI ---

@app.callback(
    Output('scan-parameters-wrapper', 'style'),
    Input('mode-selection-radios', 'value')
)
def toggle_parameter_visibility(selected_mode):
    if selected_mode == 'scan_and_map':
        return {'display': 'block'}
    return {'display': 'none'}


@app.callback(
    Output('scan-status-message', 'children'),
    [Input('start-scan-button', 'n_clicks')],
    [State('mode-selection-radios', 'value'),
     State('scan-duration-angle-input', 'value'), State('step-angle-input', 'value'),
     State('buzzer-distance-input', 'value'), State('invert-motor-checkbox', 'value'),
     State('steps-per-rev-input', 'value')],
    prevent_initial_call=True
)
def handle_start_scan_script(n_clicks, selected_mode, duration, step, buzzer_dist, invert, steps_rev):
    if n_clicks == 0: return no_update
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
    py_exec = sys.executable
    cmd = []
    if selected_mode == 'scan_and_map':
        cmd = [py_exec, SENSOR_SCRIPT_PATH, "--h-angle", str(duration), "--h-step", str(step), "--buzzer-distance",
               str(buzzer_dist), "--invert-motor-direction", str(invert), "--steps-per-rev", str(steps_rev)]
    elif selected_mode == 'free_movement':
        cmd = [py_exec, FREE_MOVEMENT_SCRIPT_PATH]
    else:
        return dbc.Alert("Geçersiz mod seçildi!", color="danger")
    try:
        if not os.path.exists(cmd[1]):
            return dbc.Alert(f"HATA: Betik dosyası bulunamadı: {cmd[1]}", color="danger")
        subprocess.Popen(cmd, start_new_session=True)
        # ... (PID dosyası bekleme mantığı) ...
        return dbc.Alert(
            f"{'3D Haritalama' if selected_mode == 'scan_and_map' else 'Serbest Hareket'} modu başlatıldı.",
            color="success")
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
            if is_process_running(pid_to_kill): os.kill(pid_to_kill, signal.SIGKILL)
            return dbc.Alert(f"Çalışan betik (PID:{pid_to_kill}) durduruldu.", color="info")
        except Exception as e:
            return dbc.Alert(f"Durdurma hatası: {e}", color="danger")
    return dbc.Alert("Çalışan betik bulunamadı.", color="warning")


@app.callback(
    [Output('script-status', 'children'), Output('script-status', 'className'), Output('cpu-usage', 'value'),
     Output('cpu-usage', 'label'), Output('ram-usage', 'value'), Output('ram-usage', 'label')],
    [Input('interval-component-system', 'n_intervals')]
)
def update_system_card(n):
    pid_val = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                pid_val = int(pf.read().strip())
        except:
            pass
    status_text, status_class = (f"Çalışıyor (PID:{pid_val})", "text-success") if pid_val and is_process_running(
        pid_val) else ("Çalışmıyor", "text-danger")
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    return status_text, status_class, cpu, f"{cpu:.1f}%", ram, f"{ram:.1f}%"


@app.callback(
    [Output('current-angle', 'children'), Output('current-distance', 'children'), Output('current-speed', 'children'),
     Output('current-distance-col', 'style'), Output('max-detected-distance', 'children')],
    [Input('interval-component-main', 'n_intervals')]
)
def update_realtime_values(n):
    scan = get_latest_scan()
    dist_style = {'padding': '10px', 'transition': 'background-color 0.5s ease', 'borderRadius': '5px'}
    if not scan: return "--°", "-- cm", "-- cm/s", dist_style, "-- cm"
    point = scan.points.order_by('-timestamp').first()
    if not point: return "--°", "-- cm", "-- cm/s", dist_style, "-- cm"
    angle_s = f"{point.derece:.1f}°" if pd.notnull(point.derece) else "--°"
    dist_s = f"{point.mesafe_cm:.1f} cm" if pd.notnull(point.mesafe_cm) else "-- cm"
    speed_s = f"{point.hiz_cm_s:.1f} cm/s" if pd.notnull(point.hiz_cm_s) else "-- cm/s"
    if scan.buzzer_distance_setting is not None and pd.notnull(
            point.mesafe_cm) and 0 < point.mesafe_cm <= scan.buzzer_distance_setting:
        dist_style.update({'backgroundColor': '#d9534f', 'color': 'white'})
    max_dist_agg = scan.points.filter(mesafe_cm__lt=2500, mesafe_cm__gt=0).aggregate(max_dist_val=Max('mesafe_cm'))
    max_dist_s = f"{max_dist_agg['max_dist_val']:.1f} cm" if max_dist_agg.get('max_dist_val') is not None else "-- cm"
    return angle_s, dist_s, speed_s, dist_style, max_dist_s


@app.callback(
    [Output('calculated-area', 'children'), Output('perimeter-length', 'children'), Output('max-width', 'children'),
     Output('max-depth', 'children')],
    [Input('interval-component-main', 'n_intervals')]
)
def update_analysis_panel(n):
    scan = get_latest_scan()
    if not scan: return "-- cm²", "-- cm", "-- cm", "-- cm"
    area_s = f"{scan.calculated_area_cm2:.2f} cm²" if pd.notnull(scan.calculated_area_cm2) else "N/A"
    perim_s = f"{scan.perimeter_cm:.2f} cm" if pd.notnull(scan.perimeter_cm) else "N/A"
    width_s = f"{scan.max_width_cm:.2f} cm" if pd.notnull(scan.max_width_cm) else "N/A"
    depth_s = f"{scan.max_depth_cm:.2f} cm" if pd.notnull(scan.max_depth_cm) else "N/A"
    return area_s, perim_s, width_s, depth_s


@app.callback(Output('download-csv', 'data'), Input('export-csv-button', 'n_clicks'), prevent_initial_call=True)
def export_csv_callback(n_clicks_csv):
    scan = get_latest_scan()
    if not (scan and scan.points.exists()):
        return dcc.send_data_frame(pd.DataFrame().to_csv, "veri_yok.csv", index=False)
    df = pd.DataFrame(list(scan.points.all().values()))
    return dcc.send_data_frame(df.to_csv, f"tarama_id_{scan.id}.csv", index=False)


@app.callback(Output('download-excel', 'data'), Input('export-excel-button', 'n_clicks'), prevent_initial_call=True)
def export_excel_callback(n_clicks_excel):
    scan = get_latest_scan()
    if not scan: return dcc.send_bytes(b"", "tarama_yok.xlsx")
    buf = io.BytesIO()
    try:
        scan_info_df = pd.DataFrame([Scan.objects.filter(id=scan.id).values().first()])
        points_df = pd.DataFrame(list(scan.points.all().values()))
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            scan_info_df.to_excel(writer, sheet_name=f'Scan_{scan.id}_Info', index=False)
            if not points_df.empty:
                points_df.to_excel(writer, sheet_name=f'Scan_{scan.id}_Points', index=False)
    except Exception as e:
        buf.seek(0);
        buf.truncate()
        pd.DataFrame([{"Hata": str(e)}]).to_excel(buf, sheet_name='Hata', index=False)
    buf.seek(0)
    return dcc.send_bytes(buf.getvalue(), f"tarama_detaylari_id_{scan.id}.xlsx")


@app.callback(Output('tab-content-datatable', 'children'),
              [Input('visualization-tabs-main', 'active_tab'), Input('interval-component-main', 'n_intervals')])
def render_and_update_data_table(active_tab, n):
    if active_tab != "tab-datatable": return None
    scan = get_latest_scan()
    if not (scan and scan.points.exists()): return html.P("Görüntülenecek veri yok.")
    df = pd.DataFrame(list(
        scan.points.order_by('-id').values('id', 'derece', 'dikey_aci', 'mesafe_cm', 'hiz_cm_s', 'x_cm', 'y_cm', 'z_cm',
                                           'timestamp')))
    if 'timestamp' in df.columns: df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
    return dash_table.DataTable(data=df.to_dict('records'),
                                columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                page_size=50, sort_action="native", filter_action="native", virtualization=True,
                                fixed_rows={'headers': True})


@app.callback(
    [Output('scan-map-graph-3d', 'figure'), Output('scan-map-graph', 'figure'),
     Output('polar-regression-graph', 'figure'), Output('polar-graph', 'figure'), Output('time-series-graph', 'figure'),
     Output('environment-estimation-text', 'children'), Output('clustered-data-store', 'data')],
    Input('interval-component-main', 'n_intervals')
)
def update_all_graphs(n):
    scan = get_latest_scan()
    if not scan:
        empty_fig = go.Figure(layout={'title': 'Veri Bekleniyor...'})
        return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, "Tarama başlatın...", None

    figs = [go.Figure() for _ in range(5)]
    scan_id_for_revision = str(scan.id)
    points_qs = scan.points.all().values('x_cm', 'y_cm', 'z_cm', 'derece', 'mesafe_cm', 'timestamp')
    if not points_qs.exists():
        empty_fig = go.Figure(layout={'title': f'Tarama #{scan.id} için nokta verisi yok'})
        return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, "Nokta verisi bulunamadı.", None

    df_pts = pd.DataFrame(list(points_qs))
    df_val = df_pts[(df_pts['mesafe_cm'] > 0.1) & (df_pts['mesafe_cm'] < 400.0)].copy()

    # 3D Graph
    if not df_val.empty:
        figs[0].add_trace(go.Scatter3d(x=df_val['y_cm'], y=df_val['x_cm'], z=df_val['z_cm'], mode='markers',
                                       marker=dict(size=2, color=df_val['z_cm'], colorscale='Viridis', showscale=True,
                                                   colorbar_title='Yükseklik (cm)')))

    est_text, store_data = "Analiz için yetersiz veri.", None
    if len(df_val) >= 10:
        est_cart, df_clus = analyze_environment_shape(figs[1], df_val.copy())
        store_data = df_clus.to_json(orient='split')
        add_scan_rays(figs[1], df_val)
        add_sector_area(figs[1], df_val)

        line_data, est_polar = analyze_polar_regression(df_val)
        figs[2].add_trace(go.Scatter(x=df_val['derece'], y=df_val['mesafe_cm'], mode='markers', name='Noktalar'))
        if line_data: figs[2].add_trace(go.Scatter(x=line_data['x'], y=line_data['y'], mode='lines', name='Regresyon',
                                                   line=dict(color='red', width=3)))

        update_polar_graph(figs[3], df_val)
        update_time_series_graph(figs[4], df_val)

        est_text = html.Div([html.P(estimate_geometric_shape(df_val), className="fw-bold"), html.Hr(),
                             html.P(find_clearest_path(df_val), className="fw-bold text-primary"), html.Hr(),
                             html.P(f"Kümeleme: {est_cart}"), html.Hr(), html.P(f"Regresyon: {est_polar}")])

    for i in range(5): add_sensor_position(figs[i]) if i != 0 else figs[i].add_trace(
        go.Scatter3d(x=[0], y=[0], z=[0], mode='markers', marker=dict(size=5, color='red'), name='Sensör'))

    titles = ['Ortamın 3D Haritası', '2D Harita (Üstten Görünüm)', 'Açıya Göre Mesafe Regresyonu', 'Polar Grafik',
              'Zaman Serisi - Mesafe']
    for i, fig in enumerate(figs): fig.update_layout(title_text=titles[i], uirevision=scan_id_for_revision,
                                                     legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                                                 xanchor="right", x=1),
                                                     margin=dict(l=40, r=40, t=80, b=40))
    figs[0].update_layout(
        scene=dict(xaxis_title='Y Ekseni (cm)', yaxis_title='X Ekseni (cm)', zaxis_title='Z Ekseni (cm)',
                   aspectmode='data'))
    figs[1].update_layout(xaxis_title="Yatay Mesafe (cm)", yaxis_title="Dikey Mesafe (cm)", yaxis_scaleanchor="x",
                          yaxis_scaleratio=1)
    figs[2].update_layout(xaxis_title="Tarama Açısı (Derece)", yaxis_title="Mesafe (cm)")

    return figs[0], figs[1], figs[2], figs[3], figs[4], est_text, store_data


@app.callback(
    [Output('container-map-graph-3d', 'style'), Output('container-map-graph', 'style'),
     Output('container-regression-graph', 'style'), Output('container-polar-graph', 'style'),
     Output('container-time-series-graph', 'style')],
    Input('graph-selector-dropdown', 'value')
)
def update_graph_visibility(selected_graph):
    styles = {'3d_map': {'display': 'none'}, 'map': {'display': 'none'}, 'regression': {'display': 'none'},
              'polar': {'display': 'none'}, 'time': {'display': 'none'}}
    if selected_graph in styles: styles[selected_graph] = {'display': 'block'}
    return styles['3d_map'], styles['map'], styles['regression'], styles['polar'], styles['time']


@app.callback(
    [Output("cluster-info-modal", "is_open"), Output("modal-title", "children"), Output("modal-body", "children")],
    [Input("scan-map-graph", "clickData")], [State("clustered-data-store", "data")], prevent_initial_call=True
)
def display_cluster_info(clickData, stored_data_json):
    if not clickData or not stored_data_json: return False, no_update, no_update
    try:
        df_clus = pd.read_json(stored_data_json, orient='split')
        cl_label = clickData["points"][0].get('customdata')
        if cl_label is None: return False, "Hata", "Küme etiketi alınamadı."
        if cl_label == -2:
            title, body = "Analiz Yok", "Bu nokta için küme analizi yapılamadı."
        elif cl_label == -1:
            title, body = "Gürültü Noktası", "Bu nokta bir nesne kümesine ait değil."
        else:
            cl_df_points = df_clus[df_clus['cluster'] == cl_label]
            n_pts, w_cl, d_cl = len(cl_df_points), cl_df_points['y_cm'].max() - cl_df_points['y_cm'].min(), \
                                                   cl_df_points['x_cm'].max() - cl_df_points['x_cm'].min()
            title = f"Küme #{int(cl_label)} Detayları"
            body = html.Div([html.P(f"Nokta Sayısı: {n_pts}"), html.P(f"Yaklaşık Genişlik (Y): {w_cl:.1f} cm"),
                             html.P(f"Yaklaşık Derinlik (X): {d_cl:.1f} cm")])
        return True, title, body
    except Exception as e:
        return True, "Hata", f"Küme bilgisi gösterilemedi: {e}"


@app.callback(
    [Output('ai-yorum-sonucu', 'children'),
     Output('ai-image', 'children')],
    Input('ai-model-dropdown', 'value'),
    prevent_initial_call=True
)
def yorumla_model_secimi(selected_config_id):
    """
    Seçilen AI yapılandırmasına göre ortam yorumlamasını yapar ve
    özel bir model ile resim oluşturur. Bu fonksiyon, önbelleği kontrol eder,
    gerekirse yeni analiz yapar ve sonucu veritabanına kaydeder.
    """
    # 1. Başlangıç Kontrolleri
    if not selected_config_id:
        return [html.P("Yorum için bir AI yapılandırması seçin."), None]

    if not DJANGO_MODELS_AVAILABLE:
        return [dbc.Alert("Veritabanı modellerine erişilemiyor. Lütfen sistem yapılandırmasını kontrol edin.",
                          color="danger"), None]

    scan = get_latest_scan()
    if not scan:
        return [dbc.Alert("Analiz edilecek bir tarama bulunamadı.", color="warning"), None]

    try:
        # 2. Metin Analizi
        # --------------------------------------------------------------------
        # Önce AI servisi için yapılandırmayı ve analizciyi hazırla
        config = AIModelConfiguration.objects.get(id=selected_config_id)
        analyzer = AIAnalyzerService(config=config)

        analysis_result_text = ""
        text_component = None

        # Önbelleği kontrol et: Eğer bu tarama için daha önce yapılmış bir yorum varsa, onu kullan.
        if scan.ai_commentary and scan.ai_commentary.strip():
            analysis_result_text = scan.ai_commentary
            text_component = dbc.Alert([
                html.H4("Önbellekten Yüklendi", className="alert-heading"),
                html.Hr(),
                dcc.Markdown(analysis_result_text, dangerously_allow_html=True)
            ], color="info")
            print("Metin analizi önbellekten yüklendi.")
        else:
            # Önbellekte yoksa yeni analiz yap
            print("Önbellekte yorum bulunamadı, yeni analiz yapılıyor...")
            prompt = (
                "Bu 3D tarama verilerini analiz et. Ortamın genel şekli nedir (oda, koridor vb.)? "
                "Belirgin nesneler var mı? Varsa, konumları ve olası şekilleri hakkında bilgi ver. "
                "Özellikle z_cm (yükseklik) verisini dikkate alarak yorum yap."
            )
            analysis_result_text = analyzer.analyze_model_data(
                django_model=ScanPoint, custom_prompt=prompt,
                fields=['derece', 'dikey_aci', 'mesafe_cm', 'x_cm', 'y_cm', 'z_cm'],
                scan=scan
            )
            # Yeni sonucu veritabanına kaydet
            if "hata" not in analysis_result_text.lower():
                scan.ai_commentary = analysis_result_text
                scan.save(update_fields=['ai_commentary'])
                print("Yeni metin analizi veritabanına kaydedildi.")

            text_component = dcc.Markdown(analysis_result_text, dangerously_allow_html=True)

        # 3. Resim Oluşturma
        # --------------------------------------------------------------------
        image_component = None  # Varsayılan olarak resim çıktısı boş

        # Sadece metin analizi başarılıysa resim oluşturmayı dene
        if analysis_result_text and "hata" not in analysis_result_text.lower():
            try:
                print("🖼️ Resim oluşturma işlemi başlatılıyor...")
                image_model_name = "gemini-2.0-flash-preview-image-generation"
                image_model = genai.GenerativeModel(image_model_name)

                image_prompt = (
                    "Aşağıdaki metin analizini temel alarak, taranan ortamın kuşbakışı şematik bir haritasını veya "
                    "3D render edilmiş bir görüntüsünü oluştur. Çıktıda sadece resim olsun.\n\n"
                    f"--- ANALİZ ---\n{analysis_result_text}"
                )

                generation_config = types.GenerationConfig(
                    response_mime_types=['image/png']
                )

                image_response = image_model.generate_content(
                    contents=image_prompt,
                    generation_config=generation_config
                )

                # Yanıtı işle ve resmi bul
                found_image = False
                if image_response.parts:
                    for part in image_response.parts:
                        if hasattr(part, 'inline_data') and part.inline_data.data:
                            print("✅ Resim verisi yanıtta bulundu.")
                            image_data = part.inline_data.data
                            mime_type = part.inline_data.mime_type

                            base64_image = base64.b64encode(image_data).decode('utf-8')
                            image_src = f"data:{mime_type};base64,{base64_image}"

                            image_component = html.Img(src=image_src, style={'maxWidth': '100%', 'borderRadius': '10px',
                                                                             'marginTop': '15px'})
                            found_image = True
                            break  # Resim bulununca döngüden çık

                if not found_image:
                    image_component = dbc.Alert("Model bir resim üretmedi. Modelin yanıtı resim verisi içermiyor.",
                                                color="warning", className="mt-3")
                    print(f"⚠️ Yanıt resim içermiyor.")

            except Exception as img_e:
                print(f"❌ Resim oluşturulurken hata oluştu: {img_e}")
                image_component = dbc.Alert(f"Resim oluşturulamadı: Model bulunamadı veya API hatası.", color="danger",
                                            className="mt-3")

        # 4. Sonuçları Döndür
        # --------------------------------------------------------------------
        return [text_component, image_component]

    except AIModelConfiguration.DoesNotExist:
        error_message = f"ID'si {selected_config_id} olan bir AI yapılandırması bulunamadı. Lütfen admin panelini kontrol edin."
        return [dbc.Alert(error_message, color="danger"), None]
    except Exception as e:
        import traceback
        error_message = f"Analiz sırasında beklenmedik bir genel hata oluştu: {e}"
        print(f"❌ Callback içinde genel hata: {e}")
        traceback.print_exc()
        return [dbc.Alert(error_message, color="danger"), None]