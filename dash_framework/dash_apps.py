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

SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'
SENSOR_SCRIPT_LOCK_FILE = '/tmp/sensor_scan_script.lock'
AUTONOMOUS_SCRIPT_LOCK_FILE = '/tmp/autonomous_drive_script.lock'

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
    """Verilen PID'ye sahip bir işlemin çalışıp çalışmadığını kontrol eder."""
    if pid is None:
        return False
    try:
        # psutil.pid_exists() en basit ve hızlı yoldur.
        return psutil.pid_exists(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except Exception as e:
        print(f"is_process_running içinde beklenmedik hata: {e}")
        return False


def stop_all_scripts():
    """
    Bilinen tüm betik PID dosyalarını kontrol eder ve çalışan işlemleri sonlandırır.
    Ayrıca ilgili .pid ve .lock dosyalarını temizler.
    """
    print("Tüm aktif betikler durduruluyor...")
    # Kontrol edilecek tüm bilinen PID dosyalarını bir listeye koyun
    all_pid_files = [SENSOR_SCRIPT_PID_FILE, AUTONOMOUS_SCRIPT_PID_FILE]

    for pid_file in all_pid_files:
        if os.path.exists(pid_file):
            pid_to_kill = None
            try:
                with open(pid_file, 'r') as f:
                    content = f.read().strip()
                    if content:  # Dosyanın boş olmadığından emin ol
                        pid_to_kill = int(content)

                if pid_to_kill and is_process_running(pid_to_kill):
                    print(f"Çalışan işlem bulundu (PID: {pid_to_kill}). Durdurma sinyali (SIGTERM) gönderiliyor...")
                    os.kill(pid_to_kill, signal.SIGTERM)
                else:
                    print(f"PID dosyasında ({pid_file}) belirtilen işlem (PID: {pid_to_kill}) zaten çalışmıyor.")

            except (IOError, ValueError) as e:
                print(f"PID dosyası ({pid_file}) okunurken veya işlenirken hata: {e}")
            except Exception as e:
                print(f"Bilinmeyen bir hata oluştu (PID: {pid_to_kill}): {e}")
            finally:
                # Her durumda PID ve ilişkili LOCK dosyasını silmeyi dene
                print(f"Temizlik: {pid_file} siliniyor...")
                try:
                    os.remove(pid_file)
                    lock_file = pid_file.replace('.pid', '.lock')
                    if os.path.exists(lock_file):
                        print(f"Temizlik: {lock_file} siliniyor...")
                        os.remove(lock_file)
                except OSError as e:
                    print(f"Dosya silme hatası: {e}")


def stop_current_operation(mode):
    """
    Mevcut işlemi durdurur. Hangi modda olursa olsun, bilinen tüm betikleri
    durdurarak sistemi temiz ve kararlı bir başlangıç durumuna getirir.

    Args:
        mode (str): Arayüzden gelen mevcut çalışma modu ('autonomous', 'mapping', vs.).
                     Bu parametre gelecekteki olası mod-spesifik temizlik işlemleri
                     için korunur, ancak mevcut mantık tüm modlar için aynıdır.

    Returns:
        tuple: Dash callback'i için butonların durumunu içeren bir demet.
               ("▶️ Başlat", False, True) -> Başlat butonu aktif, Durdur butonu pasif.
    """
    print(f"'{mode}' modu için durdurma talebi alındı. Genel durdurma prosedürü başlatılıyor.")

    # En güvenli yöntem, hangi modda olunduğuna bakmaksızın tüm betikleri durdurmaktır.
    # Bu, takılı kalmış veya unutulmuş işlemleri (orphaned processes) önler.
    stop_all_scripts()

    print("Durdurma işlemi tamamlandı. Arayüz başlangıç durumuna getiriliyor.")

    # Arayüzdeki butonları başlangıç durumuna geri döndür.
    return "▶️ Başlat", False, True


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
     State("scan-duration-angle-input", "value"),  # Haritalama parametreleri
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
    """Haritalama modunu başlatır"""
    try:
        # Önceki işlemleri durdur
        stop_all_scripts()

        # Parametreleri doğrula
        if not all(isinstance(i, (int, float)) for i in [h_angle, h_step, buzzer_dist]):
             print("Haritalama başlatma hatası: Parametreler geçersiz.")
             return "❌ Parametre Hatası", False, True # Arayüze hata mesajı

        # Komut satırı argümanlarını oluştur
        cmd = [
            sys.executable, SENSOR_SCRIPT_PATH,
            "--h-angle", str(h_angle),
            "--h-step", str(h_step),
            "--buzzer-distance", str(buzzer_dist)
            # Diğer gerekli parametreleri de buraya ekleyebilirsiniz (örn: steps-per-rev)
        ]

        # Betiği arka planda çalıştır
        subprocess.Popen(cmd,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)

        return "🔄 Haritalama Çalışıyor...", True, False

    except Exception as e:
        print(f"Haritalama başlatma hatası: {e}")
        return "❌ Başlatma Hatası", False, True


def start_manual_mode():
    """Manuel kontrol modunu başlatır"""
    return "🎮 Manuel Kontrol Aktif", True, False


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
        except (IOError, ValueError):
            pass
    if pid_to_kill and is_process_running(pid_to_kill):
        try:
            os.kill(pid_to_kill, signal.SIGTERM);
            time.sleep(1)
            if is_process_running(pid_to_kill): os.kill(pid_to_kill, signal.SIGKILL)
            msg, color = (f"Çalışan betik (PID:{pid_to_kill}) durduruldu.", "info")
        except Exception as e:
            msg, color = (f"Durdurma hatası: {e}", "danger")
    else:
        msg, color = ("Çalışan betik bulunamadı.", "warning")
    for fp in [SENSOR_SCRIPT_PID_FILE, SENSOR_SCRIPT_LOCK_FILE]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except:
                pass
    return dbc.Alert(msg, color=color)


@app.callback([Output('script-status', 'children'), Output('script-status', 'className'), Output('cpu-usage', 'value'),
               Output('cpu-usage', 'label'), Output('ram-usage', 'value'), Output('ram-usage', 'label')],
              Input('interval-component-system', 'n_intervals'))
def update_system_card(n):
    pid_val = None
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as pf:
                pid_val = int(pf.read().strip())
        except:
            pass
    status, s_class = (f"Çalışıyor (PID:{pid_val})", "text-success") if pid_val and is_process_running(pid_val) else (
        "Çalışmıyor", "text-danger")
    cpu, ram = psutil.cpu_percent(interval=0.1), psutil.virtual_memory().percent
    return status, s_class, cpu, f"{cpu:.1f}%", ram, f"{ram:.1f}%"


@app.callback(
    [Output('current-angle', 'children'), Output('current-distance', 'children'), Output('current-speed', 'children'),
     Output('current-distance-col', 'style'), Output('max-detected-distance', 'children')],
    [Input('latest-scan-object-store', 'data'),
     Input('latest-scan-points-store', 'data')]
)
def update_realtime_values(scan_json, points_json):
    style = {'padding': '10px', 'transition': 'background-color 0.5s ease', 'borderRadius': '5px'}
    if not scan_json or not points_json:
        return "--°", "-- cm", "-- cm/s", style, "-- cm"

    scan = json.loads(scan_json)
    df = pd.read_json(points_json, orient='split')

    if df.empty:
        return "--°", "-- cm", "-- cm/s", style, "-- cm"

    point = df.sort_values(by='id', ascending=False).iloc[0]
    angle = f"{point.get('derece', 0.0):.1f}°"
    dist = f"{point.get('mesafe_cm', 0.0):.1f} cm"
    speed = f"{point.get('hiz_cm_s', 0.0):.1f} cm/s"

    buzzer_dist = scan.get('buzzer_distance_setting')
    if buzzer_dist is not None and 0 < point['mesafe_cm'] <= buzzer_dist:
        style.update({'backgroundColor': '#d9534f', 'color': 'white'})

    df_valid = df[(df['mesafe_cm'] < 2500) & (df['mesafe_cm'] > 0)]
    max_dist_val = df_valid['mesafe_cm'].max() if not df_valid.empty else None
    max_dist = f"{max_dist_val:.1f} cm" if pd.notnull(max_dist_val) else "-- cm"

    return angle, dist, speed, style, max_dist


@app.callback(
    [Output('calculated-area', 'children'), Output('perimeter-length', 'children'), Output('max-width', 'children'),
     Output('max-depth', 'children')],
    Input('latest-scan-object-store', 'data')
)
def update_analysis_panel(scan_json):
    if not scan_json: return "-- cm²", "-- cm", "-- cm", "-- cm"
    scan = json.loads(scan_json)
    area = f"{scan.get('calculated_area_cm2', 0.0):.2f} cm²" if scan.get('calculated_area_cm2') is not None else "N/A"
    perim = f"{scan.get('perimeter_cm', 0.0):.2f} cm" if scan.get('perimeter_cm') is not None else "N/A"
    width = f"{scan.get('max_width_cm', 0.0):.2f} cm" if scan.get('max_width_cm') is not None else "N/A"
    depth = f"{scan.get('max_depth_cm', 0.0):.2f} cm" if scan.get('max_depth_cm') is not None else "N/A"
    return area, perim, width, depth


@app.callback(Output('download-csv', 'data'), Input('export-csv-button', 'n_clicks'), prevent_initial_call=True)
def export_csv_callback(n_clicks):
    scan = get_latest_scan()
    if not (scan and scan.points.exists()): return dcc.send_data_frame(pd.DataFrame().to_csv, "veri_yok.csv",
                                                                       index=False)
    df = pd.DataFrame(list(scan.points.all().values()))
    return dcc.send_data_frame(df.to_csv, f"tarama_id_{scan.id}.csv", index=False)


# GÜNCELLENDİ: EXCEL AKTARIMI DAHA OKUNAKLI HALE GETİRİLDİ
@app.callback(Output('download-excel', 'data'), Input('export-excel-button', 'n_clicks'), prevent_initial_call=True)
def export_excel_callback(n_clicks):
    from scanner.models import Scan
    scan = get_latest_scan()
    if not scan:
        return dcc.send_bytes(b"", "tarama_yok.xlsx")
    buf = io.BytesIO()
    try:
        scan_info_df = pd.DataFrame([Scan.objects.filter(id=scan.id).values().first()])
        points_df = pd.DataFrame(list(scan.points.all().values()))

        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            # Sayfa 1: Tarama Bilgileri
            scan_info_df.to_excel(writer, sheet_name=f'Scan_{scan.id}_Info', index=False)
            info_sheet = writer.sheets[f'Scan_{scan.id}_Info']
            info_sheet.autofit()

            # Sayfa 2: Nokta Verileri (varsa)
            if not points_df.empty:
                points_df.to_excel(writer, sheet_name=f'Scan_{scan.id}_Points', index=False)
                # Biçimlendirme
                workbook = writer.book
                points_sheet = writer.sheets[f'Scan_{scan.id}_Points']
                header_format = workbook.add_format({
                    'bold': True, 'text_wrap': False, 'valign': 'vcenter',
                    'fg_color': '#4F81BD', 'font_color': 'white', 'border': 1
                })
                # Başlıkları formatla yazdır
                for col_num, value in enumerate(points_df.columns.values):
                    points_sheet.write(0, col_num, value, header_format)
                # Sütunları otomatik ayarla
                points_sheet.autofit()

    except Exception as e:
        buf.seek(0);
        buf.truncate();
        pd.DataFrame([{"Hata": str(e)}]).to_excel(buf, sheet_name='Hata', index=False)

    buf.seek(0)
    return dcc.send_bytes(buf.getvalue(), f"tarama_detaylari_id_{scan.id}.xlsx")


@app.callback(
    Output('tab-content-datatable', 'children'),
    [Input('visualization-tabs-main', 'active_tab'),
     Input('latest-scan-points-store', 'data')]
)
def render_and_update_data_table(active_tab, points_json):
    if active_tab != "tab-datatable" or not points_json:
        return html.P("Görüntülenecek veri yok.") if active_tab == "tab-datatable" else None

    df = pd.read_json(points_json, orient='split')
    df = df[['id', 'derece', 'dikey_aci', 'mesafe_cm', 'hiz_cm_s', 'x_cm', 'y_cm', 'z_cm', 'timestamp']]

    return dash_table.DataTable(data=df.to_dict('records'),
                                columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                page_size=50, sort_action="native", filter_action="native", virtualization=True,
                                fixed_rows={'headers': True}, style_table={'minHeight': '70vh', 'overflowY': 'auto'})


@app.callback(
    [Output('scan-map-graph-3d', 'figure'), Output('scan-map-graph', 'figure'),
     Output('polar-regression-graph', 'figure'), Output('polar-graph', 'figure'),
     Output('time-series-graph', 'figure'), Output('environment-estimation-text', 'children'),
     Output('clustered-data-store', 'data')],
    [Input('latest-scan-object-store', 'data'),
     Input('latest-scan-points-store', 'data')]
)
def update_all_graphs(scan_json, points_json):
    empty_fig = go.Figure(layout={'title': 'Veri Bekleniyor...'})
    if not scan_json or not points_json:
        return empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, "Tarama başlatın...", None

    scan = json.loads(scan_json)
    df_pts = pd.read_json(points_json, orient='split')
    figs = [go.Figure() for _ in range(5)]
    scan_id_for_revision = str(scan.get('id'))

    no_data_fig = go.Figure(layout={'title': f'Tarama #{scan_id_for_revision} için nokta verisi yok'})
    if df_pts.empty:
        return no_data_fig, no_data_fig, no_data_fig, no_data_fig, no_data_fig, "Nokta verisi bulunamadı.", None

    df_val = df_pts[(df_pts['mesafe_cm'] > 0.1) & (df_pts['mesafe_cm'] < 400.0)].copy()

    if not df_val.empty:
        figs[0].add_trace(go.Scatter3d(x=df_val['y_cm'], y=df_val['x_cm'], z=df_val['z_cm'], mode='markers',
                                       marker=dict(size=2, color=df_val['z_cm'], colorscale='Viridis', showscale=True,
                                                   colorbar_title='Yükseklik (cm)')))

    est_text, store_data = "Analiz için yetersiz veri.", None
    if len(df_val) >= 10:
        est_cart, df_clus = analyze_environment_shape(figs[1], df_val.copy())
        store_data = df_clus.to_json(orient='split')
        add_scan_rays(figs[1], df_val);
        add_sector_area(figs[1], df_val)
        line_data, est_polar = analyze_polar_regression(df_val)
        figs[2].add_trace(go.Scatter(x=df_val['derece'], y=df_val['mesafe_cm'], mode='markers', name='Noktalar'))
        if line_data: figs[2].add_trace(go.Scatter(x=line_data['x'], y=line_data['y'], mode='lines', name='Regresyon',
                                                   line=dict(color='red', width=3)))
        update_polar_graph(figs[3], df_val)
        df_val['timestamp'] = pd.to_datetime(df_val['timestamp'])
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
    styles = {'display': 'none'}
    if selected_graph == '3d_map': return {'display': 'block'}, styles, styles, styles, styles
    if selected_graph == 'map': return styles, {'display': 'block'}, styles, styles, styles
    if selected_graph == 'regression': return styles, styles, {'display': 'block'}, styles, styles
    if selected_graph == 'polar': return styles, styles, styles, {'display': 'block'}, styles
    if selected_graph == 'time': return styles, styles, styles, styles, {'display': 'block'}
    return [styles] * 5


@app.callback(
    [Output("cluster-info-modal", "is_open"), Output("modal-title", "children"), Output("modal-body", "children")],
    Input("scan-map-graph", "clickData"), State("clustered-data-store", "data"), prevent_initial_call=True
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
            cl_df = df_clus[df_clus['cluster'] == cl_label]
            w, d = cl_df['y_cm'].max() - cl_df['y_cm'].min(), cl_df['x_cm'].max() - cl_df['x_cm'].min()
            title = f"Küme #{int(cl_label)} Detayları"
            body = html.Div([html.P(f"Nokta Sayısı: {len(cl_df)}"), html.P(f"Yaklaşık Genişlik: {w:.1f} cm"),
                             html.P(f"Yaklaşık Derinlik: {d:.1f} cm")])
        return True, title, body
    except Exception as e:
        return True, "Hata", f"Küme bilgisi gösterilemedi: {e}"


# GÜNCELLENDİ: AI PROMPT'U DAHA DETAYLI HALE GETİRİLDİ
@app.callback(
    [Output('ai-yorum-sonucu', 'children'), Output('ai-image', 'children')],
    Input('ai-model-dropdown', 'value'),
    prevent_initial_call=True
)
def yorumla_model_secimi(selected_config_id):
    from scanner.models import Scan, ScanPoint, AIModelConfiguration
    from scanner.ai_analyzer import AIAnalyzerService

    if not selected_config_id:
        return [html.P("Yorum için bir AI yapılandırması seçin."), None]

    try:
        scan = get_latest_scan()
        if not scan:
            return [dbc.Alert("Analiz edilecek bir tarama bulunamadı.", color="warning"), None]

        config = AIModelConfiguration.objects.get(id=selected_config_id)
        analyzer = AIAnalyzerService(config=config)

        # Metin Analizi
        analysis_result_text, text_component = "", None
        if scan.ai_commentary and scan.ai_commentary.strip():
            analysis_result_text = scan.ai_commentary
            text_component = dbc.Alert([html.H4("Önbellekten Yüklendi", className="alert-heading"), html.Hr(),
                                        dcc.Markdown(analysis_result_text, dangerously_allow_html=True)], color="info")
        else:
            prompt = (
                "Bu 3D tarama verilerini analiz et. Ortamın genel şekli nedir (oda, koridor vb.)? Belirgin nesneler var mı? Varsa, konumları ve olası şekilleri hakkında bilgi ver. Özellikle z_cm (yükseklik) verisini dikkate alarak yorum yap.")
            analysis_result_text = analyzer.analyze_model_data(django_model=ScanPoint, custom_prompt=prompt,
                                                               fields=['derece', 'dikey_aci', 'mesafe_cm', 'x_cm',
                                                                       'y_cm', 'z_cm'], scan=scan)
            if "hata" not in analysis_result_text.lower():
                scan.ai_commentary = analysis_result_text;
                scan.save(update_fields=['ai_commentary'])
            text_component = dcc.Markdown(analysis_result_text, dangerously_allow_html=True)

        # Resim Oluşturma
        image_component = None
        if analysis_result_text and "hata" not in analysis_result_text.lower():
            try:
                image_model = genai.GenerativeModel("gemini-1.5-flash-latest")
                # Daha detaylı prompt ile daha iyi sonuçlar hedefleniyor
                image_prompt = (
                    f"Aşağıdaki 3D tarama analizini temel alarak, taranan ortamın birinci şahıs bakış açısıyla (FPS view), "
                    f"sinematik ışıklandırmaya sahip, fotogerçekçi bir 3D render görüntüsünü oluştur. "
                    f"Görüntüde insanlar veya hareketli nesneler yer almasın. Ortamın dokularını ve geometrisini vurgula. "
                    f"Analiz metni: {analysis_result_text}"
                )
                image_response = image_model.generate_content(image_prompt,
                                                              generation_config={"response_mime_type": "image/png"})

                if image_response.parts:
                    part = image_response.parts[0]
                    image_data = part.inline_data.data
                    mime_type = part.inline_data.mime_type
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    image_src = f"data:{mime_type};base64,{base64_image}"
                    image_component = html.Img(src=image_src,
                                               style={'maxWidth': '100%', 'borderRadius': '10px', 'marginTop': '15px'})
                else:
                    image_component = dbc.Alert("Model bir resim üretmedi.", color="warning", className="mt-3")
            except Exception as img_e:
                image_component = dbc.Alert(f"Resim oluşturulamadı: {img_e}", color="danger", className="mt-3")

        return [text_component, image_component]

    except AIModelConfiguration.DoesNotExist:
        return [dbc.Alert(f"ID'si {selected_config_id} olan AI yapılandırması bulunamadı.", color="danger"), None]
    except Exception as e:
        traceback.print_exc()
        return [dbc.Alert(f"Analiz sırasında genel hata: {e}", color="danger"), None]
