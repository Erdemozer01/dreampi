# DreamPi Dash App (dashboard.py) - TAM VE DÜZELTİLMİŞ VERSİYON

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
SENSOR_SCRIPT_PATH = os.path.join(os.getcwd(), SENSOR_SCRIPT_FILENAME)
AUTONOMOUS_SCRIPT_FILENAME = 'autonomous_drive.py'
AUTONOMOUS_SCRIPT_PATH = os.path.join(os.getcwd(), AUTONOMOUS_SCRIPT_FILENAME)
SENSOR_SCRIPT_PID_FILE = '/tmp/sensor_scan_script.pid'

# Font Awesome için CSS linki
FONT_AWESOME = "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"

app = DjangoDash(
    'DreamPi',
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        FONT_AWESOME,
    ]
)

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
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    except Exception:
        return False


def stop_all_scripts():
    print("Tüm aktif betikler durduruluyor...")
    pid_file = SENSOR_SCRIPT_PID_FILE
    if os.path.exists(pid_file):
        pid_to_kill = None
        try:
            with open(pid_file, 'r') as f:
                content = f.read().strip()
                if content: pid_to_kill = int(content)
            if pid_to_kill and is_process_running(pid_to_kill):
                print(f"Çalışan işlem bulundu (PID: {pid_to_kill}). Durduruluyor...")
                os.kill(pid_to_kill, signal.SIGTERM)
        except (IOError, ValueError, Exception) as e:
            print(f"PID dosyası işlenirken hata: {e}")
        finally:
            if os.path.exists(pid_file): os.remove(pid_file)


def stop_current_operation(mode):
    print(f"'{mode}' modu için durdurma talebi alındı.")
    stop_all_scripts()
    return html.Span([html.I(className="fa-solid fa-play me-2"), "Başlat"]), False, True


def start_mapping_mode(scan_angle, step_angle, buzzer_dist, fixed_tilt):
    try:
        stop_all_scripts()
        cmd = [sys.executable, SENSOR_SCRIPT_PATH, "--scan-angle", str(scan_angle), "--step-angle", str(step_angle),
               "--buzzer-distance", str(buzzer_dist), "--fixed-tilt", str(fixed_tilt)]
        log_file = open("sensor_script_live.log", "w")
        subprocess.Popen(cmd, stdout=log_file, stderr=log_file, start_new_session=True)
        return html.Span([html.I(className="fa-solid fa-spinner fa-spin me-2"), "Haritalama..."]), True, False
    except Exception as e:
        print(f"Haritalama başlatma hatası: {e}")
        return html.Span([html.I(className="fa-solid fa-xmark me-2"), "Hata"]), False, True


def start_autonomous_mode(target_distance, speed_level):
    # Bu fonksiyonun içeriği gerekirse doldurulabilir
    return "Otonom mod henüz aktif değil", False, True


def start_manual_mode():
    # Bu fonksiyonun içeriği gerekirse doldurulabilir
    return "Manuel mod henüz aktif değil", False, True


# --- ARAYÜZ BİLEŞENLERİ (LAYOUT) ---

control_panel = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-gears me-2"), "Sistem Kontrolü"]),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.Label([html.I(className="fa-solid fa-compass me-2"), "Çalışma Modu:"], className="fw-bold mb-2"),
                dcc.RadioItems(
                    id='operation-mode',
                    options=[
                        {'label': html.Span(
                            [html.I(className="fa-solid fa-map-location-dot me-2"), " Haritalama Modu"]),
                         'value': 'mapping'},
                        {'label': html.Span([html.I(className="fa-solid fa-robot me-2"), " Otonom Sürüş Modu"]),
                         'value': 'autonomous', 'disabled': True},
                        {'label': html.Span([html.I(className="fa-solid fa-gamepad me-2"), " Manuel Kontrol"]),
                         'value': 'manual', 'disabled': True}
                    ], value='mapping', labelStyle={'display': 'block', 'margin': '5px 0'}, className="mb-3")
            ])
        ]),
        html.Div(id='mapping-parameters', children=[
            dbc.Row([
                dbc.Col([html.Label([html.I(className="fa-solid fa-expand me-2"), "Tarama Açısı (°):"],
                                    className="fw-bold"),
                         dbc.Input(id='scan-angle-input', type='number', value=270.0, step=10)], width=6),
                dbc.Col([html.Label([html.I(className="fa-solid fa-shoe-prints me-2"), "Adım Açısı (°):"],
                                    className="fw-bold"),
                         dbc.Input(id='step-angle-input', type='number', value=10.0, step=0.5)], width=6)],
                className="mb-2"),
            dbc.Row([
                dbc.Col([html.Label([html.I(className="fa-solid fa-volume-high me-2"), "Buzzer Mesafesi (cm):"],
                                    className="fw-bold"),
                         dbc.Input(id='buzzer-distance-input', type='number', value=10)], width=6),
                dbc.Col([html.Label([html.I(className="fa-solid fa-up-down me-2"), "Sabit Dikey Açı (°):"],
                                    className="fw-bold"),
                         dbc.Input(id='fixed-tilt-angle-input', type='number', value=45.0, step=5)], width=6)],
                className="mb-3")]),
        dbc.Row([
            dbc.Col([
                dbc.ButtonGroup([
                    dbc.Button([html.I(className="fa-solid fa-play me-2"), "Başlat"], id="start-button",
                               color="success", size="lg", className="me-2"),
                    dbc.Button([html.I(className="fa-solid fa-stop me-2"), "Durdur"], id="stop-button", color="danger",
                               size="lg", disabled=True)])
            ], width=12, className="text-center")])])])

stats_panel = dbc.Card([dbc.CardHeader([html.I(className="fa-solid fa-gauge-simple me-2"), "Anlık Sensör Değerleri"]),
                        dbc.CardBody(dbc.Row([
                            dbc.Col(html.Div([html.H6("Mevcut Açı:"), html.H4(id='current-angle', children="--°")]),
                                    id='current-angle-col', width=4, className="text-center border-end"),
                            dbc.Col(
                                html.Div([html.H6("Mevcut Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
                                id='current-distance-col', width=4, className="text-center rounded border-end"),
                            dbc.Col(html.Div(
                                [html.H6("Max Mesafe:"), html.H4(id='max-detected-distance', children="-- cm")]),
                                    width=4, className="text-center")]))], className="mb-3")

system_card = dbc.Card(
    [dbc.CardHeader([html.I(className="fa-solid fa-microchip me-2"), "Sistem Durumu"]), dbc.CardBody([
        dbc.Row([dbc.Col(html.Div([html.H6("Tarama Betiği:"), html.H5(id='script-status', children="Beklemede")]))],
                className="mb-2"),
        dbc.Row([
            dbc.Col(html.Div([html.H6("CPU Kullanımı:"),
                              dbc.Progress(id='cpu-usage', value=0, color="success", style={"height": "20px"},
                                           label="0%")])),
            dbc.Col(html.Div([html.H6("RAM Kullanımı:"),
                              dbc.Progress(id='ram-usage', value=0, color="info", style={"height": "20px"},
                                           label="0%")]))])])], className="mb-3")

export_card = dbc.Card(
    [dbc.CardHeader([html.I(className="fa-solid fa-download me-2"), "Veri Dışa Aktarma"]), dbc.CardBody([
        dbc.Button('CSV İndir', id='export-csv-button', color="primary", className="w-100 mb-2"),
        dcc.Download(id='download-csv'),
        dbc.Button('Excel İndir', id='export-excel-button', color="success", className="w-100"),
        dcc.Download(id='download-excel')])], className="mb-3")

analysis_card = dbc.Card(
    [dbc.CardHeader([html.I(className="fa-solid fa-calculator me-2"), "Tarama Analizi"]), dbc.CardBody([
        dbc.Row([
            dbc.Col([html.H6("Hesaplanan Alan:"), html.H4(id='calculated-area', children="-- cm²")]),
            dbc.Col([html.H6("Çevre Uzunluğu:"), html.H4(id='perimeter-length', children="-- cm")])]),
        dbc.Row([
            dbc.Col([html.H6("Max Genişlik:"), html.H4(id='max-width', children="-- cm")]),
            dbc.Col([html.H6("Max Derinlik:"), html.H4(id='max-depth', children="-- cm")])], className="mt-2")])])

estimation_card = dbc.Card(
    [dbc.CardHeader([html.I(className="fa-solid fa-lightbulb me-2"), "Akıllı Ortam Analizi"]), dbc.CardBody(
        html.Div("Tahmin: Bekleniyor...", id='environment-estimation-text', className="text-center"))])

visualization_tabs = dbc.Tabs([
    dbc.Tab(dcc.Graph(id='scan-map-graph-3d', style={'height': '75vh'}), label="3D Harita", tab_id="tab-3d"),
    dbc.Tab(dcc.Graph(id='scan-map-graph-2d', style={'height': '75vh'}), label="2D Harita", tab_id="tab-2d"),
    dbc.Tab(dcc.Graph(id='polar-graph', style={'height': '75vh'}), label="Polar Grafik", tab_id="tab-polar"),
    dbc.Tab(dcc.Loading(children=[html.Div(id='tab-content-datatable')]), label="Veri Tablosu", tab_id="tab-datatable")
], id="visualization-tabs-main", active_tab="tab-3d")

ai_card = dbc.Card([
    dbc.CardHeader([html.I(className="fa-solid fa-wand-magic-sparkles me-2"), "Akıllı Yorumlama (Yapay Zeka)"]),
    dbc.CardBody([
        dcc.Dropdown(id='ai-model-dropdown', placeholder="Analiz için bir AI modeli seçin...", className="mb-3"),
        dcc.Loading(id="loading-ai-comment", children=[
            html.Div(id='ai-yorum-sonucu', children=[html.P("Yorum almak için yukarıdan bir AI yapılandırması seçin.")],
                     className="text-center mt-2"),
            html.Div(id='ai-image', className="text-center mt-3")])
    ])
], className="mt-3")

# --- ANA UYGULAMA YERLEŞİMİ (LAYOUT) - DÜZELTİLDİ ---
app.layout = html.Div(style={'padding': '20px'}, children=[
    navbar,
    dbc.Row([
        # Sol Sütun
        dbc.Col([
            control_panel,
            html.Br(),
            stats_panel,
            html.Br(),
            system_card,
            html.Br(),
            export_card,
        ], md=4, className="mb-3"),

        # Sağ Sütun (EKSİK OLAN KISIM BURASIYDI)
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

    # Arka plan bileşenleri
    dcc.Store(id='latest-scan-object-store'),
    dcc.Store(id='latest-scan-points-store'),
    dcc.Store(id='clustered-data-store'),
    dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0),
    dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0),
    dbc.Modal([dbc.ModalHeader(dbc.ModalTitle(id="modal-title")), dbc.ModalBody(id="modal-body")],
              id="cluster-info-modal", is_open=False, centered=True),
])


# --- CALLBACK FONKSİYONLARI ---

@app.callback(
    [Output('latest-scan-object-store', 'data'), Output('latest-scan-points-store', 'data')],
    Input('interval-component-main', 'n_intervals')
)
def update_data_stores(n):
    try:
        scan = get_latest_scan()
        if not scan: return no_update, no_update
        scan_json = json.dumps(model_to_dict(scan), default=str)
        points_qs = scan.points.all().values('id', 'x_cm', 'y_cm', 'z_cm', 'derece', 'dikey_aci', 'mesafe_cm',
                                             'timestamp')
        if not points_qs.exists(): return scan_json, None
        df_pts = pd.DataFrame(list(points_qs))
        df_pts['timestamp'] = pd.to_datetime(df_pts['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        points_json = df_pts.to_json(orient='split')
        return scan_json, points_json
    except Exception as e:
        print(f"HATA: Merkezi veri deposu güncellenemedi: {e}")
        return None, None


@app.callback(
    Output('mapping-parameters', 'style'),
    Input('operation-mode', 'value')
)
def toggle_mode_parameters(selected_mode):
    return {'display': 'block'} if selected_mode == 'mapping' else {'display': 'none'}


@app.callback(
    [Output("start-button", "children"), Output("start-button", "disabled"), Output("stop-button", "disabled")],
    [Input("start-button", "n_clicks"), Input("stop-button", "n_clicks")],
    [State("operation-mode", "value"), State("scan-angle-input", "value"), State("step-angle-input", "value"),
     State("buzzer-distance-input", "value"), State("fixed-tilt-angle-input", "value")]
)
def handle_start_stop_operations(start_clicks, stop_clicks, mode, scan_angle, step_angle, buzzer_dist, fixed_tilt):
    ctx = dash.callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if button_id == "start-button":
        return start_mapping_mode(scan_angle, step_angle, buzzer_dist, fixed_tilt)
    elif button_id == "stop-button":
        return stop_current_operation(mode)
    return no_update


@app.callback(
    [Output('current-angle', 'children'), Output('current-distance', 'children'),
     Output('max-detected-distance', 'children'), Output('current-distance-col', 'style')],
    Input('latest-scan-points-store', 'data'),
    State('latest-scan-object-store', 'data')
)
def update_realtime_values(points_json, scan_json):
    style = {'padding': '10px', 'transition': 'background-color 0.5s ease', 'borderRadius': '5px'}
    if not points_json or not scan_json:
        return "--°", "-- cm", "-- cm", style

    df = pd.read_json(io.StringIO(points_json), orient='split')
    if df.empty:
        return "--°", "-- cm", "-- cm", style

    scan = json.loads(scan_json)
    point = df.sort_values(by='id', ascending=False).iloc[0]
    angle = f"{point.get('derece', 0.0):.1f}°"
    dist = f"{point.get('mesafe_cm', 0.0):.1f} cm"

    buzzer_dist = scan.get('buzzer_distance_setting')
    if buzzer_dist is not None and 0 < point['mesafe_cm'] <= buzzer_dist:
        style.update({'backgroundColor': '#d9534f', 'color': 'white'})

    df_valid = df[df['mesafe_cm'] > 0]
    max_dist_val = df_valid['mesafe_cm'].max() if not df_valid.empty else None
    max_dist = f"{max_dist_val:.1f} cm" if pd.notnull(max_dist_val) else "-- cm"

    return angle, dist, max_dist, style


# ORİJİNAL, TAM ÖZELLİKLİ GRAFİK FONKSİYONU
@app.callback(
    [Output('scan-map-graph-3d', 'figure'), Output('scan-map-graph-2d', 'figure'),
     Output('polar-graph', 'figure'), Output('environment-estimation-text', 'children'),
     Output('clustered-data-store', 'data'), Output('calculated-area', 'children'),
     Output('perimeter-length', 'children'), Output('max-width', 'children'),
     Output('max-depth', 'children')],
    [Input('latest-scan-points-store', 'data')]
)
def update_all_graphs_and_analytics(points_json):
    if not points_json:
        empty_fig = go.Figure(
            layout=dict(title='Veri Bekleniyor...', annotations=[dict(text="Tarama başlatın.", showarrow=False)]))
        return empty_fig, empty_fig, empty_fig, "Analiz için veri bekleniyor.", None, *["--"] * 4

    df = pd.read_json(io.StringIO(points_json), orient='split')
    if df.empty:
        empty_fig = go.Figure(layout=dict(title='Henüz Nokta Verisi Yok...'))
        return empty_fig, empty_fig, empty_fig, "Analiz için veri bekleniyor.", None, *["--"] * 4

    df_valid = df[(df['mesafe_cm'] > 0.1) & (df['mesafe_cm'] < 400.0)].copy()

    # Figürleri oluştur
    fig_3d = go.Figure()
    fig_2d = go.Figure()
    fig_polar = go.Figure()

    # Analiz metinleri için varsayılan değerler
    est_text, store_data = "Analiz için yetersiz veri.", None
    area, perim, width, depth = "-- cm²", "-- cm", "-- cm", "-- cm"

    if not df_valid.empty:
        # 3D Grafik
        fig_3d.add_trace(go.Scatter3d(x=df_valid['y_cm'], y=df_valid['x_cm'], z=df_valid['z_cm'], mode='markers',
                                      marker=dict(size=2, color=df_valid['z_cm'], colorscale='Viridis', showscale=True,
                                                  colorbar_title='Yükseklik (cm)')))
        fig_3d.add_trace(
            go.Scatter3d(x=[0], y=[0], z=[0], mode='markers', marker=dict(size=5, color='red'), name='Sensör'))
        fig_3d.update_layout(title_text='3D Tarama Haritası',
                             scene=dict(xaxis_title='Y Ekseni (cm)', yaxis_title='X Ekseni (cm)',
                                        zaxis_title='Z Ekseni (cm)', aspectmode='data'))

        # 2D Grafik
        est_cart, df_clus = analyze_environment_shape(fig_2d, df_valid.copy())
        store_data = df_clus.to_json(orient='split')
        add_scan_rays(fig_2d, df_valid)
        add_sector_area(fig_2d, df_valid)
        add_sensor_position(fig_2d)
        fig_2d.update_layout(title_text='2D Harita (Üstten Görünüm)', xaxis_title="Yatay Mesafe (cm)",
                             yaxis_title="Dikey Mesafe (cm)", yaxis_scaleanchor="x", yaxis_scaleratio=1)

        # Polar Grafik
        update_polar_graph(fig_polar, df_valid)
        fig_polar.update_layout(title_text='Polar Grafik')

        # Analizler
        est_text = html.Div([
            html.P(estimate_geometric_shape(df_valid), className="fw-bold"), html.Hr(),
            html.P(find_clearest_path(df_valid), className="fw-bold text-primary"), html.Hr(),
            html.P(f"Kümeleme: {est_cart}")
        ])

        # Alan, Çevre vb. hesaplamalar
        try:
            hull = ConvexHull(df_valid[['y_cm', 'x_cm']].values)
            area = f"{hull.volume:.2f} cm²"  # 2D için .volume alanı verir
            perim = f"{hull.area:.2f} cm"  # 2D için .area çevreyi verir
            width = f"{df_valid['y_cm'].max() - df_valid['y_cm'].min():.2f} cm"
            depth = f"{df_valid['x_cm'].max():.2f} cm"
        except Exception:
            pass  # Yetersiz nokta durumunda hata vermesini engelle

    return fig_3d, fig_2d, fig_polar, est_text, store_data, area, perim, width, depth


# ... (diğer tüm callback'ler aynı, bu yüzden tamlık için eklendi)
@app.callback(Output('tab-content-datatable', 'children'),
              [Input('visualization-tabs-main', 'active_tab'), Input('latest-scan-points-store', 'data')])
def render_and_update_data_table(active_tab, points_json):
    if active_tab != "tab-datatable" or not points_json:
        return html.P("Görüntülenecek veri yok.") if active_tab == "tab-datatable" else None
    df = pd.read_json(io.StringIO(points_json), orient='split')
    df = df[['id', 'derece', 'dikey_aci', 'mesafe_cm', 'x_cm', 'y_cm', 'z_cm', 'timestamp']]
    return dash_table.DataTable(data=df.to_dict('records'),
                                columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                page_size=20, sort_action="native", filter_action="native", virtualization=True,
                                fixed_rows={'headers': True}, style_table={'minHeight': '65vh', 'overflowY': 'auto'})