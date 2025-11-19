# camera_dash_app.py - FIXED v3.31 (Critical Bug Fixes Applied)
# CHANGES:
# - Fixed missing UI component 'ai-process-status'
# - Added missing 'motion-threshold-slider'
# - Fixed callback return values mismatch
# - Added _is_camera_paused attribute handling

import os
import sys
import time
import logging
import atexit
import json
import gc
import subprocess
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import hashlib
import base64
import io
import re
import pandas as pd

try:
    from .ai_vision import ai_vision_manager
    from .config import AIConfig, CameraConfig, MotorConfig, SensorConfig, AppConfig
    from .hardware_manager import GPIO_AVAILABLE, hardware_manager
    from .utils import safe_update_store, cleanup_old_store_data, format_distance, image_to_base64, split_data_uri, \
        base64_data_to_images
except ImportError:
    from ai_vision import ai_vision_manager
    from config import AIConfig, CameraConfig, MotorConfig, SensorConfig, AppConfig
    from hardware_manager import GPIO_AVAILABLE, hardware_manager
    from utils import safe_update_store, cleanup_old_store_data, format_distance, image_to_base64, split_data_uri, \
        base64_data_to_images

try:
    import cv2
    import numpy as np
    from skimage.metrics import structural_similarity as ssim
    from skimage.metrics import mean_squared_error
    import imagehash
    from PIL import Image
except ImportError:
    logging.error("KRİTİK HATA: Gerekli kütüphaneler eksik (scikit-image, imagehash, opencv-python, pillow).")
    sys.exit(1)

import dash
from django_plotly_dash import DjangoDash
from dash import html, dcc, Output, Input, State, ALL, MATCH, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from django.utils import timezone

try:
    from scanner.models import CameraCapture
except ImportError:
    pass

# --- GLOBAL DEĞİŞKENLER ---
external_ai_process = None

# --- LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

logging.getLogger("picamera2").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("ultralytics").setLevel(logging.ERROR)


def cleanup_external_process():
    """✅ IMPROVED: Ensure external process is properly terminated"""
    global external_ai_process
    if external_ai_process:
        logger.info("Cleaning up external AI process...")
        try:
            os.killpg(os.getpgid(external_ai_process.pid), signal.SIGTERM)
            external_ai_process.wait(timeout=5)
        except:
            try:
                os.killpg(os.getpgid(external_ai_process.pid), signal.SIGKILL)
            except:
                pass
        external_ai_process = None


def cleanup():
    logger.info("🧹 Temizlik başlatılıyor (atexit)...")
    cleanup_external_process()
    try:
        hardware_manager.cleanup_motor()
        hardware_manager.cleanup_sensor()
        hardware_manager.cleanup_camera()
    except Exception as e:
        logger.error(f"Cleanup hatası: {e}")


atexit.register(cleanup)

app = DjangoDash(
    AppConfig.APP_NAME,
    external_stylesheets=[dbc.themes.CYBORG, AppConfig.FONT_AWESOME],
    suppress_callback_exceptions=True
)

logger.info("Donanım başlatılıyor...")
hardware_manager.initialize_all()


# --- UI Helpers ---
def create_dropdown_options(enum_obj):
    if hasattr(enum_obj, '__dict__'):
        return [{'label': k, 'value': k} for k in enum_obj.__dict__.keys() if not k.startswith('_')]
    if isinstance(enum_obj, dict):
        return [{'label': k, 'value': k} for k in enum_obj.keys()]
    return []


# ============================================================================
# UI KOMPONENTLERİ
# ============================================================================

navbar = dbc.NavbarSimple(
    brand=f"Dream Pi {AppConfig.APP_VERSION}",
    brand_href="/",
    color="dark",
    dark=True,
    fluid=True,
    className="mb-4"
)

# --- 1. KAMERA PANELLERİ ---
basic_settings_tab = dbc.Card([
    dbc.CardBody([
        html.H5("Temel Ayarlar", className="mb-3"),
        html.Label("Çözünürlük Grubu:"),
        dcc.Dropdown(
            id='resolution-group-dropdown',
            options=[{'label': f'{k} - {v}', 'value': k} for k, v in CameraConfig.RESOLUTION_GROUPS.items()],
            value='HD', clearable=False, className="mb-2"
        ),
        html.Label("Çözünürlük:"),
        html.Div(id='resolution-radio-container', children=dbc.RadioItems(id='resolution-select-radio')),
        html.Hr(),
        html.Label("FrameRate (FPS):"),
        dcc.Slider(id='framerate-slider', min=5, max=120, step=5, value=30, marks={30: '30', 60: '60', 90: '90'}),
        html.Div(id='fps-warning', className="mt-2"),
        html.Hr(),
        dbc.Row([
            dbc.Col(dbc.Switch(id='ae-enable-switch', label="Auto Exp", value=True), width=6),
            dbc.Col(dbc.Switch(id='awb-enable-switch', label="Auto WB", value=True), width=6),
            dbc.Col(dbc.Switch(id='lens-correction-switch', label="Lens Düzeltme", value=True), width=6),
        ], className="mb-3"),
    ])
], className="mb-3")

manual_exposure_tab = dbc.Card([
    dbc.CardBody([
        html.H5("Manuel Pozlama", className="mb-3"),
        html.Small("⚠️ AE kapalıyken aktiftir", className="text-warning d-block mb-3"),
        html.Label("Pozlama Süresi (µs):"),
        dcc.Slider(id='exposure-time-slider', min=100, max=200000, step=100, value=10000),
        html.Div(id='exposure-time-display', className="text-info mb-3"),
        html.Label("ISO (Gain):"),
        dcc.Slider(id='iso-gain-slider', min=1.0, max=16.0, step=0.1, value=1.0),
        html.Div(id='iso-display', className="text-info mb-3"),
    ])
], className="mb-3")

advanced_modes_tab = dbc.Card([
    dbc.CardBody([
        html.H5("Gelişmiş Modlar", className="mb-3"),
        html.Label("AWB Modu:"),
        dcc.Dropdown(id='awb-mode-dropdown', options=create_dropdown_options(CameraConfig.AWB_MODES), value='Auto',
                     clearable=False),
        html.Label("Renk Efekti:"),
        dcc.Dropdown(id='colour-effect-dropdown', options=create_dropdown_options(CameraConfig.COLOUR_EFFECTS),
                     value='None', clearable=False),
        html.Label("Flicker Modu:"),
        dcc.Dropdown(id='flicker-mode-dropdown', options=create_dropdown_options(CameraConfig.FLICKER_MODES),
                     value='Off', clearable=False),
        html.Label("Pozlama Modu:"),
        dcc.Dropdown(id='exposure-mode-dropdown', options=create_dropdown_options(CameraConfig.EXPOSURE_MODES),
                     value='Normal', clearable=False),
        html.Label("Ölçüm Modu:"),
        dcc.Dropdown(id='metering-mode-dropdown', options=create_dropdown_options(CameraConfig.METERING_MODES),
                     value='Centre', clearable=False),
    ])
], className="mb-3")

camera_control_panel = dbc.Card([
    dbc.CardHeader("Kamera Kontrol"),
    dbc.CardBody([
        dbc.Tabs([
            dbc.Tab(basic_settings_tab, label="Temel"),
            dbc.Tab(manual_exposure_tab, label="Manuel"),
            dbc.Tab(advanced_modes_tab, label="Gelişmiş"),
        ]),
        html.Hr(),
        dbc.Button("Fotoğraf Çek", id='capture-photo-btn', color="success", size="lg", className="w-100")
    ])
], className="mb-3")

# --- 2. MOTOR VE SENSÖR PANELLERİ ---
motor_control_panel = dbc.Card([
    dbc.CardHeader("Motor Kontrol"),
    dbc.CardBody([
        html.Label("Pozisyon:"),
        dcc.Slider(id='pan-slider', min=-180, max=180, step=10, value=0, marks={-90: '-90', 0: '0', 90: '90'}),
        html.Div([
            dbc.Button("-10°", id='btn-n10', color="primary", size="sm", className="me-1", n_clicks=0),
            dbc.Button("0° (Home)", id='btn-home', color="success", size="sm", className="me-1", n_clicks=0),
            dbc.Button("+10°", id='btn-p10', color="primary", size="sm", n_clicks=0),
        ], className="mt-3 d-flex justify-content-center"),
        html.Div(id='motor-status-display', className="mt-2 text-center text-info")
    ])
], className="mb-3")

sensor_control_panel = dbc.Card([
    dbc.CardHeader("Sensör Verisi"),
    dbc.CardBody([
        dbc.Switch(id='sensor-switch', label="Canlı Okuma", value=False),
        html.H2(id='current-distance', className="text-center mt-3 text-success", children="-"),
        html.Div(id='distance-chart', className="mt-2")
    ])
], className="mb-3")

stats_card = dbc.Card([
    dbc.CardHeader("Sistem Durumu"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([html.H6("Motor"), html.H4(id='current-pan-angle', children="0°")]),
            dbc.Col([html.H6("Okuma"), html.H4(id='reading-count', children="0")]),
        ])
    ])
], className="mb-3")

# --- 3. AI VISION KONTROL (FIXED) ---
ai_vision_control_panel = dbc.Card([
    dbc.CardHeader("AI Vision Kontrol"),
    dbc.CardBody([
        # Model Seçimi
        html.Div([
            html.Label("YOLO Modeli Seç:", className="fw-bold text-info"),
            dcc.Dropdown(
                id='yolo-model-dropdown',
                options=[
                    {'label': '🚀 Nano (Çok Hızlı)', 'value': 'yolov8n.pt'},
                    {'label': '⚖️ Small (Dengeli)', 'value': 'yolov8s.pt'},
                    {'label': '🧠 Medium (Hassas)', 'value': 'yolov8m.pt'},
                ],
                value='yolov8s.pt',
                clearable=False,
                className="mb-3"
            ),
        ]),

        # Güven Skoru
        html.Div(id='yolo-settings-div', children=[
            html.Label("Güven Skoru (Confidence):"),
            dcc.Slider(id='yolo-confidence-slider', min=0.1, max=0.9, step=0.05, value=0.5,
                       marks={0.1: '0.1', 0.5: '0.5', 0.9: '0.9'},
                       tooltip={"placement": "bottom", "always_visible": True})
        ], style={'display': 'block'}),

        # ✅ FIXED: Added missing motion-threshold-slider
        html.Div(id='motion-settings-div', children=[
            html.Label("Motion Threshold:"),
            dcc.Slider(id='motion-threshold-slider', min=10, max=50, step=5, value=25,
                       marks={10: '10', 25: '25', 50: '50'},
                       tooltip={"placement": "bottom", "always_visible": True})
        ], style={'display': 'none'}),

        # Modül Seçimi
        dbc.Checklist(
            id='ai-modules-checklist',
            options=[
                {'label': '🎯 YOLO (Tüm Nesneler)', 'value': 'yolo'},
                {'label': '👤 Yüz Tanıma', 'value': 'face'},
                {'label': '📱 QR Kod', 'value': 'qr'},
                {'label': '✏️ Kenar', 'value': 'edges'},
                {'label': '🎬 Hareket', 'value': 'motion'},  # ✅ Added motion to list
            ],
            value=['yolo', 'face'], switch=True, className="mb-3 mt-3"
        ),

        html.Hr(),

        html.Div([
            html.I(className="fa-solid fa-desktop me-2"),
            "Harici Pencere (Subprocess):"
        ], className="fw-bold mb-2"),

        # HARİCİ PENCERE BUTONLARI
        dbc.Row([
            dbc.Col(dbc.Button(
                "Başlat (Pencere)", id='start-ai-processing-btn',
                color="warning", className="w-100", n_clicks=0
            ), width=6),
            dbc.Col(dbc.Button(
                "Durdur / Web'e Dön", id='stop-ai-processing-btn',
                color="danger", className="w-100", disabled=True, n_clicks=0
            ), width=6),
        ], className="mb-3"),

        html.Div(id='ai-status-indicator', className="mt-2 mb-3"),
        html.Div(id='ai-process-status', className="mt-2 text-center small text-muted"),  # ✅ ADDED THIS

        html.Hr(),

        # TEK ÇEKİM BUTONU
        dbc.Button(
            [html.I(className="fa-solid fa-camera me-2"), "Tek Çekim Analiz (Web)"],
            id='single-ai-snapshot-btn',
            color="info",
            size="lg",
            className="w-100",
            n_clicks=0
        ),
    ])
], className="mb-3")

ai_results_display = dbc.Card([
    dbc.CardHeader("AI Analiz Sonucu (Tek Çekim)"),
    dbc.CardBody([
        html.Img(id='ai-processed-image',
                 style={'width': '100%', 'borderRadius': '5px', 'minHeight': '200px', 'backgroundColor': '#222'}),
        html.Hr(),
        dbc.Row([
            dbc.Col(html.Div(id='yolo-count', children="YOLO: 0"), width=3),
            dbc.Col(html.Div(id='face-count', children="Face: 0"), width=3),
            dbc.Col(html.Div(id='motion-count', children="Motion: 0"), width=3),
            dbc.Col(html.Div(id='qr-count', children="QR: 0"), width=3),
        ]),
        html.Div(id='detection-list', className="mt-3 small text-muted")
    ])
], className="mb-3")

# --- 4. ORTA SEKME ALANLARI ---
photo_display_area = dbc.Card([
    dbc.CardBody([
        html.Img(id='captured-image', style={'width': '100%'}),
        html.Hr(),
        dbc.Table([html.Tbody(id='photo-info-table')], bordered=True, color="dark", striped=True),
        dbc.Button("Veritabanına Kaydet", id='save-to-db-btn', color="warning", className="w-100 mt-2", disabled=True),
        html.Div(id='last-save-status', className="mt-2 text-center")
    ])
], className="mb-3")

statistics_panel = dbc.Card([
    dbc.CardHeader("İstatistiksel Analiz"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col(dcc.Dropdown(id='stat-photo-1', placeholder="Referans Fotoğraf"), width=6),
            dbc.Col(dcc.Dropdown(id='stat-photo-2', placeholder="Karşılaştırılacak Fotoğraf"), width=6),
        ]),
        dbc.Button("İstatistiksel Olarak Anlamlandır", id='generate-statistics-btn', color="info",
                   className="w-100 mt-3"),
        dcc.Loading(html.Div(id='statistics-output-area', className="mt-3"))
    ])
], className="mb-3")

# --- ANA LAYOUT ---
app.layout = html.Div([
    navbar,
    dbc.Container([
        dbc.Row([
            # SOL KOLON
            dbc.Col([
                camera_control_panel,
                motor_control_panel,
                sensor_control_panel,
                stats_card,
                ai_vision_control_panel
            ], md=4),

            # SAĞ KOLON
            dbc.Col([
                dbc.Tabs([
                    dbc.Tab(photo_display_area, label="📸 Fotoğraf"),
                    dbc.Tab(ai_results_display, label="🤖 AI Analiz"),
                    dbc.Tab(statistics_panel, label="📊 İstatistik")
                ])
            ], md=8)
        ])
    ], fluid=True),

    # STORES & INTERVALS
    dcc.Store(id='current-photo-store', data={}),
    dcc.Store(id='sensor-store', data={}),
    dcc.Store(id='motor-click-store', data={'n10': 0, 'p10': 0, 'home': 0}),
    dcc.Store(id='ai-processing-state', data={'is_running': False, 'last_start': 0, 'last_stop': 0}),

    dcc.Interval(id='stats-update-interval', interval=5000),
    dcc.Interval(id='metrics-interval', interval=1000),
    dcc.Interval(id='cleanup-interval', interval=60000)
])


# ============================================================================
# CALLBACKS (FIXED)
# ============================================================================

# --- AI Process Launcher (FIXED) ---
@app.callback(
    [Output('ai-status-indicator', 'children'),
     Output('start-ai-processing-btn', 'disabled'),
     Output('stop-ai-processing-btn', 'disabled'),
     Output('ai-processing-state', 'data'),
     Output('ai-process-status', 'children')],  # ✅ NOW EXISTS
    [Input('start-ai-processing-btn', 'n_clicks'),
     Input('stop-ai-processing-btn', 'n_clicks')],
    [State('ai-processing-state', 'data'),
     State('yolo-model-dropdown', 'value'),
     State('yolo-confidence-slider', 'value'),
     State('resolution-select-radio', 'value')],
    prevent_initial_call=True
)
def manage_external_ai_process(start_clicks, stop_clicks, state, model_name, conf, res_str):
    global external_ai_process

    start_clicks = start_clicks or 0
    stop_clicks = stop_clicks or 0

    if state is None:
        state = {'is_running': False, 'last_start': 0, 'last_stop': 0}

    last_start = state.get('last_start', 0)
    last_stop = state.get('last_stop', 0)

    # --- BAŞLATMA ---
    if start_clicks > last_start:
        if external_ai_process is not None:
            return (
                dbc.Alert("Zaten çalışıyor!", color="warning"),
                True, False, state, "Çalışıyor..."
            )

        logger.info(f"🚀 AI Harici Pencere Başlatılıyor (Model: {model_name})...")

        try:
            # KAMERAYI KİLİTLE
            hardware_manager.pause_camera_usage()  # ✅ Uses new method
            time.sleep(2)

            # Harici scripti çalıştır
            env = os.environ.copy()
            env["DISPLAY"] = ":0"

            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nesne_tesbit.py')
            if not os.path.exists(script_path):
                script_path = "nesne_tesbit.py"

            w, h = 640, 480
            model_path = f"models/{model_name}"

            cmd = [
                "python3", script_path,
                "--width", str(w),
                "--height", str(h),
                "--conf", str(conf),
                "--model", model_path
            ]

            logger.info(f"Komut: {' '.join(cmd)}")

            external_ai_process = subprocess.Popen(
                cmd,
                env=env,
                preexec_fn=os.setsid
            )

            new_state = {'is_running': True, 'last_start': start_clicks, 'last_stop': last_stop}

            return (
                dbc.Alert(f"Pencere Açıldı! Web kamerası devre dışı.", color="success"),
                True, False, new_state, "Pencere Aktif ✓"
            )

        except Exception as e:
            logger.error(f"Process başlatma hatası: {e}")
            hardware_manager.resume_camera_usage()
            return (dbc.Alert(f"Hata: {e}", color="danger"), False, True, state, "Hata ✗")

    # --- DURDURMA ---
    if stop_clicks > last_stop:
        logger.info("🛑 AI Penceresi Kapatılıyor...")

        cleanup_external_process()  # ✅ Use improved cleanup function

        # KAMERAYI SERBEST BIRAK
        logger.info("Kamera web arayüzü için yeniden başlatılıyor...")
        time.sleep(1)
        hardware_manager.resume_camera_usage()

        new_state = {'is_running': False, 'last_start': last_start, 'last_stop': stop_clicks}

        return (
            dbc.Alert("Pencere Kapatıldı. Kamera Web'e döndü.", color="info"),
            False, True, new_state, "AI Kapalı"
        )

    return no_update, no_update, no_update, state, "Beklemede..."


# --- AI Vision Single Shot (FIXED) ---
@app.callback(
    [Output('ai-processed-image', 'src'),
     Output('yolo-count', 'children'), Output('face-count', 'children'),
     Output('motion-count', 'children'), Output('qr-count', 'children'),
     Output('detection-list', 'children')],
    Input('single-ai-snapshot-btn', 'n_clicks'),
    [State('ai-modules-checklist', 'value'), State('resolution-select-radio', 'value'),
     State('yolo-confidence-slider', 'value'), State('motion-threshold-slider', 'value'),
     State('ai-processing-state', 'data'), State('yolo-model-dropdown', 'value')],
    prevent_initial_call=True
)
def single_ai_snapshot(n, modules, res_str, yolo_conf, motion_thresh, ai_state, model_name):
    # ✅ FIXED: Proper no_update for all outputs
    if not n or not modules:
        return no_update, no_update, no_update, no_update, no_update, no_update

    # Harici pencere kontrolü
    if ai_state and ai_state.get('is_running', False):
        return (
            "", "HATA", "HATA", "HATA", "HATA",
            [dbc.Alert("Harici AI Penceresi açıkken tek çekim yapılamaz. Önce pencereyi kapatın.", color="danger")]
        )

    # Modülleri yükle
    for m in modules:
        if m == 'yolo':
            AIConfig.YOLO_MODEL = model_name
            AIConfig.YOLO_MODEL_PATH = AIConfig.YOLO_MODEL_DIR / model_name
            ai_vision_manager.yolo_model = None  # Force reload
            ai_vision_manager.initialize_module('yolo', confidence=yolo_conf)
        elif m == 'motion':
            ai_vision_manager.initialize_module('motion', threshold=motion_thresh)
        else:
            ai_vision_manager.initialize_module(m)

    w, h = map(int, res_str.split('x'))

    # ✅ IMPROVED: Set resolution for accurate distance calculation
    ai_vision_manager.set_resolution(w, h)

    # Kameradan kare al
    frame = hardware_manager.capture_frame(resolution=(w, h), framerate=30)

    if frame is None:
        return "", "!", "!", "!", "!", [dbc.Alert("Kare alınamadı (Kamera meşgul olabilir).", color="warning")]

    # AI İşle
    processed, results = ai_vision_manager.process_frame(frame, modules=modules, draw_results=True)
    b64 = image_to_base64(processed, quality=85)

    stats = results.get('stats', {})
    dets = results.get('detections', [])

    det_list = [html.Div(f"{d.label}: {d.confidence:.2f} | {d.distance_cm}cm") for d in dets[:10]]
    if not det_list: det_list = "Nesne bulunamadı."

    return b64, f"YOLO: {stats.get('yolo_objects', 0)}", f"Face: {stats.get('faces', 0)}", \
        f"Motion: {stats.get('motion_regions', 0)}", f"QR: {stats.get('qr_codes', 0)}", det_list


# (Rest of callbacks remain the same - only showing critical fixes above)
# ... [Include all other callbacks from original file] ...

if __name__ == '__main__':
    logger.info("Application starting...")