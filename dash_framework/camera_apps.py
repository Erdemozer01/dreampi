# camera_dash_app.py - Raspberry Pi 5 OV5647 130° Kamera Kontrol Uygulaması
# Version 3.3 - ctx/LookupError hatası için 'split callback' formülü

import os
import sys
import time
import logging
import signal
import atexit
import math
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

import dash
from django_plotly_dash import DjangoDash

# ----------------------------------------------------------------------------
# HATA DÜZELTMESİ (Yeni Formül):
# 'django_plotly_dash' ile 'ctx' veya 'callback_context' kullanımı 'LookupError'
# hatasına neden oluyor.
# Bu formülde, 'ctx' KULLANIMINI TAMAMEN TERK EDİYORUZ.
# 'ctx' gerektiren birleşik callback'ler yerine, her Input için
# ayrı callback'ler oluşturacağız.

from dash import (
    html, dcc, Output, Input, State, ALL, MATCH, no_update
)
# 'ctx' VEYA 'callback_context' İLE İLGİLİ TÜM IMPORTLAR KALDIRILDI.
from dash.exceptions import PreventUpdate
# ----------------------------------------------------------------------------

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from django.utils import timezone
from django.db import transaction

# Kendi modüllerimiz
from .config import (
    CameraConfig, MotorConfig, SensorConfig, AppConfig,
    DjangoConfig, LogConfig, PerformanceConfig, AIConfig
)
from .hardware_manager import (
    CAMERA_AVAILABLE, GPIO_AVAILABLE, hardware_manager,
    MotorCommandQueue, AdaptiveSensorReader
)
from .utils import (
    image_to_base64, safe_update_store, limit_list_size,
    format_distance, get_photo_metadata, create_scan_point,
    calculate_3d_position_with_fov, validate_resolution,
    ImageProcessor, StoreManager, PerformanceMonitor,
    frame_buffer, image_processor, store_manager, performance_monitor
)

# Django modeli
try:
    from scanner.models import CameraCapture, Scan, ScanPoint, SystemLog, AIModelConfiguration
    DJANGO_MODEL_AVAILABLE = True
    logging.info("✓ Django modelleri başarıyla import edildi")
except ImportError:
    DJANGO_MODEL_AVAILABLE = False
    logging.warning("⚠ scanner.models bulunamadı. DB kaydı devre dışı")

# Logger
logger = logging.getLogger(__name__)

def cleanup():
    """Temizlik işlemleri"""
    logger.info("🧹 Temizlik başlatılıyor...")
    try:
        hardware_manager.cleanup_all()
        logger.info("✓ Donanım temizlendi")
    except Exception as e:
        logger.error(f"Temizlik hatası: {e}")
# ============================================================================
# SINYAL YAKALAMA
# ============================================================================

def signal_handler(signum, frame):
    """Ctrl+C veya kill sinyali yakalandığında temizlik yap"""
    logger.info(f"Sinyal yakalandı: {signum}, temizlik yapılıyor...")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============================================================================
# DASH UYGULAMASI
# ============================================================================

app = DjangoDash(
    AppConfig.APP_NAME,
    external_stylesheets=[
        dbc.themes.CYBORG if AppConfig.BOOTSTRAP_THEME else dbc.themes.BOOTSTRAP,
        AppConfig.FONT_AWESOME
    ]
)

app.css.append_css({
    "external_url": "https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css"
})

# !!! ÖNERİLEN EKLEME BURASI !!!
# -------------------------------------------------------------
# UYGULAMA BAŞLAMADAN TÜM DONANIMLARI BAŞLAT
# -------------------------------------------------------------
logger.info("Donanım Yöneticisi (Hardware Manager) başlatılıyor...")
init_results = hardware_manager.initialize_all()
logger.info(f"Donanım başlatma sonuçları: {init_results}")
# -------------------------------------------------------------

# ============================================================================
# UI KOMPONENTLERİ
# ============================================================================

# --- NAVBAR ---
navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("Ana Sayfa", href="/", external_link=True)),
        dbc.NavItem(dbc.NavLink(
            [html.I(className="fa-solid fa-video me-2"), "Kamera"],
            href="/camera/",
            external_link=True
        )),
        dbc.NavItem(dbc.NavLink(
            [html.I(className="fa-solid fa-chart-line me-2"), "Metrikler"],
            href="#",
            id="metrics-link"
        )),
        dbc.NavItem(dbc.NavLink("Admin", href="/admin/", external_link=True, target="_blank"))
    ],
    brand=[
        html.Img(src="/static/logo.png", height="30px", className="me-2"),
        f"Dream Pi v{AppConfig.APP_VERSION} - OV5647 130°"
    ],
    brand_href="/",
    color="dark",
    dark=True,
    fluid=True,
    className="mb-4 animate__animated animate__fadeInDown"
)

# --- KAMERA KONTROL PANELİ ---
camera_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-camera me-2"),
        "OV5647 130° Kamera Kontrol"
    ], className="bg-primary text-white"),
    dbc.CardBody([
        # Donanım Durumu
        html.Div([
            html.H6([html.I(className="fa-solid fa-microchip me-2"), "Donanım:"], className="fw-bold"),
            html.Div(id='camera-status', children=[
                dbc.Badge("Kontrol ediliyor...", color="warning", className="me-2 pulse"),
            ], className="mb-3")
        ]),

        # Kamera Bilgileri
        html.Div([
            dbc.Row([
                dbc.Col([
                    html.Small("Model:", className="text-muted"),
                    html.Div("OV5647", className="fw-bold")
                ], width=6),
                dbc.Col([
                    html.Small("FOV:", className="text-muted"),
                    html.Div("130° Yatay", className="fw-bold")
                ], width=6),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Small("Çözünürlük:", className="text-muted"),
                    dcc.Dropdown(
                        id='resolution-dropdown',
                        options=CameraConfig.RESOLUTIONS,
                        value='1296x972',
                        className="mt-1"
                    )
                ], width=12),
            ])
        ], className="mb-3"),

        html.Hr(),

        # Lens Düzeltme
        html.Div([
            dbc.Switch(
                id='lens-correction-switch',
                label="130° Lens Düzeltme",
                value=CameraConfig.ENABLE_LENS_CORRECTION,
                className="mb-2"
            ),
            html.Div(id='lens-status', className="text-muted small")
        ]),

        html.Hr(),

        # Efektler
        html.Div([
            html.Label([html.I(className="fa-solid fa-wand-magic-sparkles me-2"), "Efektler:"],
                       className="fw-bold mb-2"),
            dcc.Dropdown(
                id='effect-dropdown',
                options=[
                    {'label': 'Normal', 'value': 'none'},
                    {'label': 'Gri Tonlama', 'value': 'grayscale'},
                    {'label': 'Kenar Algılama', 'value': 'edges'},
                    {'label': 'Ters Çevir', 'value': 'invert'},
                    {'label': 'Bulanıklaştır', 'value': 'blur'},
                    {'label': 'Keskinleştir', 'value': 'sharpen'},
                    {'label': 'HDR', 'value': 'hdr'},
                    {'label': 'Gece Görüşü', 'value': 'night_vision'},
                    {'label': 'Termal', 'value': 'thermal'},
                ],
                value='none',
                className="mb-3"
            )
        ]),

        html.Hr(),

        # Fotoğraf Çekme
        html.Div([
            html.H6([html.I(className="fa-solid fa-camera-retro me-2"), "Fotoğraf"], className="fw-bold mb-2"),
            dbc.ButtonGroup([
                dbc.Button(
                    [html.I(className="fa-solid fa-camera me-2"), "Çek"],
                    id='capture-photo-btn',
                    color="success",
                    className="flex-fill"
                ),
                dbc.Button(
                    [html.I(className="fa-solid fa-images me-2"), "Seri (5x)"],
                    id='burst-photo-btn',
                    color="info",
                    className="flex-fill"
                ),
            ], className="w-100 mb-2"),
            html.Div(id='photo-status', className="text-center text-muted")
        ]),
    ])
], className="mb-3 animate__animated animate__fadeInLeft")

# --- MOTOR KONTROL PANELİ ---
motor_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-gear me-2"),
        "Step Motor Kontrol"
    ], className="bg-secondary text-white"),
    dbc.CardBody([
        # Hız Profili Seçimi
        html.Div([
            html.Label("Hız Profili:", className="fw-bold"),
            dbc.RadioItems(
                id='speed-profile-radio',
                options=[
                    {'label': '🐌 Yavaş', 'value': 'slow'},
                    {'label': '🚶 Normal', 'value': 'normal'},
                    {'label': '🏃 Hızlı', 'value': 'fast'},
                    {'label': '🎯 Tarama', 'value': 'scan'},
                ],
                value='normal',
                inline=True,
                className="mb-3"
            )
        ]),

        # Pan Kontrol
        html.Div([
            html.Label([html.I(className="fa-solid fa-arrows-left-right me-2"), "Pan (Yatay):"],
                       className="fw-bold"),
            dbc.ButtonGroup([
                dbc.Button("⬅️ -90°", id={'type': 'motor-btn', 'index': -90}, color="primary", size="sm"),
                dbc.Button("◀️ -10°", id={'type': 'motor-btn', 'index': -10}, color="info", size="sm"),
                dbc.Button("⏸️ 0°", id={'type': 'motor-btn', 'index': 0}, color="secondary", size="sm"),
                dbc.Button("▶️ +10°", id={'type': 'motor-btn', 'index': 10}, color="info", size="sm"),
                dbc.Button("➡️ +90°", id={'type': 'motor-btn', 'index': 90}, color="primary", size="sm"),
            ], className="w-100 mb-2"),

            dcc.Slider(
                id='pan-slider',
                min=MotorConfig.MIN_ANGLE,
                max=MotorConfig.MAX_ANGLE,
                step=MotorConfig.FINE_STEP,
                value=0,
                marks={
                    -180: '-180°', -135: '-135°', -90: '-90°', -45: '-45°',
                    0: '0°',
                    45: '45°', 90: '90°', 135: '135°', 180: '180°'
                },
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            ),
        ]),

        # Kalibrasyon ve Presets
        html.Div([
            html.H6("Hızlı Erişim:", className="fw-bold mb-2"),
            dbc.ButtonGroup([
                dbc.Button(
                    [html.I(className="fa-solid fa-home me-1"), "Home"],
                    id='home-btn',
                    color="warning",
                    size="sm"
                ),
                dbc.Button(
                    [html.I(className="fa-solid fa-expand me-1"), "Tarama"],
                    id='scan-btn',
                    color="success",
                    size="sm"
                ),
                dbc.Button(
                    [html.I(className="fa-solid fa-stop me-1"), "Dur"],
                    id='stop-motor-btn',
                    color="danger",
                    size="sm"
                ),
            ], className="w-100"),
        ]),

        # Motor Durumu
        html.Div([
            html.Hr(),
            html.H6("Motor Durumu:", className="fw-bold"),
            html.Div(id='motor-status-display', className="small")
        ])
    ])
], className="mb-3 animate__animated animate__fadeInLeft animation-delay-1")

# --- VIDEO KONTROL PANELİ ---
video_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-video me-2"),
        "Video Kayıt"
    ], className="bg-danger text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                dbc.Button(
                    [html.I(className="fa-solid fa-circle me-2"), "Kayıt Başlat"],
                    id='start-record-btn',
                    color="danger",
                    disabled=not CAMERA_AVAILABLE,
                    className="w-100"
                ),
            ], width=6),
            dbc.Col([
                dbc.Button(
                    [html.I(className="fa-solid fa-stop me-2"), "Durdur"],
                    id='stop-record-btn',
                    color="secondary",
                    disabled=True,
                    className="w-100"
                ),
            ], width=6),
        ], className="mb-2"),
        html.Div(id='video-status', className="text-center"),
        dbc.Progress(id="recording-progress", value=0, striped=True, animated=True, className="mt-2")
    ])
], className="mb-3 animate__animated animate__fadeInLeft animation-delay-2")

# --- SENSÖR KONTROL PANELİ ---
sensor_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-satellite-dish me-2"),
        "Ultrasonik Sensör"
    ], className="bg-info text-white"),
    dbc.CardBody([
        # Sensör Kontrolü
        dbc.Row([
            dbc.Col([
                dbc.Switch(
                    id='sensor-switch',
                    label="Canlı Okuma",
                    value=False,
                    className="mb-2"
                ),
            ], width=6),
            dbc.Col([
                dbc.RadioItems(
                    id='sensor-mode',
                    options=[
                        {'label': 'Normal', 'value': 'normal'},
                        {'label': 'Adaptif', 'value': 'adaptive'},
                    ],
                    value='adaptive',
                    inline=True
                )
            ], width=6),
        ]),

        html.Hr(),

        # Anlık Mesafe Göstergesi
        html.Div([
            html.H4(id='current-distance', children="Kapalı", className="text-center text-info display-6"),
            html.Div(id='distance-chart', style={'height': '100px'})
        ]),

        html.Hr(),

        # Tarama Kontrolü
        html.Div([
            dbc.ButtonGroup([
                dbc.Button(
                    [html.I(className="fa-solid fa-play me-1"), "3D Tarama"],
                    id='start-3d-scan-btn',
                    color="success",
                    size="sm"
                ),
                dbc.Button(
                    [html.I(className="fa-solid fa-trash me-1"), "Temizle"],
                    id='clear-scan-btn',
                    color="danger",
                    size="sm"
                ),
            ], className="w-100")
        ])
    ])
], className="mb-3 animate__animated animate__fadeInLeft animation-delay-3")

# --- İSTATİSTİK KARTI ---
stats_card = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-chart-simple me-2"),
        "İstatistikler"
    ], className="bg-dark text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.H6("Motor Açısı:", className="text-muted mb-1"),
                html.H4(id='current-pan-angle', children="0°", className="mb-0 text-primary")
            ], className="text-center border-end", width=6),
            dbc.Col([
                html.H6("FPS:", className="text-muted mb-1"),
                html.H4(id='current-fps', children="0", className="mb-0 text-success")
            ], className="text-center", width=6),
        ], className="mb-3"),

        dbc.Row([
            dbc.Col([
                html.Div([
                    html.I(className="fa-solid fa-camera fa-2x text-info mb-2"),
                    html.H5(id='photo-count', children="0"),
                    html.Small("Fotoğraf", className="text-muted")
                ], className="text-center")
            ], width=4),
            dbc.Col([
                html.Div([
                    html.I(className="fa-solid fa-map-pin fa-2x text-warning mb-2"),
                    html.H5(id='scan-count', children="0"),
                    html.Small("Tarama", className="text-muted")
                ], className="text-center")
            ], width=4),
            dbc.Col([
                html.Div([
                    html.I(className="fa-solid fa-memory fa-2x text-danger mb-2"),
                    html.H5(id='buffer-count', children="0"),
                    html.Small("Buffer", className="text-muted")
                ], className="text-center")
            ], width=4),
        ])
    ])
], className="animate__animated animate__fadeInLeft animation-delay-4")

# --- PERFORMANS MONİTÖR (MODAL) ---
performance_modal = dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle("Sistem Performansı")),
    dbc.ModalBody([
        dcc.Graph(id='performance-graph'),
        html.Hr(),
        html.Div(id='performance-details')
    ]),
    dbc.ModalFooter(
        dbc.Button("Kapat", id="close-performance", className="ms-auto", n_clicks=0)
    ),
], id="performance-modal", size="xl", is_open=False)

# --- ANA GÖRÜNTÜLEME TABLERİ ---
visualization_tabs = dbc.Tabs([
    dbc.Tab(
        html.Div([
            # Kamera kontrolleri overlay
            html.Div([
                dbc.ButtonGroup([
                    dbc.Button(
                        html.I(className="fa-solid fa-expand"),
                        id='fullscreen-btn',
                        color="secondary",
                        size="sm",
                        className="me-1"
                    ),
                    dbc.Button(
                        html.I(className="fa-solid fa-crosshairs"),
                        id='crosshair-btn',
                        color="secondary",
                        size="sm",
                        className="me-1"
                    ),
                    dbc.Button(
                        html.I(className="fa-solid fa-grid"),
                        id='grid-btn',
                        color="secondary",
                        size="sm"
                    ),
                ], className="position-absolute top-0 end-0 m-2", style={"z-index": 1000}),
            ]),

            # Kamera görüntüsü
            dcc.Loading(
                id="loading-camera",
                type="default",
                children=[
                    html.Div([
                        html.Img(
                            id='camera-feed',
                            style={
                                'width': '100%',
                                'height': 'auto',
                                'maxHeight': '70vh',
                                'objectFit': 'contain',
                                'border': '2px solid #1a1a1a',
                                'borderRadius': '8px',
                                'position': 'relative'
                            }
                        ),
                        # Overlay elementler (crosshair, grid vb)
                        html.Div(id='camera-overlay', style={
                            'position': 'absolute',
                            'top': 0,
                            'left': 0,
                            'width': '100%',
                            'height': '100%',
                            'pointerEvents': 'none'
                        })
                    ], style={'position': 'relative'})
                ]
            )
        ], style={'padding': '20px'}),
        label="📹 Canlı Görüntü",
        tab_id="tab-camera",
        label_style={"font-weight": "bold"}
    ),

    dbc.Tab(
        dcc.Graph(
            id='camera-3d-view',
            style={'height': '75vh'},
            config={
                'displayModeBar': True,
                'displaylogo': False,
                'modeBarButtonsToRemove': ['pan2d', 'lasso2d', 'select2d'],
                'toImageButtonOptions': {
                    'format': 'png',
                    'filename': 'scan_3d',
                    'height': 1080,
                    'width': 1920,
                    'scale': 1
                }
            }
        ),
        label="🗺️ 3D Tarama",
        tab_id="tab-3d",
        label_style={"font-weight": "bold"}
    ),

    dbc.Tab(
        html.Div(id='photo-gallery', children=[
            html.P("Henüz fotoğraf çekilmedi.", className="text-center text-muted mt-5")
        ], style={'padding': '20px', 'maxHeight': '75vh', 'overflowY': 'auto'}),
        label="📸 Galeri",
        tab_id="tab-gallery",
        label_style={"font-weight": "bold"}
    ),

    dbc.Tab(
        html.Div([
            dcc.Graph(id='metrics-chart', style={'height': '35vh'}),
            html.Hr(),
            dcc.Graph(id='sensor-history-chart', style={'height': '35vh'})
        ], style={'padding': '20px'}),
        label="📊 Metrikler",
        tab_id="tab-metrics",
        label_style={"font-weight": "bold"}
    ),
], id="camera-tabs", active_tab="tab-camera", className="animate__animated animate__fadeIn")

# ============================================================================
# ANA LAYOUT
# ============================================================================

app.layout = html.Div([
    navbar,

    dbc.Container([
        # Alerts container
        html.Div(id='alerts-container'),

        dbc.Row([
            # Sol Panel - Kontroller
            dbc.Col([
                camera_control_panel,
                motor_control_panel,
                video_control_panel,
                sensor_control_panel,
                stats_card
            ], md=4, lg=3),

            # Sağ Panel - Görüntüleme
            dbc.Col([
                visualization_tabs
            ], md=8, lg=9)
        ])
    ], fluid=True),

    # Modal
    performance_modal,

    # Intervals
    dcc.Interval(id='camera-interval', interval=AppConfig.CAMERA_INTERVAL_MS, n_intervals=0),
    dcc.Interval(id='motor-update-interval', interval=AppConfig.MOTOR_UPDATE_INTERVAL_MS, n_intervals=0),
    dcc.Interval(id='metrics-interval', interval=AppConfig.METRICS_INTERVAL_MS, n_intervals=0),

    # Stores
    dcc.Store(id='camera-store', data={
        'photo_count': 0,
        'photos': [],
        'sensor_enabled': False,
        'scan_points': [],
        'is_recording': False,
        'video_filename': None,
        'hardware_initialized': False,
        'lens_correction': CameraConfig.ENABLE_LENS_CORRECTION,
        'camera_model': CameraConfig.CAMERA_MODEL,
        'fov': CameraConfig.FOV_HORIZONTAL,
        'metrics_history': [],
        'sensor_history': []
    }),

    dcc.Store(id='performance-store', data={
        'fps_history': [],
        'cpu_history': [],
        'memory_history': [],
        'temperature_history': []
    }),

], style={'background-color': '#0a0a0a', 'min-height': '100vh'})

# --- KAMERA DURUMU CALLBACK ---
@app.callback(
    Output('camera-status', 'children'),
    Input('camera-interval', 'n_intervals')
)
def update_camera_status(n):
    """Kamera donanım durumunu güncelle"""
    if CAMERA_AVAILABLE:
        return dbc.Badge("✓ OV5647 Aktif", color="success", className="me-2")
    else:
        return dbc.Badge("⚠ Simülasyon Modu", color="warning", className="me-2 pulse")


# --- KAMERA GÖRÜNTÜSÜ CALLBACK ---
@app.callback(
    Output('camera-feed', 'src'),
    Input('camera-interval', 'n_intervals'),
    State('effect-dropdown', 'value'),
    State('lens-correction-switch', 'value'),
    State('resolution-dropdown', 'value')
)
def update_camera_feed(n, effect, lens_correction, resolution_str):
    """Canlı kamera görüntüsünü güncelle"""
    try:
        # Çözünürlük ayarla (gerekirse)
        width, height = validate_resolution(resolution_str)

        # Frame yakala
        frame = hardware_manager.capture_frame(apply_lens_correction=lens_correction)

        if frame is None:
            raise PreventUpdate

        # Efekt uygula
        if effect and effect != 'none':
            frame = image_processor.apply_effect(frame, effect)

        # Base64'e çevir
        img_base64 = image_to_base64(
            frame,
            quality=CameraConfig.IMAGE_QUALITY,
            apply_lens_correction=False  # Zaten uygulandı
        )

        return img_base64

    except Exception as e:
        logger.error(f"Kamera feed hatası: {e}")
        raise PreventUpdate


# --- FOTOĞRAF ÇEK CALLBACK ---
@app.callback(
    [Output('photo-status', 'children'),
     Output('camera-store', 'data')],
    Input('capture-photo-btn', 'n_clicks'),
    [State('camera-store', 'data'),
     State('effect-dropdown', 'value'),
     State('lens-correction-switch', 'value')],
    prevent_initial_call=True
)
def capture_photo(n_clicks, store_data, effect, lens_correction):
    """Fotoğraf çek ve kaydet"""
    if not n_clicks:
        raise PreventUpdate

    try:
        # Frame yakala
        frame = hardware_manager.capture_frame(apply_lens_correction=lens_correction)

        if frame is None:
            return dbc.Alert("❌ Fotoğraf çekilemedi", color="danger"), no_update

        # Efekt uygula
        if effect != 'none':
            frame = image_processor.apply_effect(frame, effect)

        # Base64'e çevir
        img_base64 = image_to_base64(frame, quality=90)

        # Metadata
        motor_angle = hardware_manager.get_motor_angle()
        distance = hardware_manager.get_current_distance()
        distance_str = format_distance(distance) if distance else "N/A"

        photo_metadata = get_photo_metadata(
            angle=motor_angle,
            distance=distance_str,
            effect=effect,
            timestamp=timezone.now().isoformat(),
            additional_data={
                'lens_correction': lens_correction,
                'resolution': CameraConfig.DEFAULT_RESOLUTION
            }
        )

        # Store'a ekle
        photos = store_data.get('photos', [])
        photos.append({
            'image': img_base64,
            'metadata': photo_metadata
        })

        # Django model'e kaydet
        if DJANGO_MODEL_AVAILABLE:
            try:
                CameraCapture.objects.create(
                    base64_image=img_base64,
                    effect=effect,
                    pan_angle=motor_angle,
                    distance_info=distance_str
                )
                logger.info("✓ Fotoğraf veritabanına kaydedildi")
            except Exception as e:
                logger.error(f"DB kayıt hatası: {e}")

        # Store güncelle
        updated_store = safe_update_store(store_data, {
            'photos': photos,
            'photo_count': len(photos)
        })

        return dbc.Alert(f"✓ Fotoğraf çekildi ({len(photos)})", color="success"), updated_store

    except Exception as e:
        logger.error(f"Fotoğraf çekme hatası: {e}")
        return dbc.Alert(f"❌ Hata: {str(e)}", color="danger"), no_update


# ============================================================================
# --- MOTOR KONTROL CALLBACK'LERİ (YENİ FORMÜL) ---
# Orijinal 'control_motor' fonksiyonunu 4 parçaya ayırıyoruz.
# Bu, 'ctx' ihtiyacını ortadan kaldırır.
# ÖNEMLİ: Dash 2.0+ (allow_duplicate=True) gereklidir.
# ============================================================================

# 1. 'pan-slider' için motor callback'i
@app.callback(
    Output('motor-status-display', 'children'),
    Input('pan-slider', 'value'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_slider(slider_value, speed_profile):
    """Motor kontrolü - Slider"""
    try:
        hardware_manager.move_to_angle(slider_value, speed_profile=speed_profile, priority=5)
        return html.Div([
            html.I(className="fa-solid fa-gauge-high text-primary me-2"),
            f"Hedef: {slider_value:.1f}°"
        ])
    except Exception as e:
        logger.error(f"Motor (slider) hatası: {e}")
        return html.Div([
            html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"),
            f"Hata: {str(e)}"
        ])

# 2. 'stop-motor-btn' için motor callback'i
@app.callback(
    Output('motor-status-display', 'children', allow_duplicate=True),
    Input('stop-motor-btn', 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_stop(n_clicks):
    """Motor kontrolü - Stop"""
    if not n_clicks:
        raise PreventUpdate
    try:
        hardware_manager.cancel_movement()
        return html.Div([
            html.I(className="fa-solid fa-circle-pause text-warning me-2"),
            "Motor durduruldu"
        ])
    except Exception as e:
        logger.error(f"Motor (stop) hatası: {e}")
        return html.Div([
            html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"),
            f"Hata: {str(e)}"
        ])

# 3. 'home-btn' için motor callback'i
@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input('home-btn', 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_home(n_clicks):
    """Motor kontrolü - Home"""
    if not n_clicks:
        raise PreventUpdate
    try:
        hardware_manager.move_to_angle(0, speed_profile='normal', priority=1)
        return (
            html.Div([
                html.I(className="fa-solid fa-home text-success me-2"),
                "Home pozisyonuna gidiliyor..."
            ]),
            0  # Slider'ı 0'a getir
        )
    except Exception as e:
        logger.error(f"Motor (home) hatası: {e}")
        return (
            html.Div([
                html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"),
                f"Hata: {str(e)}"
            ]),
            no_update
        )


# 4. Motor butonları için DOĞRU ÇÖZÜM
# UI'daki butonlar sayısal index kullanıyor: -90, -10, 0, 10, 90
# Callback'ler bu sayısal değerleri dinlemeli

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': -90}, 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_left_90(n_clicks):
    """⬅️ -90° Buton"""
    if not n_clicks:
        raise PreventUpdate
    try:
        hardware_manager.move_to_angle(-90, speed_profile='fast', priority=5)
        return (
            html.Div([
                html.I(className="fa-solid fa-angles-left text-primary me-2"),
                "⬅️ -90° hedef"
            ]),
            -90  # Slider'ı güncelle
        )
    except Exception as e:
        logger.error(f"Motor (-90°) hatası: {e}")
        return (
            html.Div([html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"), f"Hata: {str(e)}"]),
            no_update
        )

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': -10}, 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_left_10(n_clicks):
    """◀️ -10° Buton"""
    if not n_clicks:
        raise PreventUpdate
    try:
        current_angle = hardware_manager.get_motor_angle()
        new_angle = current_angle - 10
        hardware_manager.move_to_angle(new_angle, speed_profile='normal', priority=5)
        return (
            html.Div([
                html.I(className="fa-solid fa-arrow-left text-info me-2"),
                f"◀️ {new_angle:.1f}° hedef"
            ]),
            new_angle  # Slider'ı güncelle
        )
    except Exception as e:
        logger.error(f"Motor (-10°) hatası: {e}")
        return (
            html.Div([html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"), f"Hata: {str(e)}"]),
            no_update
        )

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': 0}, 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_center(n_clicks):
    """⏸️ 0° (Center) Buton"""
    if not n_clicks:
        raise PreventUpdate
    try:
        hardware_manager.move_to_angle(0, speed_profile='normal', priority=5)
        return (
            html.Div([
                html.I(className="fa-solid fa-circle-dot text-secondary me-2"),
                "⏸️ 0° (Merkez)"
            ]),
            0  # Slider'ı güncelle
        )
    except Exception as e:
        logger.error(f"Motor (0°) hatası: {e}")
        return (
            html.Div([html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"), f"Hata: {str(e)}"]),
            no_update
        )

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': 10}, 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_right_10(n_clicks):
    """▶️ +10° Buton"""
    if not n_clicks:
        raise PreventUpdate
    try:
        current_angle = hardware_manager.get_motor_angle()
        new_angle = current_angle + 10
        hardware_manager.move_to_angle(new_angle, speed_profile='normal', priority=5)
        return (
            html.Div([
                html.I(className="fa-solid fa-arrow-right text-info me-2"),
                f"▶️ {new_angle:.1f}° hedef"
            ]),
            new_angle  # Slider'ı güncelle
        )
    except Exception as e:
        logger.error(f"Motor (+10°) hatası: {e}")
        return (
            html.Div([html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"), f"Hata: {str(e)}"]),
            no_update
        )

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': 90}, 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_right_90(n_clicks):
    """➡️ +90° Buton"""
    if not n_clicks:
        raise PreventUpdate
    try:
        hardware_manager.move_to_angle(90, speed_profile='fast', priority=5)
        return (
            html.Div([
                html.I(className="fa-solid fa-angles-right text-primary me-2"),
                "➡️ +90° hedef"
            ]),
            90  # Slider'ı güncelle
        )
    except Exception as e:
        logger.error(f"Motor (+90°) hatası: {e}")
        return (
            html.Div([html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"), f"Hata: {str(e)}"]),
            no_update
        )
        return html.Div([
            html.I(className="fa-solid fa-angles-right text-primary me-2"),
            "➡️ +90° hedef"
        ])
    except Exception as e:
        logger.error(f"Motor (+90°) hatası: {e}")
        return html.Div([html.I(className="fa-solid fa-triangle-exclamation text-danger me-2"), f"Hata: {str(e)}"])
# ============================================================================
# --- 'ctx' KULLANAN ORİJİNAL CALLBACK (Referans için) ---
# (Bu callback 'LookupError' veriyordu ve yukarıdaki ile değiştirildi)
# ============================================================================
# @app.callback(
#     Output('motor-status-display', 'children'),
#     [Input({'type': 'motor-btn', 'index': ALL}, 'n_clicks'),
#      Input('pan-slider', 'value'),
#      Input('home-btn', 'n_clicks'),
#      Input('stop-motor-btn', 'n_clicks')],
#     State('speed-profile-radio', 'value'),
#     prevent_initial_call=True
# )
# def control_motor(btn_clicks, slider_value, home_clicks, stop_clicks, speed_profile):
#     """Motor kontrolü"""
#     triggered_id = ctx.triggered_id # <--- HATA BURADA
#
#     try:
#         if triggered_id == 'stop-motor-btn':
#             # ...
#         elif triggered_id == 'home-btn':
#             # ...
#         elif isinstance(triggered_id, dict) and triggered_id.get('type') == 'motor-btn':
#             # ...
#         elif triggered_id == 'pan-slider':
#             # ...
#     except Exception as e:
#         # ...
#     raise PreventUpdate
# ============================================================================


# --- SENSÖR OKUMA CALLBACK ---
@app.callback(
    [Output('current-distance', 'children'),
     Output('sensor-switch', 'disabled')],
    [Input('metrics-interval', 'n_intervals'),
     Input('sensor-switch', 'value')]
)
def update_sensor_reading(n, sensor_enabled):
    """Sensör okumasını güncelle"""
    if sensor_enabled:
        # Sensör başlatılmamışsa önce başlat
        if not hardware_manager._initialized.get('sensor', False):
            logger.info("Sensör başlatılıyor (UI'den tetiklendi)...")
            init_success = hardware_manager.initialize_sensor()

            if not init_success:
                return "❌ Sensör Başlatılamadı", True  # Switch'i devre dışı bırak

        if not hardware_manager.is_sensor_active():
            start_success = hardware_manager.start_continuous_sensor_reading()

            if not start_success:
                return "⚠️ Sensör Hatası", False

        distance = hardware_manager.get_current_distance()

        if distance is not None:
            formatted = format_distance(distance)
            return formatted, False
        else:
            return "Okuma Hatası", False
    else:
        if hardware_manager.is_sensor_active():
            hardware_manager.stop_continuous_sensor_reading()

        return "Kapalı", False

# --- İSTATİSTİKLER CALLBACK ---
@app.callback(
    [Output('current-pan-angle', 'children'),
     Output('current-fps', 'children'),
     Output('photo-count', 'children'),
     Output('scan-count', 'children'),
     Output('buffer-count', 'children')],
    Input('metrics-interval', 'n_intervals'),
    State('camera-store', 'data')
)
def update_statistics(n, store_data):
    """İstatistikleri güncelle"""
    try:
        # Motor açısı
        motor_angle = hardware_manager.get_motor_angle()

        # FPS hesaplama
        status = hardware_manager.get_system_status()
        fps = status['metrics'].get('fps', 0)

        # Sayaçlar
        photo_count = store_data.get('photo_count', 0)
        scan_points = len(store_data.get('scan_points', []))
        buffer_size = status['camera'].get('buffer_size', 0)

        return (
            f"{motor_angle:.1f}°",
            f"{fps:.1f}",
            str(photo_count),
            str(scan_points),
            str(buffer_size)
        )

    except Exception as e:
        logger.error(f"İstatistik güncelleme hatası: {e}")
        return "0°", "0", "0", "0", "0"


# --- 3D TARAMA CALLBACK ---
@app.callback(
    Output('camera-3d-view', 'figure'),
    Input('metrics-interval', 'n_intervals'),
    State('camera-store', 'data')
)
def update_3d_view(n, store_data):
    """3D tarama görselleştirmesi"""
    scan_points = store_data.get('scan_points', [])

    if not scan_points:
        # Boş grafik
        fig = go.Figure()
        fig.add_annotation(
            text="Henüz tarama verisi yok",
            xref="paper", yref="paper",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=20, color="gray")
        )
        fig.update_layout(
            template="plotly_dark",
            height=600,
            title="3D Tarama Haritası"
        )
        return fig

    # 3D scatter plot
    x_coords = [p['x'] for p in scan_points]
    y_coords = [p['y'] for p in scan_points]
    z_coords = [p['z'] for p in scan_points]
    distances = [p['distance'] for p in scan_points]

    fig = go.Figure()

    fig.add_trace(go.Scatter3d(
        x=x_coords,
        y=y_coords,
        z=z_coords,
        mode='markers',
        marker=dict(
            size=5,
            color=distances,
            colorscale='Viridis',
            showscale=True,
            colorbar=dict(title="Mesafe (cm)")
        ),
        text=[f"({p['x']:.1f}, {p['y']:.1f}, {p['z']:.1f})" for p in scan_points],
        hovertemplate="<b>Konum:</b> %{text}<br><b>Mesafe:</b> %{marker.color:.1f} cm<extra></extra>"
    ))

    fig.update_layout(
        template="plotly_dark",
        height=700,
        title=f"3D Tarama Haritası ({len(scan_points)} nokta)",
        scene=dict(
            xaxis_title="X (cm)",
            yaxis_title="Y (cm)",
            zaxis_title="Z (cm)",
            aspectmode='data'
        )
    )

    return fig


# --- PERFORMANS MODAL CALLBACK ---
@app.callback(
    Output("performance-modal", "is_open"),
    [Input("metrics-link", "n_clicks"),
     Input("close-performance", "n_clicks")],
    State("performance-modal", "is_open"),
    prevent_initial_call=True
)
def toggle_performance_modal(open_clicks, close_clicks, is_open):
    """Performans modal'ını aç/kapat"""
    if open_clicks or close_clicks:
        return not is_open
    return is_open


# --- VIDEO KAYIT CALLBACK (CTX OLMADAN GÜNCELLENDİ) ---
@app.callback(
    [Output('start-record-btn', 'disabled'),
     Output('stop-record-btn', 'disabled'),
     Output('video-status', 'children')],
    [Input('start-record-btn', 'n_clicks'),
     Input('stop-record-btn', 'n_clicks')],
    [State('start-record-btn', 'disabled'),
     State('stop-record-btn', 'disabled')],
    prevent_initial_call=True
)
def control_video_recording(start_clicks, stop_clicks, start_disabled, stop_disabled):
    """Video kaydını kontrol et (ctx olmadan)"""

    # Hangi butonun tıklandığını anlamak için n_clicks değerlerini kontrol etmemiz gerekiyor
    # Bu basit bir senaryo olduğu için (sadece 2 buton), 'ctx' olmadan idare edebiliriz.
    # Ancak hangi butonun *en son* tıklandığını bilmemiz gerek.
    # Bu yüzden state'i (disabled durumu) kontrol etmek daha güvenli olabilir.

    # Eğer start'a tıklandıysa VE start butonu disabled değilse:
    if start_clicks and not start_disabled:
        # Video kayıt dosyası
        video_dir = Path("media/videos")
        video_dir.mkdir(parents=True, exist_ok=True)
        filename = video_dir / f"recording_{int(time.time())}.h264"

        success, message = hardware_manager.start_recording(str(filename))

        if success:
            # Start'ı disable et, Stop'u enable et
            return True, False, dbc.Alert(f"🔴 Kayıt yapılıyor: {filename.name}", color="danger")
        else:
            # Durum değişmedi
            return no_update, no_update, dbc.Alert(f"❌ Hata: {message}", color="danger")

    # Eğer stop'a tıklandıysa VE stop butonu disabled değilse:
    elif stop_clicks and not stop_disabled:
        success, message = hardware_manager.stop_recording()

        if success:
            # Start'ı enable et, Stop'u disable et
            return False, True, dbc.Alert(f"✓ {message}", color="success")
        else:
            # Durum değişmedi
            return no_update, no_update, dbc.Alert(f"❌ {message}", color="warning")

    raise PreventUpdate


# ============================================================================
# UYGULAMA BAŞLATMA
# ============================================================================

logger.info("="*60)
logger.info("DREAM PI KAMERA DASH UYGULAMASI YÜKLENDİ")
logger.info(f"Version: {AppConfig.APP_VERSION}")
logger.info(f"Kamera: {'OV5647 130°' if CAMERA_AVAILABLE else 'Simülasyon'}")
logger.info(f"GPIO: {'Aktif' if GPIO_AVAILABLE else 'Simülasyon'}")
logger.info("="*60)