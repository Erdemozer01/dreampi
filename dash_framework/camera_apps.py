# camera_dash_app.py - FINAL v3.18 (TÜM HATALAR DÜZELTİLDİ)
# Tam Manuel Kamera Kontrolü + AI Vision + Hatasız Callback Yapısı

import os
import sys
import time
import logging
import atexit
import json
import gc
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import hashlib
import base64
import io

from .ai_vision import ai_vision_manager

from .config import AIConfig

# GÖRSEL ANALİZ KÜTÜPHANELERİ
try:
    import cv2
    import numpy as np
    from skimage.metrics import structural_similarity as ssim
    from skimage.metrics import mean_squared_error
    import imagehash
    from PIL import Image
except ImportError:
    logger = logging.getLogger(__name__)
    logger.error("KRİTİK HATA: Gerekli kütüphaneler eksik.")
    logger.error("pip install scikit-image imagehash opencv-python-headless pillow")
    sys.exit(1)

import dash
from django_plotly_dash import DjangoDash

from dash import (
    html, dcc, Output, Input, State, ALL, MATCH, no_update, callback_context
)
from dash.exceptions import PreventUpdate

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from django.utils import timezone

# Django model import
try:
    from scanner.models import CameraCapture
except ImportError:
    from scanner.models import CameraCapture

from .config import (
    CameraConfig, MotorConfig, SensorConfig, AppConfig
)

from .hardware_manager import (
    GPIO_AVAILABLE, hardware_manager
)

from .utils import (
    safe_update_store,
    cleanup_old_store_data,
    format_distance,
    image_to_base64,
    split_data_uri,
    base64_data_to_images,
)

# Logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('dash_errors.log')
    ]
)
logger = logging.getLogger(__name__)


def cleanup():
    """Temizlik işlemleri (atexit için güvenli)"""
    logger.info("🧹 Temizlik başlatılıyor (atexit)...")
    try:
        # Thread pool'u (executor) kullanan cleanup_all() yerine
        # donanımları teker teker, sıralı olarak kapatıyoruz.
        # Bu, 'cannot schedule new futures after shutdown' hatasını önler.

        logger.info("Motor temizleniyor...")
        hardware_manager.cleanup_motor()

        logger.info("Sensör temizleniyor...")
        hardware_manager.cleanup_sensor()

        logger.info("Kamera temizleniyor...")
        hardware_manager.cleanup_camera()

        logger.info("✓ Donanım temizlendi")

    except Exception as e:
        # Kapanış sırasında oluşabilecek hataları logla
        logger.error(f"Kapanış (cleanup) hatası: {e}", exc_info=True)


atexit.register(cleanup)

# ============================================================================
# DASH UYGULAMASI
# ============================================================================

app = DjangoDash(
    AppConfig.APP_NAME,
    external_stylesheets=[
        dbc.themes.CYBORG,
        AppConfig.FONT_AWESOME,
        "https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css"
    ],
    suppress_callback_exceptions=True  # ✅ Ekleyin
)

logger.info("Donanım Yöneticisi başlatılıyor (Motor + Sensör)...")
init_results = hardware_manager.initialize_all()
logger.info(f"Donanım başlatma sonuçları: {init_results}")

# ============================================================================
# UI KOMPONENTLERİ
# ============================================================================

navbar = dbc.NavbarSimple(
    children=[
        dbc.NavItem(dbc.NavLink("Ana Sayfa", href="/", external_link=True)),
        dbc.NavItem(dbc.NavLink(
            [html.I(className="fa-solid fa-gear me-2"), "Kontrol Paneli"],
            href="/camera/",
            external_link=True
        )),
        dbc.NavItem(dbc.NavLink("Admin", href="/admin/", external_link=True, target="_blank"))
    ],
    brand=[
        html.I(className="fa-solid fa-robot fa-2x me-2"),
        f"Dream Pi {AppConfig.APP_VERSION} - Ultimate Control"
    ],
    brand_href="/",
    color="dark",
    dark=True,
    fluid=True,
    className="mb-4"
)

# === TAB 1: TEMEL AYARLAR ===
basic_settings_tab = dbc.Card([
    dbc.CardBody([
        html.H5([html.I(className="fa-solid fa-sliders me-2"), "Temel Ayarlar"], className="mb-3"),

        # Çözünürlük Grubu
        html.Div([
            html.Label("Çözünürlük Kategorisi:", className="fw-bold"),
            dcc.Dropdown(
                id='resolution-group-dropdown',
                options=[
                    {'label': f'{key} - {value}', 'value': key}
                    for key, value in CameraConfig.RESOLUTION_GROUPS.items()
                ],
                value='HD',  # ✅ Varsayılan değer
                clearable=False,
                className="mb-2"
            ),
            html.Small("💡 İpucu: Kategori seçince o gruptaki çözünürlükler aşağıda görünür",
                       className="text-info d-block mb-3")
        ]),

        # Çözünürlük Seçimi (Dinamik)
        html.Div([
            html.Label("Çözünürlük:", className="fw-bold"),
            html.Div(
                id='resolution-radio-container',
                # ✅ İLK YÜKLEME İÇİN VARSAYILAN RADIO BUTONLARI
                children=dbc.RadioItems(
                    id='resolution-select-radio',
                    options=[
                        {'label': '🎬 1280x720 (HD Ready) - 60 FPS ⭐', 'value': '1280x720'},
                        {'label': '🎬 1280x960 (SXGA) - 50 FPS', 'value': '1280x960'},
                        {'label': '🎬 1296x972 (Native) - 40 FPS ⭐⭐', 'value': '1296x972'},
                    ],
                    value='1280x720',  # ✅ Varsayılan seçili
                    className="mb-3"
                )
            )
        ]),

        html.Hr(),

        # FPS
        html.Div([
            html.Label("FrameRate (FPS):", className="fw-bold"),
            dcc.Slider(
                id='framerate-slider',
                min=5,
                max=120,
                step=5,
                value=30,
                marks={
                    5: '5', 15: '15', 30: {'label': '30\n(Optimal)', 'style': {'color': '#0f0'}},
                    60: '60', 90: '90', 120: {'label': '120\n(Max)', 'style': {'color': '#f00'}}
                },
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            ),
            html.Div(id='fps-warning', className="mt-2")
        ]),

        html.Hr(),

        # Otomatik Kontroller
        html.Div([
            html.Label("Otomatik Kontroller:", className="fw-bold"),
            dbc.Row([
                dbc.Col(dbc.Switch(
                    id='ae-enable-switch',
                    label="Auto Exposure (AE)",
                    value=True
                ), width=6),
                dbc.Col(dbc.Switch(
                    id='awb-enable-switch',
                    label="Auto White Balance (AWB)",
                    value=True
                ), width=6),
                dbc.Col(dbc.Switch(
                    id='lens-correction-switch',
                    label="Lens Düzeltme",
                    value=True
                ), width=6),
            ], className="mb-3")
        ]),

        html.Hr(),

        # Hızlı Preset Butonları
        html.Label("Hızlı Ön Ayarlar:", className="fw-bold"),
        dbc.ButtonGroup([
            dbc.Button("⚡ Max FPS", id='preset-max-fps', color="danger", size="sm",
                       title="640x480 @ 90fps"),
            dbc.Button("⚖️ Dengeli", id='preset-balanced', color="success", size="sm",
                       title="1280x720 @ 60fps"),
            dbc.Button("🎬 Full HD", id='preset-fullhd', color="primary", size="sm",
                       title="1920x1080 @ 30fps"),
            dbc.Button("📸 Max Kalite", id='preset-max-quality', color="warning", size="sm",
                       title="2592x1944 @ 10fps"),
        ], className="w-100 mb-2"),
    ])
], className="mb-3")

# === TAB 2: MANUEL POZLAMA ===
manual_exposure_tab = dbc.Card([
    dbc.CardBody([
        html.H5([html.I(className="fa-solid fa-sun me-2"), "Manuel Pozlama"], className="mb-3"),
        html.Small("⚠️ Bu ayarlar sadece Auto Exposure (AE) kapalıyken aktif olur",
                   className="text-warning d-block mb-3"),

        # Exposure Time
        html.Div([
            html.Label("Pozlama Süresi (Shutter Speed):", className="fw-bold"),
            dcc.Slider(
                id='exposure-time-slider',
                min=100,
                max=200000,
                step=100,
                value=10000,
                marks={
                    100: '0.1ms',
                    10000: '10ms',
                    50000: '50ms',
                    100000: '100ms',
                    200000: '200ms'
                },
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-1"
            ),
            html.Div(id='exposure-time-display', className="text-center text-info mb-3")
        ]),

        html.Hr(),

        # ISO
        html.Div([
            html.Label("ISO (Analog Gain):", className="fw-bold"),
            dcc.Slider(
                id='iso-gain-slider',
                min=1.0,
                max=16.0,
                step=0.1,
                value=1.0,
                marks={
                    1.0: 'ISO 100',
                    2.0: 'ISO 200',
                    4.0: 'ISO 400',
                    8.0: 'ISO 800',
                    16.0: 'ISO 1600'
                },
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-1"
            ),
            html.Div(id='iso-display', className="text-center text-info mb-3")
        ]),

        html.Hr(),

        # Quick Presets
        html.Label("Hızlı Ön Ayarlar:", className="fw-bold"),
        dbc.ButtonGroup([
            dbc.Button("☀️ Parlak Gün", id='preset-bright', color="warning", size="sm"),
            dbc.Button("🌤️ Normal", id='preset-normal', color="info", size="sm"),
            dbc.Button("🌙 Karanlık", id='preset-dark', color="secondary", size="sm"),
            dbc.Button("⚡ Hızlı", id='preset-fast', color="danger", size="sm"),
        ], className="w-100")
    ])
], className="mb-3")

# === TAB 3: GÖRÜNTÜ İYİLEŞTİRME ===
image_enhancement_tab = dbc.Card([
    dbc.CardBody([
        html.H5([html.I(className="fa-solid fa-wand-magic-sparkles me-2"), "Görüntü İyileştirme"], className="mb-3"),

        html.Div([
            html.Label("Parlaklık (Brightness):", className="fw-bold"),
            dcc.Slider(
                id='brightness-slider',
                min=-1.0,
                max=1.0,
                step=0.1,
                value=0.0,
                marks={-1.0: 'Karanlık', 0: 'Normal', 1.0: 'Parlak'},
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Kontrast (Contrast):", className="fw-bold"),
            dcc.Slider(
                id='contrast-slider',
                min=0.0,
                max=3.0,
                step=0.1,
                value=1.0,
                marks={0: 'Düz', 1: 'Normal', 2: 'Yüksek', 3: 'Çok Yüksek'},
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Doygunluk (Saturation):", className="fw-bold"),
            dcc.Slider(
                id='saturation-slider',
                min=0.0,
                max=3.0,
                step=0.1,
                value=1.0,
                marks={0: 'B&W', 1: 'Normal', 2: 'Canlı', 3: 'Çok Canlı'},
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Keskinlik (Sharpness):", className="fw-bold"),
            dcc.Slider(
                id='sharpness-slider',
                min=0.0,
                max=4.0,
                step=0.1,
                value=1.0,
                marks={0: 'Yumuşak', 1: 'Normal', 2: 'Keskin', 4: 'Çok Keskin'},
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            )
        ]),

        html.Hr(),

        dbc.Button(
            [html.I(className="fa-solid fa-rotate-left me-2"), "Varsayılana Sıfırla"],
            id='reset-image-settings-btn',
            color="secondary",
            size="sm",
            className="w-100"
        )
    ])
], className="mb-3")

# === TAB 4: GELİŞMİŞ MODLAR ===
advanced_modes_tab = dbc.Card([
    dbc.CardBody([
        html.H5([html.I(className="fa-solid fa-flask me-2"), "Gelişmiş Modlar"], className="mb-3"),

        html.Div([
            html.Label("Beyaz Dengesi Modu:", className="fw-bold"),
            dcc.Dropdown(
                id='awb-mode-dropdown',
                options=[
                    {'label': '🔄 Otomatik', 'value': 'Auto'},
                    {'label': '💡 Akkor Lamba (3000K)', 'value': 'Tungsten'},
                    {'label': '💡 Floresan (4000K)', 'value': 'Fluorescent'},
                    {'label': '🏠 İç Mekan', 'value': 'Indoor'},
                    {'label': '☀️ Gün Işığı (5500K)', 'value': 'Daylight'},
                    {'label': '☁️ Bulutlu (6500K)', 'value': 'Cloudy'},
                ],
                value='Auto',
                clearable=False,
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Renk Efekti:", className="fw-bold"),
            dcc.Dropdown(
                id='colour-effect-dropdown',
                options=[
                    {'label': '🎨 Normal', 'value': 'None'},
                    {'label': '🔲 Negatif', 'value': 'Negative'},
                    {'label': '🌅 Solar', 'value': 'Solarise'},
                    {'label': '✏️ Eskiz', 'value': 'Sketch'},
                    {'label': '🖼️ Kabartma', 'value': 'Emboss'},
                    {'label': '🎨 Yağlı Boya', 'value': 'Oilpaint'},
                    {'label': '🌸 Pastel', 'value': 'Pastel'},
                    {'label': '💧 Sulu Boya', 'value': 'Watercolour'},
                    {'label': '🎬 Çizgi Film', 'value': 'Cartoon'},
                    {'label': '📷 Sepya', 'value': 'Sepia'},
                ],
                value='None',
                clearable=False,
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Titreme Azaltma (Flicker):", className="fw-bold"),
            dcc.Dropdown(
                id='flicker-mode-dropdown',
                options=[
                    {'label': 'Kapalı', 'value': 'Off'},
                    {'label': '50 Hz (Avrupa)', 'value': '50Hz'},
                    {'label': '60 Hz (Amerika)', 'value': '60Hz'},
                    {'label': 'Otomatik', 'value': 'Auto'},
                ],
                value='Off',
                clearable=False,
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Pozlama Modu:", className="fw-bold"),
            dcc.Dropdown(
                id='exposure-mode-dropdown',
                options=[
                    {'label': 'Normal', 'value': 'Normal'},
                    {'label': 'Kısa (Fast)', 'value': 'Short'},
                    {'label': 'Uzun (Long)', 'value': 'Long'},
                ],
                value='Normal',
                clearable=False,
                className="mb-3"
            )
        ]),

        html.Div([
            html.Label("Ölçüm Modu:", className="fw-bold"),
            dcc.Dropdown(
                id='metering-mode-dropdown',
                options=[
                    {'label': 'Merkez Ağırlıklı', 'value': 'Centre'},
                    {'label': 'Nokta (Spot)', 'value': 'Spot'},
                    {'label': 'Matris', 'value': 'Matrix'},
                ],
                value='Centre',
                clearable=False,
                className="mb-3"
            )
        ]),
    ])
], className="mb-3")

# === KAMERA KONTROL PANELİ ===
camera_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-camera me-2"),
        "Kamera Kontrol (Ultimate)"
    ], className="bg-success text-white"),
    dbc.CardBody([
        dbc.Tabs([
            dbc.Tab(basic_settings_tab, label="Temel", tab_id="tab-basic"),
            dbc.Tab(manual_exposure_tab, label="Manuel Pozlama", tab_id="tab-exposure"),
            dbc.Tab(image_enhancement_tab, label="Görüntü", tab_id="tab-image"),
            dbc.Tab(advanced_modes_tab, label="Gelişmiş", tab_id="tab-advanced"),
        ], id="camera-tabs", active_tab="tab-basic"),

        html.Hr(),

        dbc.Button(
            [html.I(className="fa-solid fa-camera-retro me-2"), "Fotoğraf Çek"],
            id='capture-photo-btn',
            color="success",
            size="lg",
            className="w-100",
            n_clicks=0
        ),
    ])
], className="mb-3")

# === VERİTABANI KONTROL PANELİ ===
database_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-database me-2"),
        "Veritabanı İşlemleri"
    ], className="bg-warning text-dark"),
    dbc.CardBody([
        dbc.Button(
            [html.I(className="fa-solid fa-save me-2"), "Fotoğrafı Kaydet"],
            id='save-to-db-btn',
            color="warning",
            className="w-100 mb-2",
            n_clicks=0,
            disabled=True
        ),
        html.Hr(),
        html.Div([
            html.H6("Son Kayıt:", className="fw-bold mb-2"),
            html.Div(id='last-save-status', className="small text-muted", children="-")
        ]),
        html.Hr(),
        dbc.Row([
            dbc.Col([
                html.Small("Toplam:", className="text-muted"),
                html.Div(id='total-db-records', children="0", className="fw-bold h4")
            ], width=6),
            dbc.Col([
                html.Small("Bugün:", className="text-muted"),
                html.Div(id='today-db-records', children="0", className="fw-bold h4")
            ], width=6),
        ]),
        html.Hr(),
        dbc.Button(
            [html.I(className="fa-solid fa-sync me-2"), "İstatistikleri Yenile"],
            id='refresh-stats-btn',
            color="secondary",
            size="sm",
            className="w-100",
            n_clicks=0
        )
    ])
], className="mb-3")

# === MOTOR KONTROL PANELİ ===
motor_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-gear me-2"),
        "Step Motor Kontrol"
    ], className="bg-primary text-white"),
    dbc.CardBody([
        html.Div([
            html.Label("Hız Profili:", className="fw-bold"),
            dbc.RadioItems(
                id='speed-profile-radio',
                options=[
                    {'label': '🐌 Yavaş', 'value': 'slow'},
                    {'label': '🚶 Normal', 'value': 'normal'},
                    {'label': '🏃 Hızlı', 'value': 'fast'},
                ],
                value='normal',
                inline=True,
                className="mb-3"
            )
        ]),
        html.Div([
            html.Label([html.I(className="fa-solid fa-arrows-left-right me-2"), "Pozisyon:"],
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
                    -180: '-180°', -90: '-90°', 0: '0°', 90: '90°', 180: '180°'
                },
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            ),
        ]),
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
                    [html.I(className="fa-solid fa-stop me-1"), "Dur"],
                    id='stop-motor-btn',
                    color="danger",
                    size="sm"
                ),
            ], className="w-100"),
        ]),
        html.Div([
            html.Hr(),
            html.H6("Motor Durumu:", className="fw-bold"),
            html.Div(id='motor-status-display', className="small", children="Hazır")
        ])
    ])
], className="mb-3")

# === SENSÖR KONTROL PANELİ ===
sensor_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-satellite-dish me-2"),
        "Ultrasonik Sensör"
    ], className="bg-info text-white"),
    dbc.CardBody([
        dbc.Switch(
            id='sensor-switch',
            label="Canlı Okuma",
            value=False,
            className="mb-2"
        ),
        html.Hr(),
        html.H1(
            id='current-distance',
            children="⏹️ Kapalı",
            className="text-center display-4 pulse",
            style={'minHeight': '100px', 'display': 'flex', 'alignItems': 'center', 'justifyContent': 'center'}
        ),
        html.Hr(),
        html.Div(id='distance-chart', style={'height': '120px'}),
        html.Hr(),
        dbc.Row([
            dbc.Col([
                html.Small("Son Okuma:", className="text-muted"),
                html.Div(id='last-reading-time', children="-", className="fw-bold")
            ], width=6),
            dbc.Col([
                html.Small("Okuma Sayısı:", className="text-muted"),
                html.Div(id='reading-count', children="0", className="fw-bold")
            ], width=6),
        ])
    ])
], className="mb-3")

# === STATS CARD ===
stats_card = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-chart-simple me-2"),
        "Sistem Durumu"
    ], className="bg-dark text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.H6("Motor Açısı:", className="text-muted mb-1"),
                html.H3(id='current-pan-angle', children="0.0°", className="mb-0 text-primary")
            ], className="text-center border-end", width=6),
            dbc.Col([
                html.H6("Sensör Mesafe:", className="text-muted mb-1"),
                html.H3(id='current-sensor-distance', children="-", className="mb-0 text-success")
            ], className="text-center", width=6),
        ])
    ])
], className="mb-3")

# === FOTOĞRAF GÖRÜNTÜLEME ===
photo_display_area = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-image me-2"),
        "Çekilen Fotoğraf"
    ], className="bg-secondary text-white"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.Img(id='captured-image', style={'width': '100%', 'borderRadius': '5px'})
            ], md=6),
            dbc.Col([
                html.H5("Çekim Bilgileri"),
                dbc.Table([
                    html.Tbody(id='photo-info-table')
                ], bordered=True, striped=True, hover=True, color="dark"),
                html.Hr(),
                html.H5("Base64 Önizleme"),
                dbc.Textarea(
                    id='photo-base64-output',
                    style={'height': '100px', 'fontSize': '0.75rem'},
                    readOnly=True
                )
            ], md=6)
        ])
    ], style={'display': 'none'}, id='photo-display-wrapper')
], className="mb-3")

# === KARŞILAŞTIRMA PANELİ ===
comparison_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-balance-scale me-2"),
        "Fotoğraf Karşılaştırma"
    ], className="bg-info text-dark"),
    dbc.CardBody([
        dbc.Row([
            dbc.Col([
                html.Label("1. Fotoğraf:", className="fw-bold"),
                dcc.Dropdown(
                    id='compare-photo-1',
                    placeholder="Fotoğraf seçin...",
                    className="mb-2"
                )
            ], md=6),
            dbc.Col([
                html.Label("2. Fotoğraf:", className="fw-bold"),
                dcc.Dropdown(
                    id='compare-photo-2',
                    placeholder="Fotoğraf seçin...",
                    className="mb-2"
                )
            ], md=6),
        ]),
        dbc.Button(
            [html.I(className="fa-solid fa-code-compare me-2"), "Karşılaştır"],
            id='compare-btn',
            color="info",
            className="w-100 mb-3",
            n_clicks=0
        ),
        html.Hr(),
        html.Div(id='comparison-result', className="text-center", children="Karşılaştırma için iki fotoğraf seçin")
    ])
], className="mb-3")

# === AI VISION KONTROL ===
ai_vision_control_panel = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-brain me-2"),
        "AI Vision Kontrol"
    ], className="bg-purple text-white"),
    dbc.CardBody([
        html.H6("Aktif Modüller:", className="fw-bold mb-2"),

        dbc.Checklist(
            id='ai-modules-checklist',
            options=[
                {'label': '🎯 YOLO (Nesne Tespiti)', 'value': 'yolo'},
                {'label': '👤 Yüz Tanıma', 'value': 'face'},
                {'label': '💫 Hareket Tespiti', 'value': 'motion'},
                {'label': '📱 QR/Barkod Okuma', 'value': 'qr'},
                {'label': '✏️ Kenar Tespiti', 'value': 'edges'},
            ],
            value=[],
            switch=True,
            className="mb-3"
        ),

        html.Hr(),

        html.Div([
            html.Label("YOLO Güven Skoru:", className="fw-bold"),
            dcc.Slider(
                id='yolo-confidence-slider',
                min=0.1,
                max=0.9,
                step=0.05,
                value=AIConfig.YOLO_CONFIDENCE,
                marks={0.1: '10%', 0.5: '50%', 0.9: '90%'},
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            )
        ], id='yolo-settings-div', style={'display': 'none'}),

        html.Div([
            html.Label("Hareket Hassasiyeti:", className="fw-bold"),
            dcc.Slider(
                id='motion-threshold-slider',
                min=10,
                max=50,
                step=5,
                value=AIConfig.MOTION_THRESHOLD,
                marks={10: 'Düşük', 25: 'Orta', 50: 'Yüksek'},
                tooltip={"placement": "bottom", "always_visible": True},
                className="mb-3"
            )
        ], id='motion-settings-div', style={'display': 'none'}),

        html.Hr(),

        dbc.Button(
            [html.I(className="fa-solid fa-play me-2"), "AI İşleme Başlat"],
            id='start-ai-processing-btn',
            color="success",
            size="lg",
            className="w-100 mb-2",
            n_clicks=0
        ),

        dbc.Button(
            [html.I(className="fa-solid fa-stop me-2"), "Durdur"],
            id='stop-ai-processing-btn',
            color="danger",
            size="lg",
            className="w-100 mb-2",
            n_clicks=0,
            disabled=True
        ),

        dbc.Button(
            [html.I(className="fa-solid fa-camera me-2"), "Tek Çekim Analiz"],
            id='single-ai-snapshot-btn',
            color="info",
            size="sm",
            className="w-100",
            n_clicks=0
        ),
    ])
], className="mb-3")

# === AI SONUÇLARI ===
ai_results_display = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-chart-bar me-2"),
        "AI Analiz Sonuçları"
    ], className="bg-info text-white"),
    dbc.CardBody([
        html.Div([
            html.H6("İşlenmiş Görüntü:", className="fw-bold"),
            html.Img(
                id='ai-processed-image',
                style={'width': '100%', 'borderRadius': '5px', 'border': '2px solid #17a2b8'}
            )
        ], className="mb-3"),

        html.Hr(),

        html.Div([
            html.H6("Tespit Edilen Nesneler:", className="fw-bold mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Div(id='yolo-count', children="0", className="h3 text-primary mb-0"),
                    html.Small("YOLO", className="text-muted")
                ], width=3, className="text-center"),
                dbc.Col([
                    html.Div(id='face-count', children="0", className="h3 text-danger mb-0"),
                    html.Small("Yüz", className="text-muted")
                ], width=3, className="text-center"),
                dbc.Col([
                    html.Div(id='motion-count', children="0", className="h3 text-warning mb-0"),
                    html.Small("Hareket", className="text-muted")
                ], width=3, className="text-center"),
                dbc.Col([
                    html.Div(id='qr-count', children="0", className="h3 text-success mb-0"),
                    html.Small("QR/Kod", className="text-muted")
                ], width=3, className="text-center"),
            ])
        ], className="mb-3"),

        html.Hr(),

        html.Div([
            html.H6("Hareket Yüzdesi:", className="fw-bold"),
            dcc.Graph(
                id='motion-percentage-gauge',
                style={'height': '200px'},
                config={'displayModeBar': False}
            )
        ]),

        html.Hr(),

        html.Div([
            html.H6("Detaylı Tespit Listesi:", className="fw-bold"),
            html.Div(
                id='detection-list',
                style={
                    'maxHeight': '300px',
                    'overflowY': 'auto',
                    'backgroundColor': '#1a1a1a',
                    'padding': '10px',
                    'borderRadius': '5px'
                }
            )
        ])
    ])
], className="mb-3")

edge_detection_display = dbc.Card([
    dbc.CardHeader([
        html.I(className="fa-solid fa-crop me-2"),
        "Kenar Tespiti"
    ], className="bg-secondary text-white"),
    dbc.CardBody([
        html.Img(
            id='edge-detection-image',
            style={'width': '100%', 'borderRadius': '5px'}
        )
    ])
], className="mb-3")

ai_vision_tab = dbc.Tab([
    dbc.Row([
        dbc.Col([
            ai_vision_control_panel,
            html.Div([
                html.H6("AI Durumu:", className="fw-bold"),
                html.Div(id='ai-status-indicator', className="alert alert-secondary")
            ])
        ], md=4),

        dbc.Col([
            ai_results_display,
            edge_detection_display
        ], md=8)
    ])
], label="🤖 AI Vision", tab_id="tab-ai-vision")

# ============================================================================
# ANA LAYOUT
# ============================================================================

app.layout = html.Div([
    navbar,

    html.Link(
        rel='stylesheet',
        href='data:text/css;charset=utf-8,' + '''
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.05); }
        }
        .pulse { animation: pulse 2s ease-in-out infinite; }
        .rc-slider-mark-text { font-size: 0.75rem !important; }
        .bg-purple { background-color: #6f42c1 !important; }
        '''
    ),

    dbc.Container([
        dbc.Row([
            dbc.Col([
                camera_control_panel,
                database_control_panel,
                motor_control_panel,
                sensor_control_panel,
                stats_card
            ], md=4),

            dbc.Col([
                dbc.Tabs([
                    dbc.Tab(photo_display_area, label="📸 Fotoğraf"),
                    dbc.Tab(comparison_panel, label="⚖️ Karşılaştırma"),
                    ai_vision_tab,
                ], id="main-tabs", active_tab="tab-photo"),
            ], md=8),

        ])
    ], fluid=True),

    # Intervals
    dcc.Interval(id='motor-update-interval', interval=AppConfig.MOTOR_UPDATE_INTERVAL_MS, n_intervals=0),
    dcc.Interval(id='metrics-interval', interval=AppConfig.METRICS_INTERVAL_MS, n_intervals=0),
    dcc.Interval(id='stats-update-interval', interval=5000, n_intervals=0),
    dcc.Interval(id='cleanup-interval', interval=AppConfig.CLEANUP_INTERVAL_MS, n_intervals=0),

    # Stores
    dcc.Store(id='sensor-store', data={'sensor_enabled': False, 'sensor_history': [], 'reading_count': 0}),
    dcc.Store(id='current-photo-store', data={}),
    dcc.Store(id='camera-settings-store', data={}),
    dcc.Store(id='ai-processing-state', data={'is_running': False, 'last_start_click': 0, 'last_stop_click': 0}),

], style={'background-color': '#0a0a0a', 'min-height': '100vh'})


# ============================================================================
# YARDIMCI FONKSİYONLAR
# ============================================================================

def format_exposure_time(microseconds: int) -> str:
    """Pozlama süresini okunabilir formata çevir"""
    ms = microseconds / 1000
    if ms < 1:
        return f"{microseconds} µs"
    elif ms < 1000:
        return f"{ms:.1f} ms"
    else:
        return f"{ms / 1000:.2f} s"


def format_iso(gain: float) -> str:
    """ISO gain'i ISO değerine çevir"""
    iso = int(gain * 100)
    return f"ISO {iso}"


# ============================================================================
# CALLBACKS - DISPLAY HELPERS
# ============================================================================

@app.callback(
    Output('exposure-time-display', 'children'),
    Input('exposure-time-slider', 'value')
)
def display_exposure_time(value):
    return f"⏱️ {format_exposure_time(value)}"


@app.callback(
    Output('iso-display', 'children'),
    Input('iso-gain-slider', 'value')
)
def display_iso(value):
    return f"📷 {format_iso(value)}"


# ============================================================================
# CALLBACKS - RESOLUTION
# ============================================================================

@app.callback(
    [Output('resolution-radio-container', 'children'),
     Output('current-photo-store', 'data', allow_duplicate=True)],
    Input('resolution-group-dropdown', 'value'),
    State('current-photo-store', 'data'),
    prevent_initial_call='initial_duplicate'  # ✅ 'initial_duplicate' kullan
)
def update_resolution_options(selected_group, store):
    """Çözünürlük grubuna göre seçenekleri filtrele"""

    if not selected_group:
        selected_group = 'HD'

    filtered_resolutions = [
        res for res in CameraConfig.RESOLUTIONS
        if res.get('group') == selected_group
    ]

    if not filtered_resolutions:
        filtered_resolutions = [
            res for res in CameraConfig.RESOLUTIONS
            if res.get('group') == 'HD'
        ]

    default_value = filtered_resolutions[0]['value'] if filtered_resolutions else '1280x720'

    radio_items = dbc.RadioItems(
        id='resolution-select-radio',
        options=[
            {'label': res['label'], 'value': res['value']}
            for res in filtered_resolutions
        ],
        value=default_value,
        className="mb-3"
    )

    updated_store = store.copy() if store else {}
    updated_store['selected_resolution'] = default_value

    return radio_items, updated_store


@app.callback(
    [Output('framerate-slider', 'max'),
     Output('framerate-slider', 'value'),
     Output('fps-warning', 'children')],
    Input('resolution-select-radio', 'value'),
    State('framerate-slider', 'value'),
    prevent_initial_call='initial_duplicate'  # ✅ Değiştir
)
def update_fps_limits(resolution_str, current_fps):
    """FPS limitlerini çözünürlüğe göre güncelle"""

    default_max_fps = 60
    default_fps = 30

    if not resolution_str or 'x' not in str(resolution_str):
        warning = html.Div([
            html.I(className="fa-solid fa-info-circle me-2 text-info"),
            "Varsayılan FPS limiti kullanılıyor"
        ], className="alert alert-info py-2 mb-0")

        return default_max_fps, default_fps, warning

    try:
        w, h = map(int, str(resolution_str).strip().split('x'))
        resolution_tuple = (w, h)
        max_fps = CameraConfig.RESOLUTION_FPS_LIMITS.get(resolution_tuple, default_max_fps)

        if resolution_tuple not in CameraConfig.RESOLUTION_FPS_LIMITS:
            pixel_count = w * h
            if pixel_count > 2_000_000:
                max_fps = 15
            elif pixel_count > 1_000_000:
                max_fps = 30
            elif pixel_count > 500_000:
                max_fps = 60
            else:
                max_fps = 90

        new_fps = min(current_fps or default_fps, max_fps)

        if current_fps and current_fps > max_fps:
            warning = html.Div([
                html.I(className="fa-solid fa-triangle-exclamation me-2 text-warning"),
                f"FPS {max_fps}'e düşürüldü"
            ], className="alert alert-warning py-2 mb-0")
        else:
            warning = html.Div([
                html.I(className="fa-solid fa-info-circle me-2 text-info"),
                f"Maksimum FPS: {max_fps}"
            ], className="alert alert-info py-2 mb-0")

        return max_fps, new_fps, warning

    except Exception as e:
        logger.error(f"FPS limit hatası: {e}")
        warning = html.Div(f"⚠️ FPS hesaplanamadı", className="alert alert-warning py-2")
        return default_max_fps, default_fps, warning


# ============================================================================
# CALLBACKS - PRESETS
# ============================================================================

@app.callback(
    [Output('exposure-time-slider', 'value'),
     Output('iso-gain-slider', 'value')],
    [Input('preset-bright', 'n_clicks'),
     Input('preset-normal', 'n_clicks'),
     Input('preset-dark', 'n_clicks'),
     Input('preset-fast', 'n_clicks')],
    prevent_initial_call='initial_duplicate'
)
def apply_presets(bright_clicks, normal_clicks, dark_clicks, fast_clicks):
    """Pozlama preset'leri"""
    clicks = {
        'bright': bright_clicks or 0,
        'normal': normal_clicks or 0,
        'dark': dark_clicks or 0,
        'fast': fast_clicks or 0
    }

    if max(clicks.values()) == 0:
        return 10000, 1.0

    last_clicked = max(clicks, key=clicks.get)

    presets = {
        'bright': (5000, 1.0),
        'normal': (10000, 1.0),
        'dark': (50000, 4.0),
        'fast': (1000, 8.0)
    }

    exposure, gain = presets[last_clicked]
    return exposure, gain


@app.callback(
    [Output('brightness-slider', 'value'),
     Output('contrast-slider', 'value'),
     Output('saturation-slider', 'value'),
     Output('sharpness-slider', 'value')],
    Input('reset-image-settings-btn', 'n_clicks'),
    prevent_initial_call='initial_duplicate'
)
def reset_image_settings(n):
    return 0.0, 1.0, 1.0, 1.0


@app.callback(
    [Output('resolution-group-dropdown', 'value'),
     Output('framerate-slider', 'value', allow_duplicate=True)],
    [Input('preset-max-fps', 'n_clicks'),
     Input('preset-balanced', 'n_clicks'),
     Input('preset-fullhd', 'n_clicks'),
     Input('preset-max-quality', 'n_clicks')],
    prevent_initial_call='initial_duplicate'
)
def apply_quick_presets(max_fps_clicks, balanced_clicks, fullhd_clicks, quality_clicks):
    """Çözünürlük preset'leri"""
    clicks = {
        'max_fps': max_fps_clicks or 0,
        'balanced': balanced_clicks or 0,
        'fullhd': fullhd_clicks or 0,
        'quality': quality_clicks or 0
    }

    if max(clicks.values()) == 0:
        return 'HD', 30

    last_clicked = max(clicks, key=clicks.get)

    presets = {
        'max_fps': ('Performans', 90),
        'balanced': ('HD', 60),
        'fullhd': ('Full HD', 30),
        'quality': ('Maksimum', 10)
    }

    group, fps = presets[last_clicked]
    return group, fps


# ============================================================================
# CALLBACKS - CLEANUP
# ============================================================================

@app.callback(
    Output('sensor-store', 'data', allow_duplicate=True),
    Input('cleanup-interval', 'n_intervals'),
    State('sensor-store', 'data'),
    prevent_initial_call='initial_duplicate'  # ✅ Değiştir
)
def auto_cleanup(n, store):
    """Otomatik bellek temizliği"""
    try:
        cleaned_store = cleanup_old_store_data(store, AppConfig.MAX_FRAME_BUFFER_AGE_SECONDS)

        if AppConfig.ENABLE_MANUAL_GC and n % 6 == 0:
            gc.collect()
            logger.debug("🧹 Manuel garbage collection yapıldı")

        return cleaned_store
    except Exception as e:
        logger.error(f"Auto cleanup hatası: {e}")
        return store or {'sensor_enabled': False, 'sensor_history': [], 'reading_count': 0}


# ============================================================================
# CALLBACKS - CAPTURE PHOTO
# ============================================================================

@app.callback(
    [Output('photo-display-wrapper', 'style'),
     Output('captured-image', 'src'),
     Output('photo-info-table', 'children'),
     Output('photo-base64-output', 'value'),
     Output('current-photo-store', 'data'),
     Output('save-to-db-btn', 'disabled')],
    Input('capture-photo-btn', 'n_clicks'),
    [State('resolution-select-radio', 'value'),
     State('current-photo-store', 'data'),  # FALLBACK İÇİN EKLE
     State('framerate-slider', 'value'),
     State('lens-correction-switch', 'value'),
     State('ae-enable-switch', 'value'),
     State('awb-enable-switch', 'value'),
     State('exposure-time-slider', 'value'),
     State('iso-gain-slider', 'value'),
     State('brightness-slider', 'value'),
     State('contrast-slider', 'value'),
     State('saturation-slider', 'value'),
     State('sharpness-slider', 'value'),
     State('awb-mode-dropdown', 'value'),
     State('colour-effect-dropdown', 'value'),
     State('flicker-mode-dropdown', 'value'),
     State('exposure-mode-dropdown', 'value'),
     State('metering-mode-dropdown', 'value')],
    prevent_initial_call=True
)
def capture_photo_ultimate(n_clicks, resolution_str, photo_store, framerate, lens_correction, ae_enable, awb_enable,
                           exposure_time, analogue_gain, brightness, contrast, saturation, sharpness,
                           awb_mode, colour_effect, flicker_mode, exposure_mode, metering_mode):
    """Fotoğraf çekme - TÜM AYARLAR + FALLBACK"""

    error_return = (
        {'display': 'none'},
        "",
        [html.Tr([html.Td("Hata", colSpan=2, className="text-danger")])],
        "",
        photo_store or {},
        True
    )

    if not n_clicks:
        return error_return

    # FALLBACK: Eğer resolution_str None ise store'dan al
    if not resolution_str or resolution_str is None:
        if photo_store and 'selected_resolution' in photo_store:
            resolution_str = photo_store['selected_resolution']
            logger.warning(f"Çözünürlük State'ten alınamadı, store'dan kullanıldı: {resolution_str}")
        else:
            logger.error("Çözünürlük hem State hem Store'da yok! Varsayılan kullanılıyor.")
            resolution_str = "1280x720"  # Varsayılan

    if not resolution_str or 'x' not in str(resolution_str):
        logger.error(f"Geçersiz çözünürlük: {resolution_str}")
        return error_return

    try:
        logger.info(f"📸 Fotoğraf çekiliyor...")

        parts = str(resolution_str).split('x')
        if len(parts) != 2:
            raise ValueError("Çözünürlük formatı hatalı")

        w_str, h_str = parts
        resolution_tuple = (int(w_str.strip()), int(h_str.strip()))

        if not (320 <= resolution_tuple[0] <= 2592):
            raise ValueError(f"Genişlik sınır dışı: {resolution_tuple[0]}")
        if not (240 <= resolution_tuple[1] <= 1944):
            raise ValueError(f"Yükseklik sınır dışı: {resolution_tuple[1]}")

        validated_fps = CameraConfig.validate_framerate(float(framerate), resolution_tuple)
        if validated_fps != framerate:
            logger.warning(f"FPS {framerate} -> {validated_fps} ayarlandı")

        try:
            frame = hardware_manager.capture_frame(
                resolution=resolution_tuple,
                framerate=validated_fps,
                apply_lens_correction=lens_correction,
                ae_enable=ae_enable,
                awb_enable=awb_enable,
                exposure_time=int(exposure_time) if not ae_enable else None,
                analogue_gain=float(analogue_gain) if not ae_enable else None,
                brightness=float(brightness),
                contrast=float(contrast),
                saturation=float(saturation),
                sharpness=float(sharpness),
                awb_mode=awb_mode,
                colour_effect=colour_effect,
                flicker_mode=flicker_mode,
                exposure_mode=exposure_mode,
                metering_mode=metering_mode,
            )
        except TypeError:
            logger.warning("Hardware manager güncel değil, temel ayarlar kullanılıyor")
            frame = hardware_manager.capture_frame(
                resolution=resolution_tuple,
                framerate=validated_fps,
                apply_lens_correction=lens_correction,
                ae_enable=ae_enable,
                awb_enable=awb_enable,
            )

        motor_angle = hardware_manager.get_motor_angle()
        sensor_distance = hardware_manager.get_current_distance()
        sensor_is_active = hardware_manager.is_sensor_active()

        if frame is None:
            logger.error("Kare alınamadı")
            return error_return

        base64_string = image_to_base64(frame, quality=80, format='JPEG')
        if not base64_string:
            logger.error("Base64 çevrimi başarısız")
            return error_return

        img_prefix, img_data = split_data_uri(base64_string)
        img_format = img_prefix.split('/')[1].split(';')[0].upper()
        img_bytes_len = len(base64.b64decode(img_data))
        file_size_kb = img_bytes_len / 1024.0
        actual_height, actual_width = frame.shape[:2]
        resolution_final = f"{actual_width}x{actual_height}"

        from math import gcd
        aspect_gcd = gcd(actual_width, actual_height)
        aspect_ratio = f"{actual_width // aspect_gcd}:{actual_height // aspect_gcd}"
        megapixels = (actual_width * actual_height) / 1_000_000

        def row(label, value):
            return html.Tr([html.Td(label, className="fw-bold"), html.Td(value)])

        def bool_badge(val, true_text="AKTİF", false_text="KAPALI"):
            if val:
                return html.Span(true_text, className="badge bg-success")
            return html.Span(false_text, className="badge bg-secondary")

        table_rows = [
            row("Motor Açısı", f"{motor_angle:.1f}°"),
            row("Sensör Mesafesi", format_distance(sensor_distance) if sensor_distance else "N/A"),
            row("Sensör Durumu", bool_badge(sensor_is_active, "AÇIK", "KAPALI")),
            html.Tr([html.Td(html.Hr(style={'margin': '5px 0'}), colSpan=2)]),

            row("Çözünürlük", resolution_final),
            row("Aspect Ratio", aspect_ratio),
            row("Megapixel", f"{megapixels:.2f} MP"),
            row("FrameRate", f"{validated_fps} FPS"),
            row("Dosya Boyutu", f"{file_size_kb:.1f} KB"),
            row("Format", img_format),
            html.Tr([html.Td(html.Hr(style={'margin': '5px 0'}), colSpan=2)]),

            row("Lens Düzeltme", bool_badge(lens_correction, "UYGULANDI", "YOK")),
            row("Oto Pozlama (AE)", bool_badge(ae_enable)),
            row("Oto Beyaz Deng. (AWB)", bool_badge(awb_enable)),
            row("AWB Modu", awb_mode),
            html.Tr([html.Td(html.Hr(style={'margin': '5px 0'}), colSpan=2)]),

            row("Pozlama Süresi", format_exposure_time(exposure_time) if not ae_enable else "Otomatik"),
            row("ISO", format_iso(analogue_gain) if not ae_enable else "Otomatik"),
            html.Tr([html.Td(html.Hr(style={'margin': '5px 0'}), colSpan=2)]),

            row("Parlaklık", f"{brightness:+.1f}"),
            row("Kontrast", f"{contrast:.1f}x"),
            row("Doygunluk", f"{saturation:.1f}x"),
            row("Keskinlik", f"{sharpness:.1f}x"),
            html.Tr([html.Td(html.Hr(style={'margin': '5px 0'}), colSpan=2)]),

            row("Renk Efekti", colour_effect),
            row("Titreme Modu", flicker_mode),
            row("Pozlama Modu", exposure_mode),
            row("Ölçüm Modu", metering_mode),
        ]

        photo_data = {
            'base64': base64_string,
            'angle': motor_angle,
            'distance': format_distance(sensor_distance) if sensor_distance else "N/A",
            'distance_raw': sensor_distance,
            'sensor_active': sensor_is_active,
            'timestamp': datetime.now().isoformat(),
            'effect': 'none',
            'resolution': resolution_final,
            'aspect_ratio': aspect_ratio,
            'megapixels': megapixels,
            'file_size_kb': file_size_kb,
            'image_format': img_format,
            'framerate': float(validated_fps),
            'lens_correction': lens_correction,
            'ae_enable': ae_enable,
            'awb_enable': awb_enable,
            'exposure_time': int(exposure_time) if not ae_enable else None,
            'analogue_gain': float(analogue_gain) if not ae_enable else None,
            'brightness': float(brightness),
            'contrast': float(contrast),
            'saturation': float(saturation),
            'sharpness': float(sharpness),
            'awb_mode': awb_mode,
            'colour_effect': colour_effect,
            'ae_flicker_mode': flicker_mode,
            'exposure_mode': exposure_mode,
            'metering_mode': metering_mode,
        }

        logger.info(f"✓ Fotoğraf çekildi: {resolution_final}, {file_size_kb:.1f}KB")

        return (
            {'display': 'block'},
            base64_string,
            table_rows,
            base64_string[:100] + "...",
            photo_data,
            False
        )

    except Exception as e:
        logger.error(f"Capture hatası: {e}", exc_info=True)
        return error_return


# ============================================================================
# CALLBACKS - DATABASE
# ============================================================================

@app.callback(
    [Output('last-save-status', 'children'),
     Output('save-to-db-btn', 'disabled', allow_duplicate=True)],
    Input('save-to-db-btn', 'n_clicks'),
    State('current-photo-store', 'data'),
    prevent_initial_call='initial_duplicate'
)
def save_to_db_ultimate(n_clicks, photo_data):
    """DB'ye kaydet"""
    if not n_clicks or not photo_data:
        return "-", True

    try:
        kwargs = {
            'base64_image': photo_data['base64'],
            'effect': photo_data.get('effect', 'none'),
            'pan_angle': photo_data['angle'],
            'distance_info': photo_data['distance'],
            'resolution': photo_data.get('resolution', 'N/A'),
            'file_size_kb': photo_data.get('file_size_kb', 0.0),
            'image_format': photo_data.get('image_format', 'JPEG'),
            'framerate': photo_data.get('framerate'),
            'lens_correction': photo_data.get('lens_correction', True),
            'ae_enable': photo_data.get('ae_enable', True),
            'awb_enable': photo_data.get('awb_enable', True),
        }

        optional_fields = [
            'exposure_time', 'analogue_gain',
            'brightness', 'contrast', 'saturation', 'sharpness',
            'awb_mode', 'colour_effect', 'ae_flicker_mode',
            'exposure_mode', 'metering_mode'
        ]

        for field in optional_fields:
            if field in photo_data and photo_data[field] is not None:
                kwargs[field] = photo_data[field]

        capture = CameraCapture.objects.create(**kwargs)

        logger.info(f"✓ DB'ye kaydedildi: ID={capture.id}")

        return (
            html.Div([
                html.I(className="fa-solid fa-check text-success me-2"),
                f"Kaydedildi (ID: {capture.id})"
            ]),
            True
        )
    except Exception as e:
        logger.error(f"DB kayıt hatası: {e}", exc_info=True)
        return (html.Div(f"❌ {str(e)[:50]}", className="text-danger"), False)


@app.callback(
    [Output('compare-photo-1', 'options'),
     Output('compare-photo-2', 'options'),
     Output('total-db-records', 'children'),
     Output('today-db-records', 'children')],
    [Input('refresh-stats-btn', 'n_clicks'),
     Input('stats-update-interval', 'n_intervals'),
     Input('save-to-db-btn', 'n_clicks')],
    prevent_initial_call=False
)
def update_stats_and_dropdowns(refresh_clicks, intervals, save_clicks):
    """İstatistikleri ve dropdown'ları güncelle"""
    try:
        photos = CameraCapture.objects.all().order_by('-timestamp')[:20]
        total = CameraCapture.objects.count()
        today = CameraCapture.objects.filter(timestamp__date=timezone.now().date()).count()

        if not photos:
            return ([], [], str(total), str(today))

        dropdown_opts = []

        for photo in photos:
            res = photo.resolution or "Unknown"
            fps = f"{photo.framerate:.0f}fps" if photo.framerate else "N/A"
            label = f"#{photo.id} - {photo.timestamp.strftime('%H:%M:%S')} ({photo.pan_angle:.0f}°, {res} @ {fps})"
            dropdown_opts.append({'label': label, 'value': photo.id})

        return (dropdown_opts, dropdown_opts, str(total), str(today))

    except Exception as e:
        logger.error(f"İstatistik/Dropdown hatası: {e}")
        return ([], [], "0", "0")


# ============================================================================
# CALLBACKS - COMPARISON
# ============================================================================

@app.callback(
    Output('comparison-result', 'children'),
    Input('compare-btn', 'n_clicks'),
    [State('compare-photo-1', 'value'), State('compare-photo-2', 'value')],
    prevent_initial_call='initial_duplicate'
)
def compare_ultimate(n_clicks, id1, id2):
    """Hibrit karşılaştırma: pHash + SSIM + MSE + ORB + SHA256"""
    if not n_clicks or not id1 or not id2 or id1 == id2:
        return "Karşılaştırma için iki farklı fotoğraf seçin"

    try:
        p1 = CameraCapture.objects.get(id=id1)
        p2 = CameraCapture.objects.get(id=id2)

        prefix1, data1 = split_data_uri(p1.base64_image)
        prefix2, data2 = split_data_uri(p2.base64_image)

        pil1, gray1 = base64_data_to_images(data1)
        pil2, gray2 = base64_data_to_images(data2)

        if pil1 is None or pil2 is None:
            return html.Div("❌ Hata: Base64 verisi görüntüye çevrilemedi.", className="alert alert-danger")

        angle_diff = abs(p1.pan_angle - p2.pan_angle)
        time_diff = abs(p1.timestamp - p2.timestamp)
        is_identical = (p1.base64_image == p2.base64_image)

        sha_hash1 = hashlib.sha256(data1.encode('utf-8')).hexdigest()
        sha_hash2 = hashlib.sha256(data2.encode('utf-8')).hexdigest()
        sha_match = (sha_hash1 == sha_hash2)

        phash1 = imagehash.phash(pil1)
        phash2 = imagehash.phash(pil2)
        phash_diff = phash1 - phash2

        h1, w1 = gray1.shape
        h2, w2 = gray2.shape
        target_h = min(h1, h2, 512)
        target_w = min(w1, w2, 512)

        gray1_resized = cv2.resize(gray1, (target_w, target_h), interpolation=cv2.INTER_AREA)
        gray2_resized = cv2.resize(gray2, (target_w, target_h), interpolation=cv2.INTER_AREA)

        ssim_score = ssim(gray1_resized, gray2_resized, data_range=gray1_resized.max() - gray1_resized.min())
        ssim_percent = ssim_score * 100

        mse_score = mean_squared_error(gray1_resized, gray2_resized)

        orb = cv2.ORB_create(nfeatures=1000)
        kp1, des1 = orb.detectAndCompute(gray1, None)
        kp2, des2 = orb.detectAndCompute(gray2, None)
        orb_match_percent = 0.0
        orb_total_features = (len(kp1) if kp1 is not None else 0, len(kp2) if kp2 is not None else 0)

        if des1 is not None and des2 is not None and orb_total_features[0] > 0 and orb_total_features[1] > 0:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = bf.match(des1, des2)
            good_matches = [m for m in matches if m.distance < 75]
            min_kp = min(orb_total_features)
            if min_kp > 0:
                orb_match_percent = (len(good_matches) / min_kp) * 100

        image_row = dbc.Row([
            dbc.Col([
                html.H6(f"#{p1.id}"),
                html.Img(src=p1.base64_image, style={'width': '100%'}),
                html.Small(f"{p1.pan_angle:.1f}° | {p1.timestamp.strftime('%H:%M')}")
            ], md=6),
            dbc.Col([
                html.H6(f"#{p2.id}"),
                html.Img(src=p2.base64_image, style={'width': '100%'}),
                html.Small(f"{p2.pan_angle:.1f}° | {p2.timestamp.strftime('%H:%M')}")
            ], md=6)
        ])

        if phash_diff <= 2:
            phash_text, phash_class = f"AYNI ({phash_diff} bit)", "text-success"
        elif phash_diff <= 8:
            phash_text, phash_class = f"BENZER ({phash_diff} bit)", "text-warning"
        else:
            phash_text, phash_class = f"FARKLI ({phash_diff} bit)", "text-danger"

        if ssim_percent >= 99.0:
            ssim_class = "text-success"
        elif ssim_percent >= 85.0:
            ssim_class = "text-warning"
        else:
            ssim_class = "text-danger"

        if mse_score <= 100:
            mse_class = "text-success"
        elif mse_score <= 1000:
            mse_class = "text-warning"
        else:
            mse_class = "text-danger"

        if orb_match_percent >= 75.0:
            orb_class = "text-success"
        elif orb_match_percent >= 40.0:
            orb_class = "text-warning"
        else:
            orb_class = "text-danger"

        if sha_match:
            sha_td = html.Td("AYNI", className="text-success")
        else:
            sha_td = html.Td([
                html.P("FARKLI", className="text-danger fw-bold"),
                html.Small(f"SHA1: {sha_hash1[:32]}...", style={'wordBreak': 'break-all', 'fontSize': '0.7rem'}),
                html.Hr(),
                html.Small(f"SHA2: {sha_hash2[:32]}...", style={'wordBreak': 'break-all', 'fontSize': '0.7rem'})
            ], className="text-danger")

        summary_icon = "fa-solid fa-check-double" if is_identical else "fa-solid fa-triangle-exclamation"
        summary_text = "BİREBİR AYNI VERİ" if is_identical else "FARKLI VERİ"
        summary_class = "text-success" if is_identical else "text-danger"

        def compare_row(label, val1, val2, text_true="AYNI", text_false="FARKLI"):
            if val1 == val2:
                val_str = str(val1) if val1 is not None else "N/A"
                if isinstance(val1, bool): val_str = ("Aktif" if val1 else "Kapalı")
                return html.Tr([html.Td(label), html.Td(f"{text_true} ({val_str})", className="text-success")])
            else:
                val1_str = str(val1) if val1 is not None else "N/A"
                val2_str = str(val2) if val2 is not None else "N/A"
                if isinstance(val1, bool): val1_str = ("Aktif" if val1 else "Kapalı")
                if isinstance(val2, bool): val2_str = ("Aktif" if val2 else "Kapalı")
                return html.Tr([html.Td(label), html.Td(f"{text_false} (1: {val1_str} | 2: {val2_str})",
                                                        className="text-danger fw-bold")])

        table_body = [
            html.Tr([html.Td("Genel Durum", className="fw-bold"),
                     html.Td([summary_text, html.I(className=f"{summary_icon} ms-2")],
                             className=f"h5 {summary_class}")]),

            html.Tr(
                [html.Td("SSIM", className="fw-bold"), html.Td(f"{ssim_percent:.2f}%", className=f"h5 {ssim_class}")]),
            html.Tr([html.Td("pHash", className="fw-bold"), html.Td(phash_text, className=f"h5 {phash_class}")]),
            html.Tr([html.Td("ORB", className="fw-bold"),
                     html.Td(f"{orb_match_percent:.2f}% ({orb_total_features[0]}/{orb_total_features[1]})",
                             className=f"h5 {orb_class}")]),
            html.Tr([html.Td("MSE", className="fw-bold"), html.Td(f"{mse_score:.2f}", className=f"h5 {mse_class}")]),

            html.Tr([html.Td("Açı Farkı"), html.Td(f"{angle_diff:.1f}°")]),
            html.Tr([html.Td("Zaman Farkı"), html.Td(f"{time_diff}")]),

            compare_row("Çözünürlük", p1.resolution, p2.resolution),
            compare_row("FrameRate", p1.framerate, p2.framerate),
            compare_row("Lens Düzeltme", p1.lens_correction, p2.lens_correction),
            compare_row("Auto Exposure", p1.ae_enable, p2.ae_enable),
            compare_row("Auto WB", p1.awb_enable, p2.awb_enable),

            html.Tr([html.Td("SHA256"), sha_td]),
        ]

        stats_row = dbc.Row([
            dbc.Col(
                dbc.Table(table_body, bordered=True, striped=True, hover=True, color="dark"),
                md=12
            )
        ], className="mt-3")

        return html.Div([image_row, stats_row])

    except Exception as e:
        logger.error(f"Karşılaştırma hatası: {e}", exc_info=True)
        return html.Div(f"❌ Hata: {str(e)}", className="alert alert-danger")


# ============================================================================
# CALLBACKS - MOTOR (BİRLEŞTİRİLMİŞ)
# ============================================================================
@app.callback(
    [Output('motor-status-display', 'children'),
     Output('pan-slider', 'value')],
    Input('motor-update-interval', 'n_intervals'),
    prevent_initial_call=False # Sayfa yüklendiğinde de çalış
)
def update_motor_status_interval(n):
    """
    Motorun mevcut durumunu periyodik olarak günceller (Ana Callback).
    Slider'ı motorun GERÇEK açısıyla senkronize eder.
    """
    if not hardware_manager._initialized.get('motor'):
        status_div = html.Div([
            html.I(className="fa-solid fa-times text-danger me-2"),
            "Motor başlatılmamış!"
        ])
        return (status_div, 0)

    motor_info = hardware_manager.get_motor_info()

    if motor_info['is_moving']:
        status_div = html.Div([
            html.I(className="fa-solid fa-spinner fa-spin text-warning me-2"),
            f"{motor_info['angle']:.1f}° → {motor_info.get('target_angle', '?'):.1f}°"
        ])
    else:
        status_div = html.Div([
            html.I(className="fa-solid fa-check text-success me-2"),
            f"{motor_info['angle']:.1f}° (Hazır)"
        ])

    # Slider'ı motorun gerçek açısıyla senkronize et
    return (status_div, motor_info['angle'])

@app.callback(
    Output('motor-status-display', 'children', allow_duplicate=True),
    Input('pan-slider', 'value'),
    State('speed-profile-radio', 'value'), # <-- DÜZELTİLDİ
    prevent_initial_call=True
)
def control_motor_slider(slider_value, speed_profile): # <-- DÜZELTİLDİ
    """Slider ile motoru ASENKRON olarak hareket ettirir."""

    # Interval'in slider'ı güncellemesi bu callback'i tetiklemesin diye kontrol
    current_angle = hardware_manager.get_motor_angle()
    if slider_value is None or abs(slider_value - current_angle) < MotorConfig.FINE_STEP:
        raise PreventUpdate

    logger.info(f"🎚️ SLIDER DEĞİŞTİ -> {slider_value}°")
    slider_value = float(slider_value)

    # ASENKRON (wait=False)
    success = hardware_manager.move_to_angle(
        slider_value,
        speed_profile=speed_profile,
        force=False,  # Kuyruğa ekle
        wait=False,
        timeout=10.0
    )

    if success:
        status_div = html.Div([
            html.I(className="fa-solid fa-gauge text-info me-2"),
            f"Slider komutu: {slider_value:.1f}°"
        ])
    else:
        logger.error("❌ Slider hareketi BAŞARISIZ!")
        status_div = html.Div([
            html.I(className="fa-solid fa-exclamation-triangle text-danger me-2"),
            "Slider BAŞARISIZ!"
        ])

    return status_div


@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input('stop-motor-btn', 'n_clicks'),
    prevent_initial_call=True
)
def control_motor_stop(n_clicks):
    """Motor hareketini iptal eder."""
    if not n_clicks:
        raise PreventUpdate

    logger.info("🛑 STOP BUTONU BASILDI")
    hardware_manager.cancel_movement()
    current_angle = hardware_manager.get_motor_angle() # Durdurulan açıyı al

    status_div = html.Div([
        html.I(className="fa-solid fa-stop text-warning me-2"),
        f"Durduruldu ({current_angle:.1f}°)"
    ])
    logger.info(f"✅ Motor durduruldu: {current_angle:.1f}°")
    return (status_div, current_angle)


@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input('home-btn', 'n_clicks'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_home(n_clicks, speed_profile):
    """Motoru ASENKRON olarak 0° pozisyonuna (Home) gönderir."""
    if not n_clicks:
        raise PreventUpdate

    logger.info("🏠 HOME BUTONU - ASENKRON HAREKET")

    # ASENKRON (wait=False)
    success = hardware_manager.move_to_angle(
        0,
        speed_profile='normal',
        force=True,
        wait=False,
        timeout=10.0
    )

    if success:
        logger.info("✅ Home komutu kuyruğa eklendi: 0°")
        status_div = html.Div([
            html.I(className="fa-solid fa-home text-success me-2"),
            "Home (0°) komutu gönderildi..."
        ])
        return (status_div, 0) # Slider'ı 0'a çek
    else:
        logger.error("❌ Home komutu BAŞARISIZ!")
        status_div = html.Div([
            html.I(className="fa-solid fa-exclamation-triangle text-danger me-2"),
            "Home BAŞARISIZ!"
        ])
        return (no_update, no_update)



@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': -90}, 'n_clicks'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_btn_n90(n_clicks, speed_profile):
    """Motoru -90°'ye ASENKRON olarak gönderir."""
    if not n_clicks: raise PreventUpdate
    logger.info("🎯 MOTOR BUTONU -90° - ASENKRON")
    hardware_manager.move_to_angle(-90, speed_profile=speed_profile, force=True, wait=False)
    return (html.Div("Komut: -90°", className="text-info"), -90)

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': -10}, 'n_clicks'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_btn_n10(n_clicks, speed_profile):
    """Motoru mevcut açıdan -10° geriye ASENKRON olarak gönderir."""
    if not n_clicks: raise PreventUpdate
    logger.info("🎯 MOTOR BUTONU -10° - ASENKRON")
    current_angle = hardware_manager.get_motor_angle()
    target_angle = max(MotorConfig.MIN_ANGLE, current_angle - 10) # Min sınırın altına inme
    hardware_manager.move_to_angle(target_angle, speed_profile=speed_profile, force=True, wait=False)
    return (html.Div(f"Komut: {target_angle:.1f}°", className="text-info"), target_angle)

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': 0}, 'n_clicks'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_btn_0(n_clicks, speed_profile):
    """Motoru 0°'ye ASENKRON olarak gönderir."""
    if not n_clicks: raise PreventUpdate
    logger.info("🎯 MOTOR BUTONU 0° - ASENKRON")
    hardware_manager.move_to_angle(0, speed_profile=speed_profile, force=True, wait=False)
    return (html.Div("Komut: 0°", className="text-info"), 0)

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': 10}, 'n_clicks'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_btn_p10(n_clicks, speed_profile):
    """Motoru mevcut açıdan +10° ileriye ASENKRON olarak gönderir."""
    if not n_clicks: raise PreventUpdate
    logger.info("🎯 MOTOR BUTONU +10° - ASENKRON")
    current_angle = hardware_manager.get_motor_angle()
    target_angle = min(MotorConfig.MAX_ANGLE, current_angle + 10) # Max sınırın üstüne çıkma
    hardware_manager.move_to_angle(target_angle, speed_profile=speed_profile, force=True, wait=False)
    return (html.Div(f"Komut: {target_angle:.1f}°", className="text-info"), target_angle)

@app.callback(
    [Output('motor-status-display', 'children', allow_duplicate=True),
     Output('pan-slider', 'value', allow_duplicate=True)],
    Input({'type': 'motor-btn', 'index': 90}, 'n_clicks'),
    State('speed-profile-radio', 'value'),
    prevent_initial_call=True
)
def control_motor_btn_p90(n_clicks, speed_profile):
    """Motoru +90°'ye ASENKRON olarak gönderir."""
    if not n_clicks: raise PreventUpdate
    logger.info("🎯 MOTOR BUTONU +90° - ASENKRON")
    hardware_manager.move_to_angle(90, speed_profile=speed_profile, force=True, wait=False)
    return (html.Div("Komut: +90°", className="text-info"), 90)


# ============================================================================
# CALLBACKS - SENSOR
# ============================================================================
@app.callback(
    Output('sensor-store', 'data', allow_duplicate=True),
    Input('sensor-switch', 'value'),
    State('sensor-store', 'data'),
    prevent_initial_call='initial_duplicate'  # ✅ Değiştir
)
def sensor_switch(enabled, store):
    """Sensör aç/kapat"""
    if store is None:
        store = {'sensor_enabled': False, 'sensor_history': [], 'reading_count': 0}

    try:
        if enabled:
            if not hardware_manager._initialized.get('sensor'):
                hardware_manager.initialize_sensor()
            hardware_manager.start_continuous_sensor_reading()

            updated_store = store.copy()
            updated_store['sensor_enabled'] = True
            return updated_store
        else:
            hardware_manager.stop_continuous_sensor_reading()

            updated_store = store.copy()
            updated_store['sensor_enabled'] = False
            return updated_store

    except Exception as e:
        logger.error(f"Sensor switch hatası: {e}")
        return store if store else {'sensor_enabled': False, 'sensor_history': [], 'reading_count': 0}


@app.callback(
    [Output('current-distance', 'children'),
     Output('last-reading-time', 'children')],
    Input('metrics-interval', 'n_intervals'),
    prevent_initial_call=False
)
def sensor_display(n):
    """Sensör mesafesini göster"""
    if not hardware_manager.is_sensor_active():
        return ("⏹️ Kapalı", "-")

    dist = hardware_manager.get_current_distance()
    if dist:
        return (html.H1(format_distance(dist), className="text-success pulse"), datetime.now().strftime('%H:%M:%S'))
    return ("⏳ Bekleniyor...", "-")


@app.callback(
    Output('sensor-store', 'data', allow_duplicate=True),
    Input('metrics-interval', 'n_intervals'),
    State('sensor-store', 'data'),
    prevent_initial_call='initial_duplicate'  # ✅ Değiştir
)
def sensor_history(n, store):
    """Sensör geçmişini kaydet"""
    if store is None:
        store = {'sensor_enabled': False, 'sensor_history': [], 'reading_count': 0}

    if not hardware_manager.is_sensor_active():
        return store

    dist = hardware_manager.get_current_distance()
    if not dist:
        return store

    history = store.get('sensor_history', [])
    history.append({'distance': dist, 'timestamp': datetime.now().isoformat()})
    if len(history) > 100:
        history = history[-100:]

    updated_store = store.copy()
    updated_store['sensor_history'] = history
    updated_store['reading_count'] = store.get('reading_count', 0) + 1
    return updated_store


@app.callback(
    Output('distance-chart', 'children'),
    Input('metrics-interval', 'n_intervals'),
    State('sensor-store', 'data'),
    prevent_initial_call=False
)
def mini_chart(n, store):
    """Mesafe grafiği"""
    if store is None:
        store = {'sensor_history': []}

    history = store.get('sensor_history', [])
    if len(history) < 2:
        return html.Div("Veri bekleniyor...", className="text-muted small")

    distances = [h['distance'] for h in history[-50:]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=distances,
        mode='lines',
        line=dict(color='#0f0', width=2),
        fill='tozeroy'
    ))
    fig.update_layout(
        height=120,
        margin=dict(l=30, r=10, t=10, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(26,26,26,1)',
        xaxis=dict(showgrid=False, showticklabels=False),
        yaxis=dict(title="cm", gridcolor='rgba(255,255,255,0.1)'),
        showlegend=False
    )
    return dcc.Graph(figure=fig, config={'displayModeBar': False}, style={'height': '120px'})


@app.callback(
    [Output('current-pan-angle', 'children'),
     Output('current-sensor-distance', 'children'),
     Output('reading-count', 'children')],
    Input('metrics-interval', 'n_intervals'),
    State('sensor-store', 'data'),
    prevent_initial_call='initial_duplicate'
)
def stats(n, store):
    """Sistem istatistikleri"""
    if store is None:
        store = {'reading_count': 0}

    angle = hardware_manager.get_motor_angle()
    dist = hardware_manager.get_current_distance()
    count = store.get('reading_count', 0)
    return (f"{angle:.1f}°", format_distance(dist) if dist else "-", str(count))


# ============================================================================
# CALLBACKS - AI VISION
# ============================================================================

@app.callback(
    [Output('yolo-settings-div', 'style'),
     Output('motion-settings-div', 'style')],
    Input('ai-modules-checklist', 'value'),
    prevent_initial_call='initial_duplicate'
)
def toggle_ai_settings(selected_modules):
    """Seçili modüle göre ayarları göster"""
    yolo_style = {'display': 'block'} if 'yolo' in (selected_modules or []) else {'display': 'none'}
    motion_style = {'display': 'block'} if 'motion' in (selected_modules or []) else {'display': 'none'}
    return yolo_style, motion_style


@app.callback(
    [Output('ai-processed-image', 'src'),
     Output('edge-detection-image', 'src'),
     Output('yolo-count', 'children'),
     Output('face-count', 'children'),
     Output('motion-count', 'children'),
     Output('qr-count', 'children'),
     Output('detection-list', 'children'),
     Output('motion-percentage-gauge', 'figure')],
    Input('single-ai-snapshot-btn', 'n_clicks'),
    [State('ai-modules-checklist', 'value'),
     # --- YENİ EKLENEN STATE'LER ---
     State('resolution-select-radio', 'value'),
     State('current-photo-store', 'data'),
     State('framerate-slider', 'value'),
     State('lens-correction-switch', 'value'),
     State('ae-enable-switch', 'value'),
     State('awb-enable-switch', 'value'),
     State('exposure-time-slider', 'value'),
     State('iso-gain-slider', 'value'),
     State('brightness-slider', 'value'),
     State('contrast-slider', 'value'),
     State('saturation-slider', 'value'),
     State('sharpness-slider', 'value'),
     State('awb-mode-dropdown', 'value'),
     State('colour-effect-dropdown', 'value'),
     State('flicker-mode-dropdown', 'value'),
     State('exposure-mode-dropdown', 'value'),
     State('metering-mode-dropdown', 'value')],
    prevent_initial_call='initial_duplicate'
)
def single_ai_snapshot(n_clicks, modules,
                       # --- YENİ EKLENEN ARGÜMANLAR ---
                       resolution_str, photo_store, framerate, lens_correction, ae_enable, awb_enable,
                       exposure_time, analogue_gain, brightness, contrast, saturation, sharpness,
                       awb_mode, colour_effect, flicker_mode, exposure_mode, metering_mode):
    """Tek çekim AI analizi - Artık tüm kamera ayarlarını kullanıyor"""

    # Hata durumunda boş döndür
    error_return = ("", "", "0", "0", "0", "0", [], {})

    if not n_clicks:
        return error_return

    if not modules:
        return (
            "", "", "?", "?", "?", "?",
            [html.Div([
                html.I(className="fa-solid fa-exclamation-triangle me-2 text-warning"),
                "Lütfen en az bir modül seçin"
            ], className="alert alert-warning")],
            {}
        )

    try:
        logger.info(f"🔍 AI snapshot (Tüm Ayarlarla) başlatılıyor: {modules}")

        # --- FOTOĞRAF ÇEKME LOGIĞI (capture_photo_ultimate'den kopyalandı) ---

        # FALLBACK: Eğer resolution_str None ise store'dan al
        if not resolution_str or resolution_str is None:
            if photo_store and 'selected_resolution' in photo_store:
                resolution_str = photo_store['selected_resolution']
                logger.warning(f"AI Snapshot: Çözünürlük State'ten alınamadı, store'dan kullanıldı: {resolution_str}")
            else:
                logger.error("AI Snapshot: Çözünürlük hem State hem Store'da yok! Varsayılan kullanılıyor.")
                resolution_str = "1280x720"  # Varsayılan

        if not resolution_str or 'x' not in str(resolution_str):
            logger.error(f"AI Snapshot: Geçersiz çözünürlük: {resolution_str}")
            return error_return

        parts = str(resolution_str).split('x')
        if len(parts) != 2: raise ValueError("Çözünürlük formatı hatalı")
        w_str, h_str = parts
        resolution_tuple = (int(w_str.strip()), int(h_str.strip()))

        if not (320 <= resolution_tuple[0] <= 2592): raise ValueError(f"Genişlik sınır dışı: {resolution_tuple[0]}")
        if not (240 <= resolution_tuple[1] <= 1944): raise ValueError(f"Yükseklik sınır dışı: {resolution_tuple[1]}")

        validated_fps = CameraConfig.validate_framerate(float(framerate), resolution_tuple)
        if validated_fps != framerate:
            logger.warning(f"AI Snapshot: FPS {framerate} -> {validated_fps} ayarlandı")

        try:
            logger.debug(f"AI Snapshot: {resolution_tuple} @ {validated_fps}fps ile çekim yapılıyor...")
            frame = hardware_manager.capture_frame(
                resolution=resolution_tuple,
                framerate=validated_fps,
                apply_lens_correction=lens_correction,
                ae_enable=ae_enable,
                awb_enable=awb_enable,
                exposure_time=int(exposure_time) if not ae_enable else None,
                analogue_gain=float(analogue_gain) if not ae_enable else None,
                brightness=float(brightness),
                contrast=float(contrast),
                saturation=float(saturation),
                sharpness=float(sharpness),
                awb_mode=awb_mode,
                colour_effect=colour_effect,
                flicker_mode=flicker_mode,
                exposure_mode=exposure_mode,
                metering_mode=metering_mode,
            )
        except TypeError:
            logger.warning("AI Snapshot: Hardware manager güncel değil, temel ayarlar kullanılıyor")
            frame = hardware_manager.capture_frame(
                resolution=resolution_tuple,
                framerate=validated_fps,
                apply_lens_correction=lens_correction,
                ae_enable=ae_enable,
                awb_enable=awb_enable,
            )

        # --- FOTOĞRAF ÇEKME LOGIĞI BİTTİ ---

        if frame is None:
            logger.error("AI Snapshot: Frame alınamadı")
            return (
                "", "", "!", "!", "!", "!",
                [html.Div("❌ Frame alınamadı", className="alert alert-danger")],
                {}
            )

        logger.info(f"AI Snapshot: Frame alındı ({frame.shape[1]}x{frame.shape[0]}), işleniyor...")

        # AI İŞLEME
        processed_frame, results = ai_vision_manager.process_frame(
            frame,
            modules=modules,
            draw_results=True
        )

        processed_b64 = image_to_base64(processed_frame, quality=80)

        edge_b64 = ""
        if results.get('edge_frame') is not None:
            edge_b64 = image_to_base64(results['edge_frame'], quality=70)

        stats = results.get('stats', {})
        yolo_c = stats.get('yolo_objects', 0)
        face_c = stats.get('faces', 0)
        motion_c = stats.get('motion_regions', 0)
        qr_c = stats.get('qr_codes', 0)

        detections = results.get('detections', [])
        detection_items = []

        for i, det in enumerate(detections[:20]):
            color_rgb = f"rgb({det.color[2]}, {det.color[1]}, {det.color[0]})"

            item = html.Div([
                html.Span(f"#{i + 1} ", className="badge bg-secondary me-2"),
                html.Span(det.label, className="fw-bold", style={'color': color_rgb}),
                html.Span(f" ({det.confidence:.2f})", className="text-muted ms-2"),
                html.Br(),
                html.Small(
                    f"Konum: x={det.bbox[0]}, y={det.bbox[1]}, w={det.bbox[2]}, h={det.bbox[3]}",
                    className="text-muted ms-4"
                )
            ], className="mb-2 p-2", style={
                'borderLeft': f'4px solid {color_rgb}',
                'backgroundColor': 'rgba(255,255,255,0.05)',
                'borderRadius': '4px'
            })
            detection_items.append(item)

        if not detection_items:
            detection_items = [html.Div([
                html.I(className="fa-solid fa-info-circle me-2"),
                "Hiçbir şey tespit edilmedi"
            ], className="text-muted")]

        motion_pct = results.get('motion_percentage', 0.0)
        gauge_fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=motion_pct,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "Hareket %", 'font': {'color': 'white'}},
            delta={'reference': 20, 'increasing': {'color': "red"}},
            gauge={
                'axis': {'range': [None, 100], 'tickcolor': 'white'},
                'bar': {'color': "orange"},
                'bgcolor': "rgba(0,0,0,0)",
                'steps': [
                    {'range': [0, 20], 'color': "rgba(50,50,50,0.5)"},
                    {'range': [20, 50], 'color': "rgba(100,100,0,0.5)"},
                    {'range': [50, 100], 'color': "rgba(150,0,0,0.5)"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.75,
                    'value': 50
                }
            }
        ))

        gauge_fig.update_layout(
            height=200,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            font={'color': 'white', 'size': 14}
        )

        logger.info(f"AI Snapshot tamamlandı. {len(detections)} nesne bulundu.")

        return (
            processed_b64,
            edge_b64,
            str(yolo_c),
            str(face_c),
            str(motion_c),
            str(qr_c),
            detection_items,
            gauge_fig
        )

    except Exception as e:
        logger.error(f"AI snapshot hatası: {e}", exc_info=True)
        return (
            "", "", "!", "!", "!", "!",
            [html.Div(f"❌ Hata: {str(e)}", className="alert alert-danger")],
            {}
        )


@app.callback(
    [Output('ai-status-indicator', 'children'),
     Output('start-ai-processing-btn', 'disabled'),
     Output('stop-ai-processing-btn', 'disabled'),
     Output('ai-processing-state', 'data')],
    [Input('start-ai-processing-btn', 'n_clicks'),
     Input('stop-ai-processing-btn', 'n_clicks')],
    [State('ai-modules-checklist', 'value'),
     State('yolo-confidence-slider', 'value'),
     State('motion-threshold-slider', 'value'),
     State('ai-processing-state', 'data')],
    prevent_initial_call='initial_duplicate'
)
def control_ai_processing(start_clicks, stop_clicks, modules, yolo_conf, motion_thresh, state):
    """AI işleme kontrol"""

    start_clicks = start_clicks or 0
    stop_clicks = stop_clicks or 0

    if start_clicks == 0 and stop_clicks == 0:
        return (
            html.Div("Hazır", className="alert alert-secondary"),
            False, True,
            {'is_running': False, 'last_start_click': 0, 'last_stop_click': 0}
        )

    if state is None:
        state = {'is_running': False, 'last_start_click': 0, 'last_stop_click': 0}

    last_start = state.get('last_start_click', 0)
    last_stop = state.get('last_stop_click', 0)

    start_clicked = start_clicks > last_start
    stop_clicked = stop_clicks > last_stop

    if stop_clicked:
        for module in ['yolo', 'face', 'motion', 'qr', 'edges']:
            ai_vision_manager.enabled_modules[module] = False

        new_state = {
            'is_running': False,
            'last_start_click': last_start,
            'last_stop_click': stop_clicks
        }

        return (
            html.Div([
                html.I(className="fa-solid fa-stop-circle me-2"),
                "⏹️ AI işleme durduruldu"
            ], className="alert alert-danger"),
            False, True, new_state
        )

    if start_clicked:
        if not modules:
            return (
                html.Div([
                    html.I(className="fa-solid fa-exclamation-triangle me-2"),
                    "⚠️ Lütfen en az bir modül seçin!"
                ], className="alert alert-warning"),
                False, True, state
            )

        logger.info(f"AI işleme başlatılıyor: {modules}")

        success_count = 0
        messages = []

        for module in modules:
            try:
                if module == 'yolo':
                    success = ai_vision_manager.initialize_module(
                        'yolo', confidence=yolo_conf, iou=0.4
                    )
                elif module == 'motion':
                    success = ai_vision_manager.initialize_module(
                        'motion', min_area=500, threshold=motion_thresh
                    )
                else:
                    success = ai_vision_manager.initialize_module(module)

                if success:
                    success_count += 1
                    messages.append(html.Li([
                        html.I(className="fa-solid fa-check text-success me-2"),
                        f"{module.upper()}"
                    ]))
                else:
                    messages.append(html.Li([
                        html.I(className="fa-solid fa-times text-danger me-2"),
                        f"{module.upper()} (başlatılamadı)"
                    ]))
            except Exception as e:
                logger.error(f"Modül başlatma hatası ({module}): {e}")
                messages.append(html.Li([
                    html.I(className="fa-solid fa-times text-danger me-2"),
                    f"{module.upper()} (hata)"
                ]))

        new_state = {
            'is_running': True,
            'last_start_click': start_clicks,
            'last_stop_click': last_stop
        }

        if success_count == 0:
            new_state['is_running'] = False
            return (
                html.Div([
                    html.I(className="fa-solid fa-times-circle me-2"),
                    "❌ Hiçbir modül başlatılamadı!",
                    html.Ul(messages, className="mt-2")
                ], className="alert alert-danger"),
                False, True, new_state
            )

        return (
            html.Div([
                html.H6([
                    html.I(className="fa-solid fa-rocket me-2"),
                    f"🚀 {success_count}/{len(modules)} modül aktif"
                ], className="text-success mb-2"),
                html.Ul(messages, className="mb-0")
            ], className="alert alert-success"),
            True, False, new_state
        )

    return (
        html.Div("Hazır", className="alert alert-secondary"),
        False, True, state
    )


# ============================================================================
# UYGULAMA BAŞLATMA
# ============================================================================

logger.info("=" * 60)
logger.info("DREAM PI - ULTIMATE CONTROL PANEL")
logger.info(f"v{AppConfig.APP_VERSION} | GPIO: {GPIO_AVAILABLE}")
logger.info("Tam Manuel Kamera Kontrolü + AI Vision Aktif")
logger.info("=" * 60)
