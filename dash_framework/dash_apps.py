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

navbar = dbc.NavbarSimple(brand="Dream Pi 3D Scanner", brand_href="/", color="primary", dark=True, sticky="top")

control_panel = dbc.Card([
    dbc.CardHeader("Kontrol ve Ayarlar", className="bg-primary text-white"),
    dbc.CardBody([
        html.H6("Çalışma Modu:"),
        dbc.RadioItems(id='mode-selection-radios', options=[
            {'label': '3D Tarama Modu', 'value': 'scan_and_map'},
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
            dbc.InputGroup([dbc.InputGroupText("Yatay Tarama Açısı (°)", style={"width": "180px"}),
                            dbc.Input(id="scan-duration-angle-input", type="number",
                                      value=DEFAULT_UI_SCAN_DURATION_ANGLE)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Yatay Adım Açısı (°)", style={"width": "180px"}),
                            dbc.Input(id="step-angle-input", type="number", value=DEFAULT_UI_SCAN_STEP_ANGLE)],
                           className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Dikey Açı (Manuel)", style={"width": "180px"}),
                            dcc.Slider(id='servo-angle-slider', min=0, max=180, step=1, value=DEFAULT_UI_SERVO_ANGLE,
                                       marks={i: str(i) for i in range(0, 181, 45)},
                                       tooltip={"placement": "bottom", "always_visible": True}, className="mt-2")],
                           className="mb-4"),
            dbc.InputGroup([dbc.InputGroupText("Uyarı Mesafesi (cm)", style={"width": "180px"}),
                            dbc.Input(id="buzzer-distance-input", type="number", value=DEFAULT_UI_BUZZER_DISTANCE)],
                           className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Motor Adım/Tur", style={"width": "180px"}),
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
        dbc.Col(html.Div([html.H6("Yatay Açı:"), html.H4(id='current-angle', children="--°")]),
                className="text-center"),
        dbc.Col(html.Div([html.H6("Dikey Açı:"), html.H4(id='current-vertical-angle', children="--°")]),
                className="text-center"),
        dbc.Col(html.Div([html.H6("Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
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
        dcc.Dropdown(id='graph-selector-dropdown', options=[
            {'label': '3D Harita', 'value': '3d_map'},
            {'label': '2D Üstten Görünüm', 'value': 'map'},
            {'label': 'Yatay Açı-Mesafe Grafiği', 'value': 'h_angle_dist'},
            {'label': 'Dikey Açı-Mesafe Grafiği', 'value': 'v_angle_dist'},
        ], value='3d_map', clearable=False, className="m-3"),
        dcc.Loading(children=[
            html.Div(dcc.Graph(id='graph-3d-map'), id='container-3d-map'),
            html.Div(dcc.Graph(id='graph-2d-map'), id='container-2d-map', style={'display': 'none'}),
            html.Div(dcc.Graph(id='graph-h-angle-dist'), id='container-h-angle-dist', style={'display': 'none'}),
            html.Div(dcc.Graph(id='graph-v-angle-dist'), id='container-v-angle-dist', style={'display': 'none'}),
        ])
    ], label="Grafikler", tab_id="tab-graphics"),
    dbc.Tab(dcc.Loading(children=[html.Div(id='tab-content-datatable')]), label="Veri Tablosu", tab_id="tab-datatable")
], id="visualization-tabs-main", active_tab="tab-graphics")

ai_commentary_card = dbc.Card([
    dbc.CardHeader("Akıllı Yorumlama (Yapay Zeka)", className="bg-info text-white"),
    dbc.CardBody(dcc.Loading(children=[
        html.Div(id='ai-yorum-sonucu', children=[html.P("Yorum almak için bir model seçin...")]),
    ]))
])

app.layout = html.Div(style={'padding': '20px'}, children=[
    navbar,
    html.H1("3D Tarayıcı Kontrol Paneli", className="text-center my-3"),
    html.Hr(),
    dbc.Row([
        dbc.Col([control_panel, html.Br(), stats_panel, html.Br(), system_card, html.Br(), export_card], md=4),
        dbc.Col([visualization_tabs, html.Br(), ai_commentary_card], md=8)
    ]),
    dcc.Store(id='scan-data-store'),
    dcc.Interval(id='interval-component-main', interval=3000, n_intervals=0),
    dcc.Interval(id='interval-component-system', interval=5000, n_intervals=0),
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
        print(f"DB Hatası (get_latest_scan): {e}");
        return None


def yorumla_veriyi_gemini(df, model_name):
    if not GOOGLE_GENAI_AVAILABLE or not google_api_key: return "Hata: Google AI yapılandırılmamış."
    if df is None or df.empty: return "Yorumlanacak veri yok."
    try:
        model = genai.GenerativeModel(model_name=model_name)
        # Veriyi özetleyerek daha iyi bir prompt oluştur
        summary = df[['derece', 'dikey_aci', 'mesafe_cm']].describe().to_string()
        prompt = (f"Bir 3D sensör tarama verisi özeti aşağıdadır:\n\n{summary}\n\n"
                  "Bu verilere dayanarak, taranan ortamın genel yapısını (örn: 'geniş bir oda', 'karşısı duvar olan bir koridor') ve "
                  "belirgin özelliklerini analiz et. Cevabını Markdown formatında, düzenli bir şekilde sun.")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini metin yorumu hatası: {e}"


# ==============================================================================
# CALLBACK FONKSİYONLARI
# ==============================================================================

@app.callback(Output('scan-parameters-wrapper', 'style'), Input('mode-selection-radios', 'value'))
def toggle_parameter_visibility(selected_mode):
    return {'display': 'block'} if selected_mode == 'scan_and_map' else {'display': 'none'}


@app.callback(
    Output('scan-status-message', 'children'),
    Input('start-scan-button', 'n_clicks'),
    [State('mode-selection-radios', 'value'), State('scan-duration-angle-input', 'value'),
     State('step-angle-input', 'value'),
     State('buzzer-distance-input', 'value'), State('invert-motor-checkbox', 'value'),
     State('steps-per-rev-input', 'value')],
    prevent_initial_call=True
)
def handle_start_script(n_clicks, mode, h_angle, h_step, buzzer, invert, steps):
    """
    Sensör betiğini başlatır. Not: Yeni sensor_script.py dikey açıyı kendi içinde
    taradığı için, arayüzdeki slider'dan gelen değer şimdilik komuta eklenmemiştir.
    """
    if n_clicks is None: return no_update
    if os.path.exists(SENSOR_SCRIPT_PID_FILE): return dbc.Alert("Zaten bir betik çalışıyor. Önce durdurun.",
                                                                color="warning")
    cmd_map = {
        'scan_and_map': [sys.executable, SENSOR_SCRIPT_PATH, "--h-angle", str(h_angle), "--h-step", str(h_step),
                         "--buzzer-distance", str(buzzer), "--invert-motor-direction", str(invert), "--steps-per-rev",
                         str(steps)],
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
def handle_stop_script(n_clicks):
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
    [Output('scan-data-store', 'data'), Output('current-angle', 'children'),
     Output('current-vertical-angle', 'children'),
     Output('current-distance', 'children'), Output('current-distance-col', 'style')],
    Input('interval-component-main', 'n_intervals')
)
def update_data_and_realtime_stats(n):
    """Periyodik olarak veritabanından tüm veriyi çeker ve anlık değerleri günceller."""
    scan = get_latest_scan()
    style = {'transition': 'background-color 0.5s ease'}
    if not scan:
        return None, "--°", "--°", "-- cm", style

    points_qs = scan.points.all().values('derece', 'dikey_aci', 'mesafe_cm', 'x_cm', 'y_cm', 'z_cm')
    if not points_qs.exists():
        return None, "--°", "--°", "-- cm", style

    df = pd.DataFrame(list(points_qs))
    latest_point = df.iloc[-1]  # En son eklenen nokta

    h_angle = f"{latest_point['derece']:.1f}°" if pd.notnull(latest_point['derece']) else "--"
    v_angle = f"{latest_point['dikey_aci']:.1f}°" if pd.notnull(latest_point['dikey_aci']) else "--"
    dist = f"{latest_point['mesafe_cm']:.1f} cm" if pd.notnull(latest_point['mesafe_cm']) else "--"

    if scan.buzzer_distance_setting and pd.notnull(latest_point['mesafe_cm']) and 0 < latest_point[
        'mesafe_cm'] <= scan.buzzer_distance_setting:
        style.update({'backgroundColor': '#d9534f', 'color': 'white', 'borderRadius': '5px'})

    return df.to_json(orient='split'), h_angle, v_angle, dist, style


@app.callback(
    [Output('graph-3d-map', 'figure'), Output('graph-2d-map', 'figure'),
     Output('graph-h-angle-dist', 'figure'), Output('graph-v-angle-dist', 'figure')],
    Input('scan-data-store', 'data')
)
def update_all_graphs(json_data):
    """Merkezi veri deposundaki değişikliklere göre tüm grafikleri günceller."""
    if not json_data:
        empty_fig = go.Figure(
            layout={'title': 'Veri Bekleniyor...', 'xaxis': dict(visible=False), 'yaxis': dict(visible=False)})
        return empty_fig, empty_fig, empty_fig, empty_fig

    df = pd.read_json(json_data, orient='split')
    df_valid = df[df['mesafe_cm'] > 0].copy()
    if df_valid.empty:
        return no_update, no_update, no_update, no_update

    # Figürleri oluştur
    fig3d = go.Figure(layout=dict(title='3D Nokta Bulutu Haritası', margin=dict(l=0, r=0, b=0, t=40)))
    fig2d = go.Figure(layout=dict(title='2D Üstten Görünüm (X-Y Projeksiyonu)', yaxis_scaleanchor="x"))
    fig_h = go.Figure(layout=dict(title='Yatay Açıya Göre Mesafe'))
    fig_v = go.Figure(layout=dict(title='Dikey Açıya Göre Mesafe'))

    # 3D Harita
    fig3d.add_trace(go.Scatter3d(x=df_valid['y_cm'], y=df_valid['x_cm'], z=df_valid['z_cm'], mode='markers',
                                 marker=dict(size=2, color=df_valid['z_cm'], colorscale='Viridis', showscale=True,
                                             colorbar_title='Yükseklik (cm)')))
    fig3d.update_layout(
        scene=dict(xaxis_title='Y Ekseni (cm)', yaxis_title='X Ekseni (cm)', zaxis_title='Z Ekseni (cm)',
                   aspectmode='data'))

    # 2D Harita
    fig2d.add_trace(go.Scatter(x=df_valid['y_cm'], y=df_valid['x_cm'], mode='markers',
                               marker=dict(color=df_valid['dikey_aci'], colorscale='Cividis', showscale=True,
                                           colorbar_title='Dikey Açı')))

    # Açı-Mesafe Grafikleri
    fig_h.add_trace(go.Scatter(x=df_valid['derece'], y=df_valid['mesafe_cm'], mode='markers'))
    fig_v.add_trace(go.Scatter(x=df_valid['dikey_aci'], y=df_valid['mesafe_cm'], mode='markers'))

    return fig3d, fig2d, fig_h, fig_v


@app.callback(
    [Output('container-3d-map', 'style'), Output('container-2d-map', 'style'),
     Output('container-h-angle-dist', 'style'), Output('container-v-angle-dist', 'style')],
    Input('graph-selector-dropdown', 'value')
)
def update_graph_visibility(selected_graph):
    styles = {'display': 'block'}
    return [styles if k == selected_graph else {'display': 'none'} for k in
            ['3d_map', 'map', 'h_angle_dist', 'v_angle_dist']]


@app.callback(Output('ai-yorum-sonucu', 'children'), Input('ai-model-dropdown', 'value'),
              State('scan-data-store', 'data'), prevent_initial_call=True)
def get_ai_commentary(selected_model, json_data):
    if not selected_model: return "Yorum için bir model seçin."
    if not json_data: return "Analiz için veri yok."
    df = pd.read_json(json_data, orient='split')
    yorum = yorumla_veriyi_gemini(df, selected_model)
    return dcc.Markdown(yorum)


@app.callback(Output('tab-content-datatable', 'children'), Input('visualization-tabs-main', 'active_tab'),
              State('scan-data-store', 'data'))
def render_data_table(active_tab, json_data):
    if active_tab != "tab-datatable" or not json_data: return no_update
    df = pd.read_json(json_data, orient='split')
    return dash_table.DataTable(data=df.to_dict('records'),
                                columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
                                page_size=50, sort_action="native", filter_action="native", virtualization=True)


@app.callback(Output('download-csv', 'data'), Input('export-csv-button', 'n_clicks'), State('scan-data-store', 'data'),
              prevent_initial_call=True)
def export_csv_callback(n_clicks, json_data):
    if not json_data: return dcc.send_data_frame(pd.DataFrame().to_csv, "veri_yok.csv", index=False)
    df = pd.read_json(json_data, orient='split')
    return dcc.send_data_frame(df.to_csv, "tarama_verileri.csv", index=False)


@app.callback(Output('download-excel', 'data'), Input('export-excel-button', 'n_clicks'),
              State('scan-data-store', 'data'), prevent_initial_call=True)
def export_excel_callback(n_clicks, json_data):
    if not json_data: return dcc.send_bytes(b"", "veri_yok.xlsx")
    df = pd.read_json(json_data, orient='split')
    with io.BytesIO() as buffer:
        df.to_excel(buffer, sheet_name='ScanPoints', index=False)
        return dcc.send_bytes(buffer.getvalue(), "tarama_verileri.xlsx")