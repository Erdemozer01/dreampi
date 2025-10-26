import atexit
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
from scipy.spatial import ConvexHull, QhullError
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
try:
    import google.generativeai as genai
except ImportError:
    genai = None
from dotenv import load_dotenv
import dash

load_dotenv()

# --- SABİTLER VE UYGULAMA BAŞLATMA ---
SENSOR_SCRIPT_FILENAME = 'sensor_script.py'
SENSOR_SCRIPT_PATH = os.path.join(os.getcwd(), SENSOR_SCRIPT_FILENAME)
AUTONOMOUS_SCRIPT_FILENAME = 'autonomous_drive_pi5.py'
AUTONOMOUS_SCRIPT_PATH = os.path.join(os.getcwd(), AUTONOMOUS_SCRIPT_FILENAME)

SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'
AUTONOMOUS_SCRIPT_PID_FILE = '/tmp/autonomous_drive_script.pid'

FONT_AWESOME = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"

app = DjangoDash(
    'DreamPi',
    external_stylesheets=[dbc.themes.BOOTSTRAP, FONT_AWESOME]
)

# --- NAVBAR ---
navbar = dbc.NavbarSimple(
    children=[dbc.NavItem(dbc.NavLink("Admin Paneli", href="/admin/", external_link=True, target="_blank"))],
    brand="Dream Pi", brand_href="/", color="primary", dark=True, sticky="top", fluid=True, className="mb-4"
)


# --- YARDIMCI FONKSİYONLAR ---
def is_process_running(pid):
    """PID'nin çalışıp çalışmadığını kontrol et"""
    if pid is None:
        return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def get_ai_model_options():
    """Aktif AI modellerini listele"""
    try:
        from scanner.models import AIModelConfiguration
        configs = AIModelConfiguration.objects.filter(is_active=True).order_by('name')
        if not configs.exists():
            return [{'label': 'Aktif AI Modeli Yok', 'value': '', 'disabled': True}]
        return [{'label': config.name, 'value': config.id} for config in configs]
    except Exception:
        return [{'label': 'DB Hatası', 'value': '', 'disabled': True}]


def get_latest_scan():
    """En son taramayı getir"""
    try:
        from scanner.models import Scan
        running_scan = Scan.objects.filter(status='RUN').order_by('-start_time').first()
        if running_scan:
            return running_scan
        return Scan.objects.order_by('-start_time').first()
    except Exception:
        return None


def stop_all_scripts():
    """Bilinen tüm betik PID dosyalarını kontrol eder ve çalışan işlemleri sonlandırır"""
    print("Tüm aktif betikler durduruluyor...")
    all_pid_files = [SENSOR_SCRIPT_PID_FILE, AUTONOMOUS_SCRIPT_PID_FILE]

    for pid_file in all_pid_files:
        if os.path.exists(pid_file):
            pid_to_kill = None
            try:
                with open(pid_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        pid_to_kill = int(content)

                if pid_to_kill and is_process_running(pid_to_kill):
                    print(f"Çalışan işlem bulundu (PID: {pid_to_kill}). Durduruluyor...")
                    os.kill(pid_to_kill, signal.SIGTERM)
                    time.sleep(0.5)
            except (IOError, ValueError, ProcessLookupError, Exception) as e:
                print(f"PID dosyası işlenirken hata: {e}")
            finally:
                if os.path.exists(pid_file):
                    try:
                        os.remove(pid_file)
                    except OSError:
                        pass


atexit.register(stop_all_scripts)


def stop_current_operation(mode):
    """Mevcut operasyonu durdur"""
    stop_all_scripts()
    return (
        html.Span([html.I(className="fa-solid fa-play me-2"), "Başlat"]),
        False,  # start-button enabled
        True,  # stop-button disabled
        True  # interval disabled
    )


def start_mapping_mode(h_angle, h_step, v_angle, v_step, buzzer_dist):
    """Haritalama modunu başlat"""
    try:
        stop_all_scripts()
        time.sleep(0.5)  # Önceki scriptin tamamen durması için

        cmd = [
            sys.executable, SENSOR_SCRIPT_PATH,
            "--h-angle", str(h_angle),
            "--h-step", str(h_step),
            "--v-angle", str(v_angle),
            "--v-step", str(v_step),
            "--buzzer-distance", str(buzzer_dist)
        ]

        log_file = open("sensor_script_live.log", "w")
        subprocess.Popen(cmd, stdout=log_file, stderr=log_file, start_new_session=True)

        return (
            html.Span([html.I(className="fa-solid fa-spinner fa-spin me-2"), "Haritalama..."]),
            True,  # start-button disabled
            False,  # stop-button enabled
            False  # interval enabled
        )
    except Exception as e:
        print(f"Haritalama başlatma hatası: {e}")
        return (
            html.Span([html.I(className="fa-solid fa-xmark me-2"), "Hata"]),
            False, True, True
        )


def start_autonomous_mode():
    """Otonom sürüşü başlat"""
    try:
        stop_all_scripts()
        time.sleep(0.5)  # Önceki scriptin tamamen durması için

        # Script kendi scan'ını oluşturacak
        cmd = [sys.executable, AUTONOMOUS_SCRIPT_PATH]
        log_file = open("autonomous_drive_live.log", "w")
        subprocess.Popen(cmd, stdout=log_file, stderr=log_file, start_new_session=True)

        return (
            html.Span([html.I(className="fa-solid fa-robot fa-spin me-2"), "Otonom Sürüş..."]),
            True,  # start-button disabled
            False,  # stop-button enabled
            False  # interval enabled
        )
    except Exception as e:
        logging.error(f"Otonom sürüş başlatma hatası: {e}")
        return (
            html.Span([html.I(className="fa-solid fa-xmark me-2"), "Hata"]),
            False, True, True
        )


def analyze_environment_shape(fig, df_valid_input):
    """Çevre şeklini analiz et ve kümelere ayır"""
    df_valid = df_valid_input.copy()
    if len(df_valid) < 10:
        df_valid.loc[:, 'cluster'] = -2
        return "Analiz için yetersiz veri.", df_valid

    try:
        points_all = df_valid[['y_cm', 'x_cm']].to_numpy()
        db = DBSCAN(eps=15, min_samples=3).fit(points_all)
        df_valid.loc[:, 'cluster'] = db.labels_

        unique_clusters = sorted(list(set(db.labels_)))
        num_actual_clusters = len(unique_clusters) - (1 if -1 in unique_clusters else 0)

        desc = f"{num_actual_clusters} potansiyel nesne kümesi bulundu." if num_actual_clusters > 0 else "Belirgin bir nesne kümesi bulunamadı."
        colors = plt.cm.get_cmap('viridis', num_actual_clusters if num_actual_clusters > 0 else 1)

        for k in unique_clusters:
            cluster_points_df = df_valid[df_valid['cluster'] == k]
            if cluster_points_df.empty:
                continue

            points = cluster_points_df[['y_cm', 'x_cm']].to_numpy()

            if k == -1:
                c, s, n = 'rgba(128,128,128,0.3)', 5, 'Gürültü/Diğer'
            else:
                norm_k = (k / (num_actual_clusters - 1)) if num_actual_clusters > 1 else 0.0
                rc = colors(np.clip(norm_k, 0.0, 1.0))
                c = f'rgba({rc[0] * 255:.0f},{rc[1] * 255:.0f},{rc[2] * 255:.0f},0.9)'
                s, n = 8, f'Küme {k}'

            fig.add_trace(
                go.Scatter(
                    x=points[:, 0],
                    y=points[:, 1],
                    mode='markers',
                    marker=dict(color=c, size=s),
                    name=n,
                    customdata=[k] * len(points)
                )
            )

        return desc, df_valid
    except Exception as e:
        df_valid.loc[:, 'cluster'] = -2
        return f"DBSCAN kümeleme hatası: {e}", df_valid


def estimate_geometric_shape(df):
    """Geometrik şekil tahmini"""
    if len(df) < 15:
        return "Şekil tahmini için yetersiz nokta."

    try:
        hull = ConvexHull(df[['y_cm', 'x_cm']].values)
        width = df['y_cm'].max() - df['y_cm'].min()
        depth = df['x_cm'].max()

        if width < 1 or depth < 1:
            return "Algılanan şekil çok küçük."

        fill_factor = hull.volume / (depth * width) if (depth * width) > 0 else 0
        aspect_ratio = width / depth if depth > 0 else 0

        if depth > 150 and aspect_ratio < 0.4:
            return f"Dar ve Derin Boşluk (Genişlik: {width:.1f}cm, Derinlik: {depth:.1f}cm)"
        if fill_factor > 0.7 and 0.8 < aspect_ratio < 1.2:
            return f"Kutu/Dairesel Nesne (Doluluk: %{fill_factor * 100:.0f})"
        if aspect_ratio > 2.5:
            return f"Geniş Yüzey/Duvar (Genişlik: {width:.1f}cm)"
        if fill_factor < 0.4:
            return "İçbükey Yapı veya Dağınık Nesneler"

        return "Düzensiz veya Karmaşık Yapı"
    except (QhullError, ValueError) as e:
        return f"Geometrik analiz hatası: {e}"


def classify_environment_and_get_report(df):
    """Ortam türünü (iç/dış mekan) ve ilgili analiz raporunu döndürür"""
    if df.empty or len(df) < 15:
        return 'unknown', html.Div("Analiz için yetersiz veri.")

    max_distance = df['mesafe_cm'].max()
    std_dev_distance = df['mesafe_cm'].std()

    if max_distance > 380 and std_dev_distance > 100:
        env_type, env_key = "Açık Alan", "outdoor"
        suggestion = " (Ağaç, bina yüzeyi gibi büyük nesneler beklenir)"
    else:
        env_type, env_key = "Kapalı Alan", "indoor"
        suggestion = " (Duvar, masa, sandalye gibi nesneler beklenir)"

    geometric_estimation = estimate_geometric_shape(df)

    report = dbc.ListGroup([
        dbc.ListGroupItem(
            [html.I(className="fa-solid fa-mountain-sun me-2"), f"Ortam Tahmini: {env_type}"],
            className="d-flex align-items-center"
        ),
        dbc.ListGroupItem(
            [html.I(className="fa-solid fa-ruler-combined me-2"), f"Geometri: {geometric_estimation}"],
            className="d-flex align-items-center"
        ),
        dbc.ListGroupItem(
            [html.I(className="fa-solid fa-lightbulb me-2"), html.Small(suggestion, className="text-muted fst-italic")],
            className="d-flex align-items-center"
        ),
    ], flush=True)

    return env_key, report


# --- ARAYÜZ BİLEŞENLERİ (LAYOUT) ---
control_panel = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-gears me-2"), "Sistem Kontrolü"]),
    dbc.CardBody([
        dbc.Row([dbc.Col([
            html.Label([html.I(className="fa-solid fa-compass me-2"), "Çalışma Modu:"], className="fw-bold mb-2"),
            dcc.RadioItems(
                id='operation-mode',
                options=[
                    {'label': html.Span([html.I(className="fa-solid fa-map-location-dot me-2"), " Haritalama Modu"]),
                     'value': 'mapping'},
                    {'label': html.Span([html.I(className="fa-solid fa-robot me-2"), " Otonom Sürüş Modu"]),
                     'value': 'autonomous'},
                    {'label': html.Span([html.I(className="fa-solid fa-gamepad me-2"), " Manuel Kontrol"]),
                     'value': 'manual', 'disabled': True}
                ],
                value='mapping',
                labelStyle={'display': 'block', 'margin': '5px 0'},
                className="mb-3"
            )
        ])]),

        # Haritalama parametreleri
        html.Div(id='mapping-parameters', children=[
            dbc.Row([
                dbc.Col([
                    html.Label([html.I(className="fa-solid fa-arrows-left-right me-2"), "Yatay Tarama Açısı (°):"],
                               className="fw-bold"),
                    dbc.Input(id='h-scan-angle-input', type='number', value=360.0, step=10)
                ], width=6),
                dbc.Col([
                    html.Label([html.I(className="fa-solid fa-shoe-prints me-2"), "Yatay Adım Açısı (°):"],
                               className="fw-bold"),
                    dbc.Input(id='h-step-angle-input', type='number', value=20.0, step=1)
                ], width=6)
            ], className="mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Label([html.I(className="fa-solid fa-arrows-up-down me-2"), "Dikey Tarama Açısı (°):"],
                               className="fw-bold"),
                    dbc.Input(id='v-scan-angle-input', type='number', value=360.0, step=10)
                ], width=6),
                dbc.Col([
                    html.Label([html.I(className="fa-solid fa-shoe-prints fa-rotate-90 me-2"), "Dikey Adım Açısı (°):"],
                               className="fw-bold"),
                    dbc.Input(id='v-step-angle-input', type='number', value=20.0, step=1)
                ], width=6)
            ], className="mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Label([html.I(className="fa-solid fa-volume-high me-2"), "Buzzer Mesafesi (cm):"],
                               className="fw-bold"),
                    dbc.Input(id='buzzer-distance-input', type='number', value=15)
                ], width=6)
            ], className="mb-3")
        ]),

        # Kontrol butonları
        dbc.Row([
            dbc.Col(
                dbc.ButtonGroup([
                    dbc.Button(
                        [html.I(className="fa-solid fa-play me-2"), "Başlat"],
                        id="start-button",
                        color="success",
                        size="lg",
                        className="me-2"
                    ),
                    dbc.Button(
                        [html.I(className="fa-solid fa-stop me-2"), "Durdur"],
                        id="stop-button",
                        color="danger",
                        size="lg",
                        disabled=True
                    )
                ]),
                width=12,
                className="text-center"
            )
        ])
    ])
])

stats_panel = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-gauge-simple me-2"), "Anlık Sensör Değerleri"]),
    dbc.CardBody(
        dbc.Row([
            dbc.Col(
                html.Div([html.H6("Mevcut Açı:"), html.H4(id='current-angle', children="--°")]),
                width=3, className="text-center border-end"
            ),
            dbc.Col(
                html.Div([html.H6("Mevcut Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
                id='current-distance-col', width=3, className="text-center border-end"
            ),
            dbc.Col(
                html.Div([html.H6("Anlık Hız:"), html.H4(id='current-speed', children="-- cm/s")]),
                width=3, className="text-center border-end"
            ),
            dbc.Col(
                html.Div([html.H6("Max Mesafe:"), html.H4(id='max-detected-distance', children="-- cm")]),
                width=3, className="text-center"
            )
        ])
    )
], className="mb-3")

system_card = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-microchip me-2"), "Sistem Durumu"]),
    dbc.CardBody([
        dbc.Row([
            dbc.Col(html.Div([
                html.H6("Çalışan Betikler:"),
                html.H5(id='script-status', children="Beklemede")
            ]))
        ], className="mb-2"),
        dbc.Row([
            dbc.Col(html.Div([
                html.H6("CPU Kullanımı:"),
                dbc.Progress(id='cpu-usage', value=0, color="success", style={"height": "20px"}, label="0%")
            ])),
            dbc.Col(html.Div([
                html.H6("RAM Kullanımı:"),
                dbc.Progress(id='ram-usage', value=0, color="info", style={"height": "20px"}, label="0%")
            ]))
        ])
    ])
], className="mb-3")

export_card = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-download me-2"), "Veri Dışa Aktarma"]),
    dbc.CardBody([
        dbc.Button('CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
        dcc.Download(id='download-csv'),
        dbc.Button('Excel İndir', id='export-excel-button', color="success", className="w-100"),
        dcc.Download(id='download-excel')
    ])
], className="mb-3")

analysis_card = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-calculator me-2"), "Tarama Analizi"]),
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
    dbc.CardHeader([html.I(className="fa-solid fa-lightbulb me-2"), "Akıllı Ortam Analizi"]),
    dbc.CardBody(
        html.Div("Tahmin: Bekleniyor...", id='environment-estimation-text', className="text-center")
    )
])

visualization_tabs = dbc.Tabs([
    dbc.Tab(
        dcc.Graph(id='scan-map-graph-3d', style={'height': '75vh'}, config={'displayModeBar': True}),
        label="3D Harita",
        tab_id="tab-3d"
    ),
    dbc.Tab(
        dcc.Graph(id='scan-map-graph-2d', style={'height': '75vh'}),
        label="2D Harita",
        tab_id="tab-2d"
    ),
    dbc.Tab(
        dcc.Graph(id='polar-graph', style={'height': '75vh'}),
        label="Polar Grafik",
        tab_id="tab-polar"
    ),
    dbc.Tab(
        dcc.Loading(children=[html.Div(id='tab-content-datatable')]),
        label="Veri Tablosu",
        tab_id="tab-datatable"
    )
], id="visualization-tabs-main", active_tab="tab-3d")

navigation_status_card = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-location-crosshairs me-2"), "Navigasyon Durumu"]),
    dbc.CardBody([
        html.Div(id='navigation-status-text', children=[
            html.P("Hedefe gitme için 3D haritada bir noktaya tıklayın", className="text-muted text-center")
        ]),
        html.Div(id='target-coordinates', children="", className="text-center mt-2")
    ])
], className="mb-3")

ai_card = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-wand-magic-sparkles me-2"), "Akıllı Yorumlama (Yapay Zeka)"]),
    dbc.CardBody([
        dcc.Dropdown(id='ai-model-dropdown', placeholder="Analiz için bir AI modeli seçin...", className="mb-3"),
        dcc.Loading(
            id="loading-ai-comment",
            children=[
                html.Div(
                    id='ai-yorum-sonucu',
                    children=[html.P("Yorum almak için yukarıdan bir AI yapılandırması seçin.")],
                    className="text-center mt-2"
                ),
                html.Div(id='ai-image', className="text-center mt-3")
            ]
        )
    ])
], className="mt-3")

# --- ANA UYGULAMA YERLEŞİMİ ---
app.layout = html.Div(style={'padding': '20px'}, children=[
    navbar,
    dbc.Row([
        dbc.Col([
            control_panel,
            html.Br(),
            stats_panel,
            navigation_status_card,
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
            html.Br(),
            ai_card
        ], md=8)
    ]),
    dcc.Store(id='latest-scan-object-store'),
    dcc.Store(id='latest-scan-points-store'),
    dcc.Store(id='clustered-data-store'),
    dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0, disabled=True),
    dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0),
    dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(id="modal-title")),
            dbc.ModalBody(id="modal-body")
        ],
        id="cluster-info-modal",
        is_open=False,
        centered=True
    ),
    html.Div(id='dummy-clientside-output', style={'display': 'none'})
])


# --- CALLBACK FONKSİYONLARI ---

# 1. Periyodik Veri Çekme
@app.callback(
    [Output('latest-scan-object-store', 'data'),
     Output('latest-scan-points-store', 'data')],
    Input('interval-component-main', 'n_intervals')
)
def update_data_stores(n):
    """Veritabanından en son taramayı çek"""
    from django.forms.models import model_to_dict
    try:
        scan = get_latest_scan()
        if not scan:
            return no_update, no_update

        scan_json = json.dumps(model_to_dict(scan), default=str)

        points_qs = scan.points.all().values(
            'id', 'x_cm', 'y_cm', 'z_cm', 'derece', 'dikey_aci', 'mesafe_cm', 'hiz_cm_s', 'timestamp'
        )

        if not points_qs.exists():
            return scan_json, None

        df_pts = pd.DataFrame(list(points_qs))
        df_pts['timestamp'] = pd.to_datetime(df_pts['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        points_json = df_pts.to_json(orient='split')

        return scan_json, points_json
    except Exception as e:
        print(f"HATA: Merkezi veri deposu güncellenemedi: {e}")
        return None, None


# 2. Parametre Görünürlüğü
@app.callback(
    Output('mapping-parameters', 'style'),
    Input('operation-mode', 'value')
)
def toggle_mode_parameters(selected_mode):
    """Haritalama parametrelerini sadece haritalama modunda göster"""
    return {'display': 'block'} if selected_mode == 'mapping' else {'display': 'none'}


# 3. Başlat/Durdur Butonları
@app.callback(
    [Output("start-button", "children"),
     Output("start-button", "disabled"),
     Output("stop-button", "disabled"),
     Output("interval-component-main", "disabled")],
    [Input("start-button", "n_clicks"),
     Input("stop-button", "n_clicks")],
    [State("operation-mode", "value"),
     State("h-scan-angle-input", "value"),
     State("h-step-angle-input", "value"),
     State("v-scan-angle-input", "value"),
     State("v-step-angle-input", "value"),
     State("buzzer-distance-input", "value")]
)
def handle_start_stop_operations(start_clicks, stop_clicks, mode, h_angle, h_step, v_angle, v_step, buzzer_dist):
    """Başlat/Durdur butonlarını yönet"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "start-button":
        if mode == 'mapping':
            return start_mapping_mode(h_angle, h_step, v_angle, v_step, buzzer_dist)
        elif mode == 'autonomous':
            return start_autonomous_mode()
    elif button_id == "stop-button":
        return stop_current_operation(mode)

    return no_update, no_update, no_update, no_update


# 4. AI Modeli Dropdown
@app.callback(
    [Output('ai-model-dropdown', 'options'),
     Output('ai-model-dropdown', 'disabled'),
     Output('ai-model-dropdown', 'placeholder')],
    Input('interval-component-main', 'n_intervals')
)
def populate_ai_model_dropdown(n):
    """AI model listesini doldur"""
    if n > 0:
        raise PreventUpdate

    options = get_ai_model_options()
    if options and not options[0].get('disabled'):
        return options, False, "Analiz için bir AI modeli seçin..."
    return [], True, "Aktif AI Modeli Bulunamadı"


# 5. Sistem Durum Kartı (DÜZELTİLMİŞ - Çoklu Script Desteği)
@app.callback(
    [Output('script-status', 'children'),
     Output('script-status', 'className'),
     Output('cpu-usage', 'value'),
     Output('cpu-usage', 'label'),
     Output('ram-usage', 'value'),
     Output('ram-usage', 'label')],
    Input('interval-component-system', 'n_intervals')
)
def update_system_card(n):
    """Sistem durumunu güncelle - tüm çalışan scriptleri göster"""
    running_scripts = []

    # Haritalama scripti kontrol
    if os.path.exists(SENSOR_SCRIPT_PID_FILE):
        try:
            with open(SENSOR_SCRIPT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if is_process_running(pid):
                running_scripts.append(f"Haritalama (PID:{pid})")
        except:
            pass

    # Otonom script kontrol
    if os.path.exists(AUTONOMOUS_SCRIPT_PID_FILE):
        try:
            with open(AUTONOMOUS_SCRIPT_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if is_process_running(pid):
                running_scripts.append(f"Otonom (PID:{pid})")
        except:
            pass

    # Durum metni ve rengi
    if running_scripts:
        status_text = " + ".join(running_scripts)
        status_class = "text-success"
    else:
        status_text = "Beklemede"
        status_class = "text-warning"

    # CPU ve RAM kullanımı
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent

    return status_text, status_class, cpu, f"{cpu:.1f}%", ram, f"{ram:.1f}%"


# 6. Anlık Değerleri Güncelleme
@app.callback(
    [Output('current-angle', 'children'),
     Output('current-distance', 'children'),
     Output('current-speed', 'children'),
     Output('current-distance-col', 'style'),
     Output('max-detected-distance', 'children')],
    [Input('latest-scan-points-store', 'data'),
     State('latest-scan-object-store', 'data')]
)
def update_realtime_values(points_json, scan_json):
    """Anlık sensör değerlerini güncelle"""
    style = {
        'padding': '10px',
        'transition': 'background-color 0.5s ease',
        'borderRadius': '5px'
    }
    default_return = ("--°", "-- cm", "-- cm/s", style, "-- cm")

    if not points_json or not scan_json:
        return default_return

    try:
        df = pd.read_json(io.StringIO(points_json), orient='split')
        scan = json.loads(scan_json)
        if df.empty:
            return default_return
    except Exception:
        return default_return

    # En son noktayı al
    point = df.sort_values(by='id', ascending=False).iloc[0]

    angle = f"{point.get('derece', 0.0):.1f}°"
    dist = f"{point.get('mesafe_cm', 0.0):.1f} cm"
    speed = f"{point.get('hiz_cm_s', 0.0):.1f} cm/s"

    # Buzzer uyarısı için renk değiştir
    buzzer_dist = scan.get('buzzer_distance_setting')
    if buzzer_dist is not None and 0 < point['mesafe_cm'] <= buzzer_dist:
        style.update({'backgroundColor': '#d9534f', 'color': 'white'})

    # Maksimum mesafe
    df_valid = df[df['mesafe_cm'] > 0]
    max_dist_val = df_valid['mesafe_cm'].max() if not df_valid.empty else None
    max_dist = f"{max_dist_val:.1f} cm" if pd.notnull(max_dist_val) else "-- cm"

    return angle, dist, speed, style, max_dist


# 7. CSV Export
@app.callback(
    Output('download-csv', 'data'),
    Input('export-csv-button', 'n_clicks'),
    State('latest-scan-points-store', 'data'),
    prevent_initial_call=True
)
def export_csv_callback(n_clicks, points_json):
    """CSV dosyası oluştur ve indir"""
    if not points_json:
        return dcc.send_data_frame(pd.DataFrame().to_csv, "veri_yok.csv", index=False)

    df = pd.read_json(io.StringIO(points_json), orient='split')
    return dcc.send_data_frame(df.to_csv, "tarama_verisi.csv", index=False)


# 8. Excel Export
@app.callback(
    Output('download-excel', 'data'),
    Input('export-excel-button', 'n_clicks'),
    [State('latest-scan-object-store', 'data'),
     State('latest-scan-points-store', 'data')],
    prevent_initial_call=True
)
def export_excel_callback(n_clicks, scan_json, points_json):
    """Excel dosyası oluştur ve indir"""
    if not scan_json:
        return dcc.send_bytes(b"", "tarama_yok.xlsx")

    scan = json.loads(scan_json)
    scan_id = scan.get('id', 'bilinmeyen')

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Tarama bilgileri sayfası
        pd.DataFrame([scan]).to_excel(writer, sheet_name='Tarama Bilgileri', index=False)
        writer.sheets['Tarama Bilgileri'].autofit()

        # Nokta verileri sayfası
        if points_json:
            points_df = pd.read_json(io.StringIO(points_json), orient='split')
            points_df.to_excel(writer, sheet_name='Nokta Verileri', index=False)
            writer.sheets['Nokta Verileri'].autofit()

    output.seek(0)
    return dcc.send_bytes(output.getvalue(), f"tarama_detaylari_id_{scan_id}.xlsx")


# 9. Veri Tablosu
@app.callback(
    Output('tab-content-datatable', 'children'),
    [Input('visualization-tabs-main', 'active_tab'),
     Input('latest-scan-points-store', 'data')]
)
def render_and_update_data_table(active_tab, points_json):
    """Veri tablosunu oluştur"""
    if active_tab != "tab-datatable" or not points_json:
        return None

    df = pd.read_json(io.StringIO(points_json), orient='split')

    return dash_table.DataTable(
        data=df.to_dict('records'),
        columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
        page_size=20,
        sort_action="native",
        filter_action="native",
        virtualization=True,
        fixed_rows={'headers': True},
        style_table={'minHeight': '65vh', 'overflowY': 'auto'},
        style_cell={'textAlign': 'left'},
        style_header={'fontWeight': 'bold'}
    )


# 10. Tüm Grafikleri Güncelle (DÜZELTİLMİŞ)
@app.callback(
    [Output('scan-map-graph-3d', 'figure'),
     Output('scan-map-graph-2d', 'figure'),
     Output('polar-graph', 'figure'),
     Output('environment-estimation-text', 'children'),
     Output('clustered-data-store', 'data'),
     Output('calculated-area', 'children'),
     Output('perimeter-length', 'children'),
     Output('max-width', 'children'),
     Output('max-depth', 'children')],
    [Input('latest-scan-object-store', 'data'),
     Input('latest-scan-points-store', 'data')]
)
def update_all_graphs_and_analytics(scan_json, points_json):
    """Tüm grafikleri ve analizleri güncelle"""
    # Başlangıç durumu
    empty_fig = go.Figure(
        layout=dict(
            title='Veri Bekleniyor...',
            annotations=[dict(
                text="Tarama başlatın.",
                showarrow=False,
                font=dict(size=16)
            )]
        )
    )
    default_return = (empty_fig,) * 3 + (html.Div("Analiz için veri bekleniyor."), None) + ("--",) * 4

    if not scan_json or not points_json:
        return default_return

    # Veriyi yükle
    scan_data = json.loads(scan_json)
    scan_id = scan_data.get('id', 'Bilinmiyor')
    df = pd.read_json(io.StringIO(points_json), orient='split')

    if df.empty:
        empty_fig = go.Figure(layout=dict(title=f'Tarama #{scan_id} için Nokta Verisi Yok...'))
        return (empty_fig,) * 3 + (html.Div("Analiz için veri bekleniyor."), None) + ("--",) * 4

    # Geçerli verileri filtrele
    df_valid = df[(df['mesafe_cm'] > 0.1) & (df['mesafe_cm'] < 400.0)].copy()
    df_valid.dropna(subset=['x_cm', 'y_cm', 'z_cm', 'derece', 'dikey_aci'], inplace=True)

    # Figürleri başlat
    fig_3d = go.Figure(layout=dict(
        title=f'3D Tarama Görüntüsü - Tarama ID: {scan_id}',
        margin=dict(l=0, r=0, b=0, t=40)
    ))

    fig_2d = go.Figure(layout=dict(
        title='2D Harita (Üstten Görünüm)',
        xaxis_title='Y Ekseni (cm)',
        yaxis_title='X Ekseni (cm)',
        margin=dict(l=20, r=20, b=20, t=40)
    ))

    fig_polar = go.Figure(layout=dict(
        title='Polar Grafik',
        polar=dict(radialaxis=dict(title='Mesafe (cm)')),
        margin=dict(l=40, r=40, b=40, t=40)
    ))

    analysis_report_component = html.Div("Analiz için yetersiz veri.")
    store_data = None
    area, perim, width, depth = "-- cm²", "-- cm", "-- cm", "-- cm"

    if len(df_valid) > 10:
        # --- 3D GRAFİK ---
        custom_data_3d = np.stack((
            df_valid['derece'],
            df_valid['dikey_aci'],
            df_valid['id']
        ), axis=-1)

        fig_3d.add_trace(go.Scatter3d(
            x=df_valid['y_cm'],
            y=df_valid['x_cm'],
            z=df_valid['z_cm'],
            mode='markers',
            marker=dict(
                size=3,
                color=df_valid['mesafe_cm'],
                colorscale='Viridis',
                showscale=True,
                colorbar_title='Mesafe (cm)',
                line=dict(width=0)
            ),
            customdata=custom_data_3d,
            hovertemplate=(
                    "<b>Nokta Bilgileri</b><br><br>" +
                    "X (İleri): %{y:.1f} cm<br>" +
                    "Y (Yanal): %{x:.1f} cm<br>" +
                    "Z (Yükseklik): %{z:.1f} cm<br>" +
                    "--------------------<br>" +
                    "<b>Yatay Açı: %{customdata[0]:.1f}°</b><br>" +
                    "<b>Dikey Açı: %{customdata[1]:.1f}°</b><br>" +
                    "<i>Tıklayarak bu noktaya git</i>" +
                    "<extra></extra>"
            ),
            name='Tarama Noktaları'
        ))

        # Sensör pozisyonu
        fig_3d.add_trace(go.Scatter3d(
            x=[0], y=[0], z=[0],
            mode='markers',
            marker=dict(size=8, color='red', symbol='diamond'),
            name='Sensör (Başlangıç)',
            hovertemplate="<b>Robot Başlangıç Pozisyonu</b><extra></extra>"
        ))

        fig_3d.update_layout(
            scene=dict(
                xaxis_title='Y Ekseni (cm)',
                yaxis_title='X Ekseni (cm)',
                zaxis_title='Z Ekseni (cm)',
                aspectmode='data'
            ),
            clickmode='event+select'
        )

        # --- 2D GRAFİK (DÜZELTİLMİŞ) ---
        # Kümeleme yap
        desc, df_clustered = analyze_environment_shape(fig_2d, df_valid)

        # Sensör pozisyonu ekle
        fig_2d.add_trace(go.Scatter(
            x=[0], y=[0],
            mode='markers',
            marker=dict(size=12, color='red', symbol='circle'),
            name='Sensör'
        ))

        # Tarama sektörü ekle
        df_sorted = df_valid.sort_values(by='derece')
        poly_x = df_sorted['y_cm'].tolist()
        poly_y = df_sorted['x_cm'].tolist()
        fig_2d.add_trace(go.Scatter(
            x=[0] + poly_x + [0],
            y=[0] + poly_y + [0],
            mode='lines',
            fill='toself',
            fillcolor='rgba(255,0,0,0.15)',
            line=dict(color='rgba(255,0,0,0.4)'),
            name='Taranan Sektör'
        ))

        fig_2d.update_layout(yaxis=dict(scaleanchor="x", scaleratio=1))

        # --- POLAR GRAFİK (DÜZELTİLMİŞ) ---
        fig_polar.add_trace(go.Scatterpolar(
            r=df_valid['mesafe_cm'],
            theta=df_valid['derece'],
            mode='markers',
            marker=dict(
                size=5,
                color=df_valid['mesafe_cm'],
                colorscale='Viridis',
                showscale=True
            ),
            name='Mesafeler',
            hovertemplate="Açı: %{theta:.1f}°<br>Mesafe: %{r:.1f} cm<extra></extra>"
        ))

        # --- ANALİZLER ---
        env_key, analysis_report_component = classify_environment_and_get_report(df_valid)

        # Alan hesaplama
        try:
            hull = ConvexHull(df_valid[['y_cm', 'x_cm']].values)
            area = f"{hull.volume:.1f} cm²"
            perim = f"{hull.area:.1f} cm"
        except:
            area = "Hesaplanamadı"
            perim = "Hesaplanamadı"

        # Genişlik ve derinlik
        width = f"{df_valid['y_cm'].max() - df_valid['y_cm'].min():.1f} cm"
        depth = f"{df_valid['x_cm'].max():.1f} cm"

        # Kümelenmiş veriyi kaydet
        store_data = df_clustered.to_json(orient='split')

    return fig_3d, fig_2d, fig_polar, analysis_report_component, store_data, area, perim, width, depth


# 11. Küme Bilgisi Modal
@app.callback(
    [Output("cluster-info-modal", "is_open"),
     Output("modal-title", "children"),
     Output("modal-body", "children")],
    Input("scan-map-graph-2d", "clickData"),
    State("clustered-data-store", "data"),
    prevent_initial_call=True
)
def display_cluster_info(clickData, stored_data_json):
    """2D haritada bir noktaya tıklandığında küme bilgilerini göster"""
    if not clickData or not stored_data_json:
        return False, no_update, no_update

    try:
        df_clus = pd.read_json(io.StringIO(stored_data_json), orient='split')
        cl_label = clickData["points"][0].get('customdata')

        if cl_label is None or cl_label < -1:
            title = "Hata"
            body = "Küme etiketi alınamadı."
        elif cl_label == -1:
            title = "Gürültü Noktası"
            body = "Bu nokta bir nesne kümesine ait değil."
        else:
            cl_df = df_clus[df_clus['cluster'] == cl_label]
            w = cl_df['y_cm'].max() - cl_df['y_cm'].min()
            d = cl_df['x_cm'].max() - cl_df['x_cm'].min()

            title = f"Küme #{int(cl_label)} Detayları"
            body = html.Div([
                html.P(f"Nokta Sayısı: {len(cl_df)}"),
                html.P(f"Yaklaşık Genişlik: {w:.1f} cm"),
                html.P(f"Yaklaşık Derinlik: {d:.1f} cm")
            ])

        return True, title, body
    except Exception as e:
        return True, "Hata", f"Küme bilgisi gösterilemedi: {e}"


# 12. AI Yorumlama
@app.callback(
    [Output('ai-yorum-sonucu', 'children'),
     Output('ai-image', 'children')],
    Input('ai-model-dropdown', 'value'),
    [State('latest-scan-object-store', 'data'),
     State('latest-scan-points-store', 'data')],
    prevent_initial_call=True
)
def yorumla_model_secimi(selected_config_id, scan_json, points_json):
    """Seçilen AI modelini kullanarak tarama verilerini yorumla ve resim oluştur"""
    from scanner.models import AIModelConfiguration, Scan
    from scanner.ai_analyzer import AIAnalyzerService

    if not selected_config_id or not scan_json or not points_json:
        return "Analiz için bir model seçin ve tarama verisinin yüklendiğinden emin olun.", None

    try:
        config = AIModelConfiguration.objects.get(id=selected_config_id)
        scan_id = json.loads(scan_json).get('id')
        scan_to_analyze = Scan.objects.get(id=scan_id)

        analyzer = AIAnalyzerService(config=config)

        # Metin yorumu al
        turkish_analysis, english_prompt = analyzer.get_text_interpretation(scan=scan_to_analyze)
        text_component = dcc.Markdown(turkish_analysis, dangerously_allow_html=True)

        # Resim oluştur
        image_data_uri = analyzer.generate_image_with_imagen(english_prompt)

        if image_data_uri.startswith("data:image/png;base64,"):
            image_component = dbc.Spinner(html.Img(
                src=image_data_uri,
                style={
                    'maxWidth': '100%',
                    'height': 'auto',
                    'borderRadius': '10px',
                    'marginTop': '15px'
                }
            ))
        else:
            image_component = dbc.Alert(
                f"Resim oluşturulamadı: {image_data_uri}",
                color="warning",
                className="mt-3"
            )

        return text_component, image_component

    except Exception as e:
        traceback.print_exc()
        safe_error_message = str(e).encode('ascii', 'ignore').decode('ascii')
        return dbc.Alert(f"Hata: {safe_error_message}", color="danger"), None


# 13. 3D Harita Tıklama - Hedefe Git
@app.callback(
    [Output('navigation-status-text', 'children'),
     Output('target-coordinates', 'children')],
    Input('scan-map-graph-3d', 'clickData'),
    State('latest-scan-object-store', 'data'),
    prevent_initial_call=True
)
def handle_3d_map_click(clickData, scan_json):
    """3D haritada bir noktaya tıklandığında hedefe gitme komutunu yaz"""
    if not clickData:
        raise PreventUpdate

    if not scan_json:
        return (
            dbc.Alert("Aktif tarama yok!", color="warning"),
            ""
        )

    try:
        scan = json.loads(scan_json)

        # Otonom mod kontrolü
        if scan.get('scan_type') != 'AUT':
            return (
                dbc.Alert("Hedefe gitme sadece otonom modda çalışır!", color="warning"),
                ""
            )

        # Tıklanan noktanın koordinatlarını al
        point = clickData['points'][0]
        target_x = point['y']  # Plotly'de x/y ters
        target_y = point['x']
        target_z = point['z']

        # Komut dosyasına yaz (atomic operation ile)
        command_file = '/tmp/robot_command.txt'
        temp_file = command_file + '.tmp'

        with open(temp_file, 'w') as f:
            f.write(f"GOTO:{target_x},{target_y},{target_z}")

        os.replace(temp_file, command_file)  # Atomic rename

        logging.info(f"🎯 Hedefe gitme komutu gönderildi: ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")

        return (
            dbc.Alert([
                html.I(className="fa-solid fa-check-circle me-2"),
                "Hedefe gitme komutu gönderildi!"
            ], color="success"),
            html.Div([
                html.Strong("Hedef Koordinatlar:"),
                html.Br(),
                html.Small(f"X: {target_x:.1f} cm | Y: {target_y:.1f} cm | Z: {target_z:.1f} cm")
            ])
        )

    except Exception as e:
        logging.error(f"Hedefe gitme hatası: {e}")
        return (
            dbc.Alert(f"Hata: {str(e)}", color="danger"),
            ""
        )