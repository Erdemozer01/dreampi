# scanner/admin.py - DÜZELTME v3.19 (Sadece Ham Fark Verisi TXT)
import logging
from django.contrib import admin
from django.utils.html import format_html

from django.utils.safestring import mark_safe

from django.http import HttpResponse
from django import forms
from scanner.models import (
    Scan, ScanPoint, AIModelConfiguration,
    CameraCapture, SystemLog
)
import json
import csv
from io import StringIO
from datetime import datetime

# Logger (ZORUNLU)
logger = logging.getLogger(__name__)


# ============================================================================
# INLINE CLASSES
# ============================================================================

class ScanPointInline(admin.TabularInline):
    model = ScanPoint
    extra = 0
    readonly_fields = (
        'derece', 'dikey_aci', 'mesafe_cm',
        'h_sensor_distance', 'v_sensor_distance',
        'hiz_cm_s', 'timestamp', 'x_cm', 'y_cm', 'z_cm'
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# ============================================================================
# CAMERA CAPTURE ADMIN (GÜVENLİK DÜZELTMELİ)
# ============================================================================

@admin.register(CameraCapture)
class CameraCaptureAdmin(admin.ModelAdmin):
    """
    Kamera fotoğrafları için admin paneli
    v3.19 - Tüm format_html/mark_safe hataları düzeltildi
    """

    # === LİST GÖRÜNÜMÜ ===
    list_display = [
        'id',
        'get_image_preview',
        'timestamp',
        'settings_summary_display',
        'pan_angle',
        'distance_info',
        'effect',
        'image_size_display'
    ]

    list_filter = [
        'effect',
        'timestamp',
        'ae_enable',
        'awb_enable',
        'awb_mode',
        'resolution',
        'lens_correction',
    ]

    search_fields = ['distance_info', 'id', 'resolution']

    readonly_fields = [
        'timestamp',
        'get_full_image',
        'base64_info',
        'settings_summary',
        'image_size_kb',
        'image_size_mb',
    ]

    date_hierarchy = 'timestamp'

    # === SAYFALAMA ===
    list_per_page = 20
    list_max_show_all = 100

    # === DETAY GÖRÜNÜMÜ (FIELDSETS) ===
    fieldsets = (
        ('📸 Görüntü', {
            'fields': ('get_full_image', 'effect'),
            'description': 'Çekilen fotoğraf ve uygulanan efekt'
        }),
        ('📍 Konum Bilgileri', {
            'fields': ('pan_angle', 'distance_info', 'timestamp')
        }),
        ('⚙️ Temel Ayarlar', {
            'fields': (
                'resolution',
                'framerate',
                'lens_correction',
                'image_format',
                'image_size_kb',
                'image_size_mb',
            )
        }),
        ('🤖 Otomatik Kontroller', {
            'fields': ('ae_enable', 'awb_enable', 'awb_mode'),
            'description': 'Otomatik pozlama ve beyaz dengesi ayarları'
        }),
        ('📷 Manuel Pozlama (AE Kapalıysa)', {
            'fields': ('exposure_time', 'analogue_gain'),
            'classes': ('collapse',),
            'description': 'Manuel shutter speed ve ISO ayarları'
        }),
        ('🎨 Görüntü İyileştirme', {
            'fields': ('brightness', 'contrast', 'saturation', 'sharpness'),
            'classes': ('collapse',),
            'description': 'Parlaklık, kontrast, doygunluk ve keskinlik'
        }),
        ('🔬 Gelişmiş Modlar', {
            'fields': (
                'colour_effect',
                'ae_flicker_mode',
                'exposure_mode',
                'metering_mode'
            ),
            'classes': ('collapse',),
            'description': 'Renk efektleri ve gelişmiş kamera modları'
        }),
        ('💾 Base64 Bilgisi', {
            'fields': ('base64_info',),
            'classes': ('collapse',),
            'description': '⚠️ Güvenlik nedeniyle tam base64 admin panelinde gösterilmez. Download için action kullanın.'
        })
    )

    # === GÖRÜNTÜ ÖNİZLEME (LİST VİEW) ===
    def get_image_preview(self, obj):
        """List view için küçük thumbnail (TAM DÜZELTİLMİŞ)"""
        from django.utils.html import escape

        if not obj.base64_image:
            return mark_safe('<span style="color: gray;">❌ No image</span>')

        try:
            # String kontrolü
            if not isinstance(obj.base64_image, str):
                logger.error(f"ID {obj.id}: base64_image string değil, tip: {type(obj.base64_image)}")
                return mark_safe('<span style="color: red;">❌ Geçersiz tip</span>')

            # Uzunluk kontrolü
            if len(obj.base64_image) < 50:
                logger.error(f"ID {obj.id}: base64_image çok kısa ({len(obj.base64_image)} karakter)")
                return mark_safe('<span style="color: orange;">⚠️ Veri eksik</span>')

            # Data URI formatı kontrolü ve düzeltme
            if obj.base64_image.startswith('data:image'):
                # Doğru format
                img_src = obj.base64_image
            elif obj.base64_image.startswith('/9j/') or obj.base64_image.startswith('iVBORw0KGgo'):
                # Raw base64 JPEG veya PNG, prefix ekle
                img_src = f"data:image/jpeg;base64,{obj.base64_image}"
                logger.info(f"ID {obj.id}: Data URI prefix eklendi")
            else:
                # İlk karakterlere bak
                first_chars = escape(obj.base64_image[:50])
                logger.warning(f"ID {obj.id}: Bilinmeyen format. İlk 50 karakter: {first_chars}")
                return mark_safe(f'<span style="color: orange;" title="{first_chars}">⚠️ Bilinmeyen format</span>')

            # HTML oluştur
            size_kb = len(obj.base64_image) / 1024 if obj.base64_image else 0
            return mark_safe(
                f'<img src="{img_src}" width="100" height="75" '
                f'style="object-fit: cover; border-radius: 5px; border: 2px solid #28a745;" '
                f'title="ID: {obj.id} | Boyut: {size_kb:.1f} KB" />'
            )

        except Exception as e:
            error_msg = escape(str(e)[:100])
            logger.error(f"ID {obj.id}: Preview oluşturma hatası: {e}", exc_info=True)
            return mark_safe(f'<span style="color: red;" title="{error_msg}">❌ Hata</span>')

    get_image_preview.short_description = '🖼️ Önizleme'

    # === TAM GÖRÜNTÜ (DETAIL VIEW) ===
    def get_full_image(self, obj):
        """Detail view için tam boyutlu görüntü (TAM DÜZELTİLMİŞ v3.17)"""
        # XSS Koruması için eklendi
        from django.utils.html import escape

        if not obj.base64_image:
            return mark_safe(
                '<div style="padding: 20px; background: #f8d7da; border: 2px solid #dc3545; border-radius: 5px;">'
                '<h4 style="color: #721c24; margin-top: 0;">❌ Görüntü Yok</h4>'
                '<p style="color: #721c24;">Bu kayıtta base64_image verisi bulunmuyor.</p>'
                '<p style="color: #721c24; margin-bottom: 0;">'
                '<strong>Çözüm:</strong> Kameradan yeni bir fotoğraf çekin.'
                '</p></div>'
            )

        try:
            # String kontrolü
            if not isinstance(obj.base64_image, str):
                return mark_safe(
                    f'<div style="padding: 20px; background: #f8d7da; border: 2px solid #dc3545; border-radius: 5px;">'
                    f'<h4 style="color: #721c24;">❌ Geçersiz Veri Tipi</h4>'
                    f'<p style="color: #721c24;">base64_image string değil: <code>{type(obj.base64_image).__name__}</code></p>'
                    f'</div>'
                )

            # Uzunluk kontrolü
            data_length = len(obj.base64_image)
            if data_length < 50:
                return mark_safe(
                    f'<div style="padding: 20px; background: #fff3cd; border: 2px solid #ffc107; border-radius: 5px;">'
                    f'<h4 style="color: #856404; margin-top: 0;">⚠️ Veri Çok Kısa</h4>'
                    f'<p style="color: #856404;">base64_image sadece <strong>{data_length}</strong> karakter içeriyor.</p>'
                    f'<p style="color: #856404; margin-bottom: 0;">'
                    f'Geçerli bir görüntü için en az 1000 karakter beklenir.</p></div>'
                )

            # Boyut kontrolü
            size_mb = obj.image_size_mb
            if size_mb is None:
                size_mb = data_length / 1024 / 1024

            # Güvenlik: Maksimum 5MB göster
            if size_mb > 5:
                first_50 = escape(obj.base64_image[:50])  # XSS Koruması
                format_check = "Data URI ✓" if obj.base64_image.startswith('data:image') else "Raw Base64"
                return mark_safe(
                    f'<div style="padding: 20px; background: #fff3cd; border: 2px solid #ffc107; border-radius: 5px;">'
                    f'<h4 style="color: #856404; margin-top: 0;">⚠️ Güvenlik Uyarısı</h4>'
                    f'<p style="color: #856404;">Bu görüntü <strong style="font-size: 1.2em;">{size_mb:.2f} MB</strong> boyutunda.</p>'
                    f'<p style="color: #856404;">Tarayıcı performansı için admin panelinde gösterilmiyor.</p>'
                    f'<ul style="color: #856404;">'
                    f'<li><strong>Toplam karakter:</strong> {data_length:,}</li>'
                    f'<li><strong>İlk 50 karakter:</strong> <code style="background: #ffe69c; padding: 2px 6px; border-radius: 3px;">{first_50}</code></li>'
                    f'<li><strong>Format kontrolü:</strong> {format_check}</li>'
                    f'</ul>'
                    f'<p style="color: #856404; margin-bottom: 0;">'
                    f'<strong>Çözüm:</strong> Liste görünümünden "Base64\'ü Export Et" action\'ını kullanın.'
                    f'</p></div>'
                )

            # Data URI kontrolü
            if obj.base64_image.startswith('data:image'):
                img_src = obj.base64_image
                format_status = "✓ Data URI formatı (doğru)"
            elif obj.base64_image.startswith('/9j/'):
                # Raw base64 JPEG, prefix ekle
                img_src = f"data:image/jpeg;base64,{obj.base64_image}"
                format_status = "✓ JPEG Base64 (prefix eklendi)"
                logger.info(f"ID {obj.id}: Data URI prefix eklendi (JPEG)")
            elif obj.base64_image.startswith('iVBORw0KGgo'):
                # Raw base64 PNG, prefix ekle
                img_src = f"data:image/png;base64,{obj.base64_image}"
                format_status = "✓ PNG Base64 (prefix eklendi)"
                logger.info(f"ID {obj.id}: Data URI prefix eklendi (PNG)")
            else:
                # Bilinmeyen format (XSS KORUMASI EKLENDİ)
                first_100 = escape(obj.base64_image[:100])
                return mark_safe(
                    f'<div style="padding: 20px; background: #fff3cd; border: 2px solid #ffc107; border-radius: 5px;">'
                    f'<h4 style="color: #856404; margin-top: 0;">⚠️ Bilinmeyen Format</h4>'
                    f'<p style="color: #856404;">base64_image beklenen formatta değil.</p>'
                    f'<ul style="color: #856404;">'
                    f'<li><strong>Uzunluk:</strong> {data_length:,} karakter</li>'
                    f'<li><strong>İlk 100 karakter:</strong><br/>'
                    f'<code style="background: #ffe69c; padding: 5px; border-radius: 3px; display: block; overflow-x: auto;">{first_100}</code></li>'
                    f'</ul>'
                    f'<p style="color: #856404;"><strong>Beklenen formatlar:</strong></p>'
                    f'<ul style="color: #856404; margin-bottom: 0;">'
                    f'<li><code>data:image/jpeg;base64,...</code> (tercih edilen)</li>'
                    f'<li><code>/9j/...</code> (raw JPEG base64)</li>'
                    f'<li><code>iVBORw0KGgo...</code> (raw PNG base64)</li>'
                    f'</ul></div>'
                )

            # Görüntüyü göster
            timestamp_str = obj.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            resolution_str = obj.resolution or 'N/A'

            return mark_safe(
                f'<div style="text-align: center; padding: 20px; background: #f8f9fa; border-radius: 8px; border: 1px solid #dee2e6;">'
                f'<div style="margin-bottom: 15px; padding: 10px; background: #d4edda; border: 1px solid #c3e6cb; border-radius: 5px;">'
                f'<p style="margin: 0; color: #155724; font-weight: bold;">✓ Görüntü Başarıyla Yüklendi</p>'
                f'</div>'
                f'<img src="{img_src}" style="max-width: 100%; max-height: 800px; border: 3px solid #28a745; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);" />'
                f'<div style="margin-top: 15px; padding: 15px; background: white; border-radius: 5px; border: 1px solid #dee2e6;">'
                f'<table style="width: 100%; text-align: left; border-collapse: collapse;">'
                f'<tr style="border-bottom: 1px solid #dee2e6;">'
                f'<td style="padding: 8px; font-weight: bold; color: #495057;">ID:</td>'
                f'<td style="padding: 8px; color: #212529;">{obj.id}</td></tr>'
                f'<tr style="border-bottom: 1px solid #dee2e6;">'
                f'<td style="padding: 8px; font-weight: bold; color: #495057;">Boyut:</td>'
                f'<td style="padding: 8px; color: #212529;">{size_mb:.2f} MB ({data_length:,} karakter)</td></tr>'
                f'<tr style="border-bottom: 1px solid #dee2e6;">'
                f'<td style="padding: 8px; font-weight: bold; color: #495057;">Çözünürlük:</td>'
                f'<td style="padding: 8px; color: #212529;">{resolution_str}</td></tr>'
                f'<tr style="border-bottom: 1px solid #dee2e6;">'
                f'<td style="padding: 8px; font-weight: bold; color: #495057;">Format:</td>'
                f'<td style="padding: 8px; color: #28a745;">{format_status}</td></tr>'
                f'<tr><td style="padding: 8px; font-weight: bold; color: #495057;">Timestamp:</td>'
                f'<td style="padding: 8px; color: #212529;">{timestamp_str}</td></tr>'
                f'</table></div></div>'
            )

        except Exception as e:
            logger.error(f"ID {obj.id}: Full image display hatası: {e}", exc_info=True)
            return mark_safe(
                f'<div style="padding: 20px; background: #f8d7da; border: 2px solid #dc3545; border-radius: 5px;">'
                f'<h4 style="color: #721c24; margin-top: 0;">❌ Görüntü Gösterilemedi</h4>'
                f'<p style="color: #721c24;"><strong>Hata:</strong> {str(e)[:200]}</p>'
                f'<p style="color: #721c24;"><strong>ID:</strong> {obj.id}</p>'
                f'<p style="color: #721c24; margin-bottom: 0;">'
                f'<strong>Detaylar için server loglarını kontrol edin.</strong></p></div>'
            )

    get_full_image.short_description = '🖼️ Tam Görüntü'

    # === BASE64 BİLGİSİ ===
    def base64_info(self, obj):
        """Base64 verisi hakkında bilgi (GÜVENLİ)"""
        from django.utils.html import escape

        if not obj.base64_image:
            return mark_safe('<span style="color: gray;">Veri yok</span>')

        try:
            total_length = len(obj.base64_image)
            size_kb = total_length / 1024
            size_mb = size_kb / 1024

            if obj.base64_image.startswith('data:image'):
                parts = obj.base64_image.split(',')
                prefix = parts[0] if len(parts) > 0 else "data:image/jpeg;base64"
                actual_data_length = len(parts[1]) if len(parts) > 1 else 0
            else:
                prefix = "data:image/jpeg;base64"
                actual_data_length = total_length

            return mark_safe(
                f'<div style="padding: 15px; background: #e8f5e9; border: 2px solid #4caf50; border-radius: 8px;">'
                f'<h4 style="margin-top: 0; color: #2e7d32;">📊 Base64 Veri Bilgileri</h4>'
                f'<table style="width: 100%; border-collapse: collapse;">'
                f'<tr style="border-bottom: 1px solid #c8e6c9;">'
                f'<td style="padding: 8px; font-weight: bold;">Toplam Uzunluk:</td>'
                f'<td style="padding: 8px;">{total_length:,} karakter</td></tr>'
                f'<tr style="border-bottom: 1px solid #c8e6c9;">'
                f'<td style="padding: 8px; font-weight: bold;">Boyut (KB):</td>'
                f'<td style="padding: 8px;">{size_kb:.2f} KB</td></tr>'
                f'<tr style="border-bottom: 1px solid #c8e6c9;">'
                f'<td style="padding: 8px; font-weight: bold;">Boyut (MB):</td>'
                f'<td style="padding: 8px;">{size_mb:.3f} MB</td></tr>'
                f'<tr style="border-bottom: 1px solid #c8e6c9;">'
                f'<td style="padding: 8px; font-weight: bold;">Prefix:</td>'
                f'<td style="padding: 8px;"><code style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px;">{escape(prefix)}</code></td></tr>'
                f'<tr style="border-bottom: 1px solid #c8e6c9;">'
                f'<td style="padding: 8px; font-weight: bold;">Base64 Veri:</td>'
                f'<td style="padding: 8px;">{actual_data_length:,} karakter</td></tr>'
                f'<tr><td style="padding: 8px; font-weight: bold;">Durum:</td>'
                f'<td style="padding: 8px;"><span style="color: green; font-weight: bold;">✓ TAM VERİ MEVCUT</span></td></tr>'
                f'</table>'
                f'<div style="margin-top: 10px; padding: 10px; background: #fff3cd; border-radius: 5px;">'
                f'<strong>ℹ️ Güvenlik:</strong> Tam base64 verisi güvenlik nedeniyle panelde gösterilmez.<br>'
                f'<strong>İndirmek için:</strong> Liste görünümünden "Base64\'ü Export Et" action\'ını kullanın.'
                f'</div></div>'
            )
        except Exception as e:
            error_msg = escape(str(e)[:100])
            logger.error(f"Base64 info hatası (ID: {obj.id}): {e}")
            return mark_safe(f'<span style="color: red;">❌ Bilgi hesaplanamadı: {error_msg}</span>')

    base64_info.short_description = '💾 Base64 Bilgisi'

    # === AYARLAR ÖZETİ ===
    def settings_summary_display(self, obj):
        """Ayarların özet görünümü (list için) (GÜVENLİ)"""
        try:
            return obj.settings_summary
        except Exception as e:
            logger.error(f"Settings summary hatası (ID: {obj.id}): {e}")
            return "N/A"

    settings_summary_display.short_description = '⚙️ Ayarlar'

    # === BOYUT GÖSTERİMİ ===
    def image_size_display(self, obj):
        """Görüntü boyutunu göster (GÜVENLİ)"""
        try:
            size_kb = obj.image_size_kb

            # None kontrolü
            if size_kb is None or size_kb == 0:
                return mark_safe('<span style="color: gray;">N/A</span>')

            if size_kb > 1024:
                size_str = f"{size_kb / 1024:.2f} MB"
                color = "red" if size_kb > 5120 else "orange"
            else:
                size_str = f"{size_kb:.2f} KB"
                color = "green"

            return mark_safe(f'<span style="color: {color}; font-weight: bold;">{size_str}</span>')
        except Exception as e:
            logger.error(f"Image size display hatası (ID: {obj.id}): {e}")
            return mark_safe('<span style="color: red;">Error</span>')

    image_size_display.short_description = '📦 Boyut'

    # === ACTIONS ===
    actions = [
        'delete_selected_photos',
        'verify_base64_integrity',
        'export_base64_to_json',
        'export_metadata_to_csv',
        'compare_base64_differences',
    ]

    def delete_selected_photos(self, request, queryset):
        """Seçili fotoğrafları sil"""
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"✓ {count} fotoğraf silindi.")

    delete_selected_photos.short_description = "🗑️ Seçili fotoğrafları sil"

    def verify_base64_integrity(self, request, queryset):
        """Base64 verilerinin bütünlüğünü kontrol et"""
        valid_count = 0
        invalid_count = 0
        total_size = 0

        for obj in queryset:
            try:
                if obj.base64_image and len(obj.base64_image) > 100:
                    if obj.base64_image.startswith('data:image') or \
                            obj.base64_image.startswith('/9j/') or \
                            obj.base64_image.startswith('iVBORw0KGgo'):
                        valid_count += 1
                        total_size += len(obj.base64_image)
                    else:
                        invalid_count += 1
                        logger.warning(f"ID {obj.id}: Geçersiz format")
                else:
                    invalid_count += 1
                    logger.warning(f"ID {obj.id}: Veri yok veya çok kısa")
            except Exception as e:
                logger.error(f"Integrity check hatası (ID: {obj.id}): {e}")
                invalid_count += 1

        avg_size_kb = (total_size / valid_count / 1024) if valid_count > 0 else 0

        self.message_user(
            request,
            f"✓ Geçerli: {valid_count} (Ort. {avg_size_kb:.1f} KB) | ✗ Geçersiz: {invalid_count}"
        )

    verify_base64_integrity.short_description = "✓ Base64 bütünlüğünü kontrol et"

    def export_base64_to_json(self, request, queryset):
        """
        GÜVENLİ: Seçili base64 verilerini JSON dosyasına export et
        Maksimum 5 fotoğraf (büyük dosya koruması)
        """
        if queryset.count() > 5:
            self.message_user(
                request,
                "⚠️ Güvenlik: En fazla 5 fotoğraf seçebilirsiniz",
                level='warning'
            )
            return

        export_data = []
        for obj in queryset:
            try:
                export_data.append({
                    'id': obj.id,
                    'timestamp': obj.timestamp.isoformat(),
                    'pan_angle': obj.pan_angle,
                    'distance_info': obj.distance_info,
                    'resolution': obj.resolution,
                    'framerate': obj.framerate,
                    'effect': obj.effect,
                    # Temel ayarlar
                    'ae_enable': obj.ae_enable,
                    'awb_enable': obj.awb_enable,
                    'awb_mode': obj.awb_mode,
                    'lens_correction': obj.lens_correction,
                    # Manuel kontroller
                    'exposure_time': obj.exposure_time,
                    'analogue_gain': obj.analogue_gain,
                    'brightness': obj.brightness,
                    'contrast': obj.contrast,
                    'saturation': obj.saturation,
                    'sharpness': obj.sharpness,
                    # Gelişmiş
                    'colour_effect': obj.colour_effect,
                    'ae_flicker_mode': obj.ae_flicker_mode,
                    'exposure_mode': obj.exposure_mode,
                    'metering_mode': obj.metering_mode,
                    # Base64 (BÜYÜK VERİ)
                    'base64_image': obj.base64_image,
                    'size_kb': obj.image_size_kb
                })
            except Exception as e:
                logger.error(f"Export hatası (ID: {obj.id}): {e}")

        response = HttpResponse(
            json.dumps(export_data, indent=2, ensure_ascii=False),
            content_type='application/json'
        )
        response[
            'Content-Disposition'] = f'attachment; filename="photos_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'

        self.message_user(request, f"✓ {len(export_data)} fotoğraf JSON olarak export edildi")
        return response

    export_base64_to_json.short_description = "📥 Base64'leri JSON olarak export et (max 5)"

    def export_metadata_to_csv(self, request, queryset):
        """
        Metadata'yı CSV olarak export et (Base64 HARİÇ)
        """
        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'ID', 'Timestamp', 'Resolution', 'FPS', 'Pan Angle', 'Distance',
            'Effect', 'AE Enable', 'AWB Enable', 'AWB Mode',
            'Exposure Time (µs)', 'ISO Gain', 'Brightness', 'Contrast',
            'Saturation', 'Sharpness', 'Colour Effect', 'Flicker Mode',
            'Size (KB)'
        ])

        # Data
        for obj in queryset:
            try:
                writer.writerow([
                    obj.id,
                    obj.timestamp.isoformat(),
                    obj.resolution or 'N/A',
                    f"{obj.framerate:.1f}" if obj.framerate else 'N/A',
                    f"{obj.pan_angle:.1f}",
                    obj.distance_info or 'N/A',
                    obj.effect,
                    'Yes' if obj.ae_enable else 'No',
                    'Yes' if obj.awb_enable else 'No',
                    obj.awb_mode,
                    obj.exposure_time or 'Auto',
                    f"{obj.analogue_gain:.2f}" if obj.analogue_gain else 'Auto',
                    f"{obj.brightness:.2f}" if obj.brightness is not None else 'N/A',
                    f"{obj.contrast:.2f}" if obj.contrast is not None else 'N/A',
                    f"{obj.saturation:.2f}" if obj.saturation is not None else 'N/A',
                    f"{obj.sharpness:.2f}" if obj.sharpness is not None else 'N/A',
                    obj.colour_effect or 'None',
                    obj.ae_flicker_mode or 'Off',
                    f"{obj.image_size_kb:.2f}" if obj.image_size_kb else 'N/A'
                ])
            except Exception as e:
                logger.error(f"CSV export hatası (ID: {obj.id}): {e}")

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="metadata_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        self.message_user(request, f"✓ {queryset.count()} fotoğraf metadata'sı CSV olarak export edildi")
        return response

    export_metadata_to_csv.short_description = "📊 Metadata'yı CSV olarak export et"

    # CameraCaptureAdmin sınıfına eklenecek yeni action ve metod

    def compare_base64_differences(self, request, queryset):
        """
        İki fotoğraf arasındaki base64 farklılıklarını TXT olarak indir
        v3.19 DEĞİŞİKLİK: Sadece tablo verisi, açıklama/başlık yok. Kısaltma yok.
        """
        # Tam olarak 2 fotoğraf seçilmiş mi kontrol et
        if queryset.count() != 2:
            self.message_user(
                request,
                "⚠️ Lütfen tam olarak 2 fotoğraf seçin. Şu an {} fotoğraf seçili.".format(queryset.count()),
                level='warning'
            )
            return

        # İki fotoğrafı al
        photos = list(queryset.order_by('id'))
        photo1 = photos[0]
        photo2 = photos[1]

        # Base64 verilerini kontrol et
        if not photo1.base64_image or not photo2.base64_image:
            self.message_user(
                request,
                "❌ Seçili fotoğraflardan en az birinde base64 verisi yok!",
                level='error'
            )
            return

        # Base64 verilerini al (data URI prefix'i temizle)
        base64_1 = photo1.base64_image
        base64_2 = photo2.base64_image

        # Eğer data URI formatındaysa, sadece base64 kısmını al
        if base64_1.startswith('data:image'):
            base64_1 = base64_1.split(',')[1] if ',' in base64_1 else base64_1
        if base64_2.startswith('data:image'):
            base64_2 = base64_2.split(',')[1] if ',' in base64_2 else base64_2

        # Farklılık analizi yap
        min_len = min(len(base64_1), len(base64_2))

        # Karakter karakter karşılaştırma
        diff_positions = []
        for i in range(min_len):
            if base64_1[i] != base64_2[i]:
                diff_positions.append({
                    'position': i,
                    'char1': base64_1[i],
                    'char2': base64_2[i]
                })

        # Rapor oluştur (SADECE FARKLILIK VERİSİ, AÇIKLAMA YOK)
        diff_report_lines = []

        # Farklılık detayları (TÜM FARKLAR, KISALTMA YOK, BAŞLIK YOK)
        if diff_positions:
            for diff in diff_positions:  # Kısaltma yok
                ascii1 = ord(diff['char1'])
                ascii2 = ord(diff['char2'])
                diff_report_lines.append(
                    f"{diff['position']:8} | {diff['char1']:^6} | {diff['char2']:^6} | {ascii1:^7} | {ascii2:^7}"
                )

        # Diğer tüm açıklamalar, uzunluk farkları ve "aynı" mesajları kaldırıldı.
        # Eğer fark yoksa, dosya boş olacaktır.

        # TXT dosyası olarak indir
        content = "\n".join(diff_report_lines)
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        filename = f"base64_raw_diff_{photo1.id}_vs_{photo2.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        # Kullanıcıya mesaj (Bu mesaj dosyaya yazılmaz, sadece arayüzde görünür)
        total_diffs = len(diff_positions)
        msg_level = 'success'
        msg = f"✔ Sadece farklılıkları içeren rapor oluşturuldu: {total_diffs:,} karakter farkı bulundu."

        if len(base64_1) != len(base64_2):
            msg += " (Ayrıca uzunluk farkı var, bu fark dosyaya yazılmadı.)"
            msg_level = 'warning'
        elif total_diffs == 0:
            msg = "✅ Karşılaştırıldı. İki fotoğraf arasında hiç fark bulunamadı."

        self.message_user(request, msg, level=msg_level)

        return response

    compare_base64_differences.short_description = "🔍 2 Fotoğrafın Sadece Farklarını İndir (Sade TXT)"


# ============================================================================
# SCAN ADMIN
# ============================================================================

@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'scan_type',
        'status',
        'start_time',
        'get_point_count',
        'calculated_area_cm2',
        'calculated_volume_cm3'
    ]
    list_filter = ['status', 'scan_type', 'start_time']
    search_fields = ['id', 'ai_commentary']
    readonly_fields = [
        'id', 'start_time', 'end_time', 'status', 'point_count',
        'h_scan_angle_setting', 'h_step_angle_setting',
        'v_scan_angle_setting', 'v_step_angle_setting',
        'steps_per_revolution_setting', 'calculated_area_cm2',
        'perimeter_cm', 'max_width_cm', 'max_depth_cm',
        'max_height_cm', 'calculated_volume_cm3'
    ]
    date_hierarchy = 'start_time'
    inlines = [ScanPointInline]

    fieldsets = (
        ('Genel Bilgiler', {
            'fields': ('id', 'scan_type', 'status', 'start_time', 'end_time', 'point_count')
        }),
        ('Tarama Ayarları (Read-Only)', {
            'fields': (
                'h_scan_angle_setting', 'h_step_angle_setting',
                'v_scan_angle_setting', 'v_step_angle_setting',
                'steps_per_revolution_setting'
            ),
            'classes': ('collapse',)
        }),
        ('Analiz Sonuçları (Read-Only)', {
            'fields': (
                'calculated_area_cm2', 'perimeter_cm',
                'max_width_cm', 'max_depth_cm',
                'max_height_cm', 'calculated_volume_cm3'
            )
        }),
        ('Yapay Zeka Analizi', {
            'fields': ('ai_commentary',),
            'classes': ('collapse',)
        })
    )

    actions = ['run_analysis_on_selected']

    @admin.display(description="Nokta Sayısı")
    def get_point_count(self, obj):
        """Nokta sayısını göster"""
        return obj.point_count

    def run_analysis_on_selected(self, request, queryset):
        """Seçili taramalar için analizi çalıştır"""
        count = 0
        for scan in queryset:
            scan.run_analysis_and_update()
            count += 1
        self.message_user(request, f"✓ {count} tarama analiz edildi.")

    run_analysis_on_selected.short_description = "🔬 Seçili taramaları analiz et"


# ============================================================================
# SCAN POINT ADMIN
# ============================================================================

@admin.register(ScanPoint)
class ScanPointAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'scan',
        'timestamp',
        'derece',
        'dikey_aci',
        'mesafe_cm',
        'h_sensor_distance',
        'v_sensor_distance'
    ]
    list_filter = ['scan', 'timestamp']
    search_fields = ['scan__id']
    readonly_fields = [
        'timestamp', 'derece', 'dikey_aci', 'mesafe_cm',
        'x_cm', 'y_cm', 'z_cm', 'hiz_cm_s'
    ]
    date_hierarchy = 'timestamp'

    fieldsets = (
        ('Bağlantı', {
            'fields': ('scan', 'timestamp')
        }),
        ('Motor Pozisyonu', {
            'fields': ('derece', 'dikey_aci')
        }),
        ('Mesafe Ölçümleri', {
            'fields': ('mesafe_cm', 'h_sensor_distance', 'v_sensor_distance')
        }),
        ('3D Koordinatlar', {
            'fields': ('x_cm', 'y_cm', 'z_cm', 'hiz_cm_s'),
            'classes': ('collapse',)
        })
    )


# ============================================================================
# SYSTEM LOG ADMIN
# ============================================================================

@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'timestamp', 'level', 'component', 'message_preview']
    list_filter = ['level', 'component', 'timestamp']
    search_fields = ['message', 'component']
    readonly_fields = ['timestamp']
    date_hierarchy = 'timestamp'

    def message_preview(self, obj):
        """Mesajın ilk 100 karakteri"""
        msg = obj.message
        if len(msg) > 100:
            return msg[:100] + "..."
        return msg

    message_preview.short_description = 'Mesaj'

    actions = ['delete_old_logs']

    def delete_old_logs(self, request, queryset):
        """30 günden eski logları sil"""
        from datetime import timedelta
        from django.utils import timezone

        cutoff_date = timezone.now() - timedelta(days=30)
        old_logs = SystemLog.objects.filter(timestamp__lt=cutoff_date)
        count = old_logs.count()
        old_logs.delete()

        self.message_user(request, f"✓ {count} eski log silindi.")

    delete_old_logs.short_description = "🗑️ 30+ gün önceki logları sil"


# ============================================================================
# AI MODEL CONFIGURATION ADMIN
# ============================================================================

class AIModelConfigurationForm(forms.ModelForm):
    api_key = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        help_text="API anahtarınızı buraya girin. Kaydedildikten sonra güvenlik için gizlenir."
    )

    class Meta:
        model = AIModelConfiguration
        fields = '__all__'


@admin.register(AIModelConfiguration)
class AIModelConfigurationAdmin(admin.ModelAdmin):
    form = AIModelConfigurationForm
    list_display = [
        'name',
        'model_provider',
        'model_name',
        'is_active_display',
        'created_at',
        'updated_at'
    ]
    list_filter = ['is_active', 'model_provider', 'created_at']
    search_fields = ['name', 'model_name', 'model_provider']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Model Bilgileri', {
            'fields': ('name', 'model_provider', 'model_name', 'is_active')
        }),
        ('API Yapılandırması', {
            'fields': ('api_key',),
            'classes': ('collapse',)
        }),
        ('Zaman Bilgileri', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    def is_active_display(self, obj):
        """Aktif durumu renkli göster"""
        if obj.is_active:
            return format_html('<span style="color: green; font-weight: bold;">✓ Aktif</span>')
        return format_html('<span style="color: gray;">✗ Pasif</span>')

    is_active_display.short_description = 'Durum'

    def save_model(self, request, obj, form, change):
        """Kaydederken sadece bir aktif model olmasını sağla"""
        if obj.is_active:
            AIModelConfiguration.objects.filter(is_active=True).exclude(pk=obj.pk).update(is_active=False)

        super().save_model(request, obj, form, change)

        if obj.is_active:
            self.message_user(request, f"'{obj.name}' aktif model olarak ayarlandı.")


# ============================================================================
# ADMIN PANEL ÖZELLEŞTİRMELERİ
# ============================================================================


admin.site.site_header = "Dream Pi v3.16 Ultimate"
admin.site.site_title = "Dream Pi Admin"
admin.site.index_title = "Raspberry Pi 5 Kontrol Paneli - Tam Manuel Kontrol"