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

# Django Modelleri (Hata kontrolü ile)
try:
    from django.db.models import Max
    from scanner.models import Scan, ScanPoint

    DJANGO_MODELS_AVAILABLE = True
    print("Dashboard: Django modelleri başarıyla import edildi.")
except Exception as e:
    print(f"UYARI: Django modelleri import edilemedi: {e}. Veritabanı işlemleri çalışmayabilir.")
    DJANGO_MODELS_AVAILABLE = False
    Scan, ScanPoint = None, None

# Dash Kütüphaneleri
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, no_update, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

# Google AI Kütüphanesi
try:
    import google.generativeai as genai

    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    print("UYARI: 'google.generativeai' kütüphanesi bulunamadı. AI yorumlama özelliği çalışmayacak.")
    GOOGLE_GENAI_AVAILABLE = False

from dotenv import load_dotenv

load_dotenv()
google_api_key = os.getenv("GOOGLE_API_KEY")

# --- SABİTLER VE UYGULAMA BAŞLATMA ---
SENSOR_SCRIPT_FILENAME = 'sensor_script.py'
AUTONOMOUS_DRIVE_SCRIPT_FILENAME = 'autonomous_drive.py'

# Script yolları
APP_DIR = os.getcwd()
SENSOR_SCRIPT_PATH = os.path.join(APP_DIR, SENSOR_SCRIPT_FILENAME)
AUTONOMOUS_DRIVE_SCRIPT_PATH = os.path.join(APP_DIR, AUTONOMOUS_DRIVE_SCRIPT_FILENAME)

# Her mod için ayrı PID ve Kilit dosyaları
SENSOR_PID_FILE = '/tmp/sensor_scan_script.pid'
SENSOR_LOCK_FILE = '/tmp/sensor_scan_script.lock'
AUTONOMOUS_PID_FILE = '/tmp/autonomous_drive.pid'
AUTONOMOUS_LOCK_FILE = '/tmp/autonomous_drive.lock'

# Arayüz için varsayılan değerler
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

# --- LAYOUT BİLEŞENLERİ ---
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
                {'label': '3D Haritalama Modu', 'value': 'scan_and_map'},
                {'label': 'Otonom Sürüş Modu', 'value': 'autonomous_drive'},
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
            html.H6("Haritalama Parametreleri:", className="mt-2"),
            dbc.InputGroup([dbc.InputGroupText("Tarama Açısı (°)", style={"width": "150px"}),
                            dbc.Input(id="scan-duration-angle-input", type="number",
                                      value=DEFAULT_UI_SCAN_DURATION_ANGLE,
                                      min=10, max=720, step=1)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Adım Açısı (°)", style={"width": "150px"}),
                            dbc.Input(id="step-angle-input", type="number", value=DEFAULT_UI_SCAN_STEP_ANGLE, min=0.1,
                                      max=45, step=0.1)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Uyarı Mes. (cm)", style={"width": "150px"}),
                            dbc.Input(id="buzzer-distance-input", type="number", value=DEFAULT_UI_BUZZER_DISTANCE,
                                      min=0, max=200, step=1)], className="mb-2"),
            dbc.InputGroup([dbc.InputGroupText("Motor Adım/Tur", style={"width": "150px"}),
                            dbc.Input(id="steps-per-rev-input", type="number", value=DEFAULT_UI_STEPS_PER_REVOLUTION,
                                      min=500, max=10000, step=1)], className="mb-2"),
            dbc.Checkbox(id="invert-motor-checkbox", label="Motor Yönünü Ters Çevir", value=DEFAULT_UI_INVERT_MOTOR,
                         className="mt-2 mb-2"),
        ])
    ])
])

stats_panel = dbc.Card([dbc.CardHeader("Anlık Sensör Değerleri", className="bg-info text-white"), dbc.CardBody(dbc.Row(
    [dbc.Col(html.Div([html.H6("Mevcut Açı:"), html.H4(id='current-angle', children="--°")]), width=4,
             className="text-center border-end"),
     dbc.Col(html.Div([html.H6("Mevcut Mesafe:"), html.H4(id='current-distance', children="-- cm")]),
             id='current-distance-col', width=4, className="text-center rounded border-end"),
     dbc.Col(html.Div([html.H6("Max. Mesafe:"), html.H4(id='max-detected-distance', children="-- cm")]),
             width=4, className="text-center")]))], className="mb-3")

system_card = dbc.Card([dbc.CardHeader("Sistem Durumu", className="bg-secondary text-white"), dbc.CardBody(
    [dbc.Row([dbc.Col(html.Div([html.H6("Aktif Mod Durumu:"), html.H5(id='script-status', children="Beklemede")]))],
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

visualization_tabs = dbc.Tabs(
    [
        dbc.Tab(dcc.Graph(id='scan-map-graph-3d', style={'height': '75vh'}), label="3D Harita"),
        dbc.Tab(dcc.Graph(id='scan-map-graph', style={'height': '75vh'}), label="2D Harita"),
        dbc.Tab(dcc.Loading(id="loading-datatable", children=[html.Div(id='tab-content-datatable')]),
                label="Veri Tablosu"),
    ],
    id="visualization-tabs-main"
)

# Ana Uygulama Layout'u
app.layout = html.Div(
    style={'padding': '20px'},
    children=[
        navbar,
        title_card,
        dbc.Row([
            dbc.Col(
                [
                    control_panel,
                    html.Br(),
                    stats_panel,
                    html.Br(),
                    system_card,
                    html.Br(),
                    export_card
                ],
                md=4,
                className="mb-3"
            ),
            dbc.Col(
                [
                    visualization_tabs,
                ],
                md=8
            )
        ]),
        dcc.Interval(id='interval-component-main', interval=2500, n_intervals=0),
        dcc.Interval(id='interval-component-system', interval=3000, n_intervals=0),
    ]
)


# --- YARDIMCI FONKSİYONLAR ---
def is_process_running(pid):
    """Verilen PID'ye sahip bir sürecin çalışıp çalışmadığını kontrol eder."""
    if pid is None: return False
    try:
        return psutil.pid_exists(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def get_latest_scan():
    """Veritabanından en son tarama nesnesini alır."""
    if not DJANGO_MODELS_AVAILABLE: return None
    try:
        running_scan = Scan.objects.filter(status=Scan.Status.RUNNING).order_by('-start_time').first()
        if running_scan: return running_scan
        return Scan.objects.order_by('-start_time').first()
    except Exception as e:
        print(f"DB Hatası (get_latest_scan): {e}");
        return None


# --- CALLBACK FONKSİYONLARI ---

@app.callback(
    Output('scan-parameters-wrapper', 'style'),
    Input('mode-selection-radios', 'value')
)
def toggle_parameter_visibility(selected_mode):
    """Haritalama parametrelerini yalnızca ilgili mod seçildiğinde gösterir."""
    if selected_mode == 'scan_and_map':
        return {'display': 'block'}
    else:
        return {'display': 'none'}


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
def handle_start_script(n_clicks, selected_mode, duration, step, buzzer_dist, invert, steps_rev):
    """Seçilen moda göre doğru script'i başlatır ve kendi PID dosyasını kullanır."""
    if n_clicks == 0:
        return no_update

    script_path_to_run = None
    pid_file_to_check = None
    cmd = []
    py_exec = sys.executable

    if selected_mode == 'scan_and_map':
        script_path_to_run = SENSOR_SCRIPT_PATH
        pid_file_to_check = SENSOR_PID_FILE
        if not (isinstance(duration, (int, float)) and 10 <= duration <= 720):
            return dbc.Alert("Tarama Açısı 10-720 derece arasında olmalı!", color="danger")
        if not (isinstance(step, (int, float)) and 0.1 <= abs(step) <= 45):
            return dbc.Alert("Adım açısı 0.1-45 arasında olmalı!", color="danger")

        cmd = [py_exec, script_path_to_run,
               "--h-angle", str(duration),
               "--h-step", str(step),
               "--buzzer-distance", str(buzzer_dist),
               "--invert-motor-direction", str(bool(invert)),
               "--steps-per-rev", str(steps_rev)]

    elif selected_mode == 'autonomous_drive':
        script_path_to_run = AUTONOMOUS_DRIVE_SCRIPT_PATH
        pid_file_to_check = AUTONOMOUS_PID_FILE
        cmd = [py_exec, script_path_to_run]
    else:
        return dbc.Alert("Geçersiz mod seçildi!", color="danger")

    if os.path.exists(pid_file_to_check):
        try:
            with open(pid_file_to_check, 'r') as pf:
                pid = int(pf.read().strip())
            if is_process_running(pid):
                return dbc.Alert(f"Bu modda bir betik zaten çalışıyor (PID:{pid}). Önce durdurun.", color="warning")
        except:
            pass

    try:
        print(f"Çalıştırılacak komut: {' '.join(cmd)}")
        subprocess.Popen(cmd, start_new_session=True)
        time.sleep(2)
        if os.path.exists(pid_file_to_check):
            with open(pid_file_to_check, 'r') as pf:
                new_pid = pf.read().strip()
            return dbc.Alert(f"{selected_mode.replace('_', ' ').title()} modu başlatıldı (PID:{new_pid}).",
                             color="success")
        else:
            return dbc.Alert("Başlatılamadı. PID dosyası beklenilen sürede oluşmadı.", color="danger")
    except Exception as e:
        return dbc.Alert(f"Betik başlatma hatası: {e}", color="danger")


@app.callback(
    Output('scan-status-message', 'children', allow_duplicate=True),
    [Input('stop-scan-button', 'n_clicks')],
    [State('mode-selection-radios', 'value')],
    prevent_initial_call=True
)
def handle_stop_script(n_clicks, selected_mode):
    """Seçili olan moda ait çalışan script'i, doğru PID dosyasını kullanarak durdurur."""
    if n_clicks == 0: return no_update

    if selected_mode == 'scan_and_map':
        pid_file_to_check = SENSOR_PID_FILE
        lock_file_to_clean = SENSOR_LOCK_FILE
    elif selected_mode == 'autonomous_drive':
        pid_file_to_check = AUTONOMOUS_PID_FILE
        lock_file_to_clean = AUTONOMOUS_LOCK_FILE
    else:
        return no_update

    pid_to_kill = None
    message = ""
    color = "warning"

    if os.path.exists(pid_file_to_check):
        try:
            with open(pid_file_to_check, 'r') as pf:
                pid_to_kill = int(pf.read().strip())
            if is_process_running(pid_to_kill):
                os.kill(pid_to_kill, signal.SIGTERM)
                time.sleep(1)
                if is_process_running(pid_to_kill):
                    os.kill(pid_to_kill, signal.SIGKILL)
                message = f"Çalışan betik (PID:{pid_to_kill}) durduruldu."
                color = "info"
            else:
                message = "PID dosyası var ama ilgili süreç çalışmıyor. Dosyalar temizleniyor."
        except Exception as e:
            message = f"Durdurma hatası: {e}";
            color = "danger"
    else:
        message = "Bu modda çalışan bir betik bulunamadı."

    for fp in [pid_file_to_check, lock_file_to_clean]:
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError:
                pass

    return dbc.Alert(message, color=color)


@app.callback(
    [Output('script-status', 'children'), Output('script-status', 'className'),
     Output('cpu-usage', 'value'), Output('cpu-usage', 'label'),
     Output('ram-usage', 'value'), Output('ram-usage', 'label')],
    [Input('interval-component-system', 'n_intervals'),
     Input('mode-selection-radios', 'value')]
)
def update_system_card(n, selected_mode):
    """Sistem durumu kartını (CPU, RAM ve aktif mod durumu) günceller."""
    if selected_mode == 'scan_and_map':
        pid_file_to_check = SENSOR_PID_FILE
        mode_name = "Haritalama"
    elif selected_mode == 'autonomous_drive':
        pid_file_to_check = AUTONOMOUS_PID_FILE
        mode_name = "Otonom Sürüş"
    else:
        mode_name = "Bilinmeyen Mod"

    status_text, status_class = f"{mode_name}: Çalışmıyor", "text-danger"
    pid_val = None

    if os.path.exists(pid_file_to_check):
        try:
            with open(pid_file_to_check, 'r') as pf:
                pid_val = int(pf.read().strip())
            if is_process_running(pid_val):
                status_text, status_class = f"{mode_name}: Çalışıyor (PID:{pid_val})", "text-success"
        except:
            pass

    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    return status_text, status_class, cpu, f"{cpu:.1f}%", ram, f"{ram:.1f}%"


@app.callback(
    [Output('scan-map-graph-3d', 'figure'),
     Output('scan-map-graph', 'figure')],
    [Input('interval-component-main', 'n_intervals')]
)
def update_graphs(n):
    """Grafikleri periyodik olarak günceller."""
    scan = get_latest_scan()
    fig_3d = go.Figure()
    fig_2d = go.Figure()

    fig_3d.update_layout(title_text='3D Harita', uirevision=str(time.time()), scene=dict(aspectmode='data'))
    fig_2d.update_layout(title_text='2D Projeksiyon', uirevision=str(time.time()), yaxis_scaleanchor="x",
                         yaxis_scaleratio=1)

    if scan and DJANGO_MODELS_AVAILABLE:
        points_qs = ScanPoint.objects.filter(scan=scan).values('x_cm', 'y_cm', 'z_cm')
        if points_qs.exists():
            df = pd.DataFrame(list(points_qs))
            df_val = df.dropna().copy()

            if not df_val.empty:
                # 3D Grafik
                fig_3d.add_trace(go.Scatter3d(
                    x=df_val['y_cm'], y=df_val['x_cm'], z=df_val['z_cm'],
                    mode='markers',
                    marker=dict(size=3, color=df_val['z_cm'], colorscale='Viridis', showscale=True,
                                colorbar_title='Yükseklik (cm)')
                ))
                # 2D Grafik
                fig_2d.add_trace(go.Scatter(
                    x=df_val['y_cm'], y=df_val['x_cm'],
                    mode='markers',
                    marker=dict(size=5, color='blue')
                ))

    return fig_3d, fig_2d


@app.callback(
    [Output('current-angle', 'children'),
     Output('current-distance', 'children'),
     Output('current-distance-col', 'style'),
     Output('max-detected-distance', 'children')],
    [Input('interval-component-main', 'n_intervals')]
)
def update_realtime_values(n):
    """Anlık sensör değerlerini günceller ve uyarı mesafesine göre stil uygular."""
    scan = get_latest_scan()
    angle_s, dist_s, max_dist_s = "--°", "-- cm", "-- cm"
    dist_style = {'padding': '10px', 'transition': 'background-color 0.5s ease', 'borderRadius': '5px'}
    if scan and DJANGO_MODELS_AVAILABLE:
        point = scan.points.order_by('-timestamp').first()
        if point:
            angle_s = f"{point.derece:.1f}°" if pd.notnull(point.derece) else "--°"
            dist_s = f"{point.mesafe_cm:.1f} cm" if pd.notnull(point.mesafe_cm) else "-- cm"
            buzzer_threshold = scan.buzzer_distance_setting
            if buzzer_threshold is not None and pd.notnull(point.mesafe_cm) and 0 < point.mesafe_cm <= buzzer_threshold:
                dist_style.update({'backgroundColor': '#d9534f', 'color': 'white'})
            max_dist_agg = scan.points.filter(mesafe_cm__lt=2500, mesafe_cm__gt=0).aggregate(
                max_dist_val=Max('mesafe_cm'))
            if max_dist_agg and max_dist_agg.get('max_dist_val') is not None:
                max_dist_s = f"{max_dist_agg['max_dist_val']:.1f} cm"
    return angle_s, dist_s, dist_style, max_dist_s


@app.callback(
    Output('download-csv', 'data'),
    Input('export-csv-button', 'n_clicks'),
    prevent_initial_call=True
)
def export_csv_callback(n_clicks_csv):
    """En son tarama verilerini CSV dosyası olarak indirir."""
    if not n_clicks_csv or not DJANGO_MODELS_AVAILABLE: return no_update
    scan = get_latest_scan()
    if not scan: return dcc.send_data_frame(pd.DataFrame().to_csv, "tarama_yok.csv", index=False)
    points_qs = scan.points.all().values()
    if not points_qs: return dcc.send_data_frame(pd.DataFrame().to_csv, f"tarama_id_{scan.id}_nokta_yok.csv",
                                                 index=False)
    df = pd.DataFrame(list(points_qs))
    return dcc.send_data_frame(df.to_csv, f"tarama_id_{scan.id}_noktalar.csv", index=False)


@app.callback(
    Output('download-excel', 'data'),
    Input('export-excel-button', 'n_clicks'),
    prevent_initial_call=True
)
def export_excel_callback(n_clicks_excel):
    """En son tarama verilerini ve metadata'yı Excel dosyası olarak indirir."""
    if not n_clicks_excel or not DJANGO_MODELS_AVAILABLE: return no_update
    scan = get_latest_scan()
    if not scan: return dcc.send_bytes(b"", "tarama_yok.xlsx")
    try:
        scan_info_data = Scan.objects.filter(id=scan.id).values().first()
        scan_info_df = pd.DataFrame([scan_info_data]) if scan_info_data else pd.DataFrame()
        points_df = pd.DataFrame(list(scan.points.all().values()))
    except Exception as e_excel_data:
        print(f"Excel için veri çekme hatası: {e_excel_data}")
        return dcc.send_bytes(b"", f"veri_cekme_hatasi.xlsx")

    with io.BytesIO() as buf:
        with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
            if not scan_info_df.empty: scan_info_df.to_excel(writer, sheet_name='Tarama_Bilgisi', index=False)
            if not points_df.empty: points_df.to_excel(writer, sheet_name='Tarama_Noktalari', index=False)
        return dcc.send_bytes(buf.getvalue(), f"tarama_detaylari_id_{scan.id}.xlsx")


@app.callback(
    Output('tab-content-datatable', 'children'),
    [Input('visualization-tabs-main', 'active_tab'),
     Input('interval-component-main', 'n_intervals')]
)
def render_and_update_data_table(active_tab, n):
    """Veri Tablosu sekmesini en son tarama verileriyle günceller."""
    if active_tab != "tab-datatable" or not DJANGO_MODELS_AVAILABLE: return None
    scan = get_latest_scan()
    if not scan: return html.P("Görüntülenecek tarama verisi yok.")
    points_qs = scan.points.order_by('-id').values('id', 'derece', 'dikey_aci', 'mesafe_cm', 'x_cm', 'y_cm', 'z_cm',
                                                   'timestamp')
    if not points_qs: return html.P(f"Tarama ID {scan.id} için nokta verisi bulunamadı.")
    df = pd.DataFrame(list(points_qs))
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')

    return dash_table.DataTable(
        data=df.to_dict('records'),
        columns=[{"name": i.replace("_", " ").title(), "id": i} for i in df.columns],
        style_cell={'textAlign': 'left', 'padding': '5px', 'fontSize': '0.9em'},
        style_header={'backgroundColor': 'rgb(230,230,230)', 'fontWeight': 'bold'},
        style_table={'minHeight': '65vh', 'height': '70vh', 'maxHeight': '75vh', 'overflowY': 'auto'},
        page_size=50,
        sort_action="native",
        filter_action="native",
        virtualization=True,
        fixed_rows={'headers': True}
    )
