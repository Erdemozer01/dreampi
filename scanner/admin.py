# scanner/admin.py

from django.contrib import admin
from scanner.models import Scan, ScanPoint, AIModelConfiguration, CameraCapture
from django import forms

class ScanPointInline(admin.TabularInline):
    model = ScanPoint
    extra = 0  # Yeni nokta ekleme alanı gösterme
    readonly_fields = ('derece', 'mesafe_cm', 'hiz_cm_s', 'timestamp', 'x_cm', 'y_cm') # Noktalar değiştirilemez olmalı
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    # Tarama listesinde gösterilecek alanlar
    list_display = ('id', 'start_time', 'status', 'get_point_count', 'calculated_area_cm2', 'calculated_volume_cm3')
    list_filter = ('status', 'start_time')
    search_fields = ('id', 'ai_commentary')
    date_hierarchy = 'start_time'

    # Detay sayfasında alanları gruplama ve salt okunur yapma
    # DÜZELTME: Alan adları models.py ile senkronize edildi ve yeni alanlar eklendi.
    fieldsets = (
        ('Genel Bilgiler', {
            'fields': ('id', 'start_time', 'end_time', 'status', 'point_count')
        }),
        ('Tarama Ayarları (Read-Only)', {
            'classes': ('collapse',),  # Gizlenebilir bölüm
            'fields': (
                'h_scan_angle_setting', 'h_step_angle_setting',
                'v_scan_angle_setting', 'v_step_angle_setting',
                'steps_per_revolution_setting'
            )
        }),
        ('Analiz Sonuçları (Read-Only)', {
            'fields': (
                'calculated_area_cm2', 'perimeter_cm',
                'max_width_cm', 'max_depth_cm',
                'max_height_cm', 'calculated_volume_cm3'
            )
        }),
        ('Yapay Zeka Analizi', {
            'fields': ('ai_commentary',)
        }),
    )

    # Bu alanlar admin panelinde sadece okunabilir olacak, değiştirilemez.
    readonly_fields = (
        'id', 'start_time', 'end_time', 'status', 'point_count',
        'h_scan_angle_setting', 'h_step_angle_setting',
        'v_scan_angle_setting', 'v_step_angle_setting',
        'steps_per_revolution_setting', 'calculated_area_cm2',
        'perimeter_cm', 'max_width_cm', 'max_depth_cm',
        'max_height_cm', 'calculated_volume_cm3'
    )

    # Tarama noktalarını aynı sayfada göstermek için inline ekle
    inlines = [ScanPointInline]

    @admin.display(description="Nokta Sayısı")
    def get_point_count(self, obj):
        # Listede her taramanın kaç noktası olduğunu gösteren özel bir alan
        # Veritabanı sorgusunu azaltmak için modeldeki hazır alanı kullanıyoruz
        return obj.point_count


@admin.register(ScanPoint)
class ScanPointAdmin(admin.ModelAdmin):
    """ScanPoint'leri ayrıca görüntülemek için (isteğe bağlı)."""
    list_display = ('scan', 'timestamp', 'derece', 'mesafe_cm')
    list_filter = ('scan',)
    search_fields = ('scan__id',)


@admin.register(CameraCapture)
class CameraCaptureAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'pan_angle', 'distance_info', 'effect')
    list_filter = ('effect', 'timestamp')
    search_fields = ('distance_info',)

    # Görüntü Base64 olduğu için düzenlemeyi engelle
    readonly_fields = ('timestamp', 'pan_angle', 'distance_info', 'effect', 'base64_image')

    fieldsets = (
        (None, {
            'fields': ('timestamp', 'pan_angle', 'distance_info', 'effect')
        }),
        ('Görüntü Verisi (Görüntülenemez)', {
            'fields': ('base64_image',),
            'classes': ('collapse',)  # Varsayılan olarak kapalı tut
        }),
    )

    # Yeni kayıt eklemeye izin verme (sadece script üzerinden)
    def has_add_permission(self, request):
        return False

class AIModelConfigurationForm(forms.ModelForm):
    api_key = forms.CharField(widget=forms.PasswordInput(render_value=True),
                              help_text="API anahtarınızı buraya girin. Kaydedildikten sonra güvenlik için gizlenir.")

    class Meta:
        model = AIModelConfiguration
        fields = '__all__'


@admin.register(AIModelConfiguration)
class AIModelConfigurationAdmin(admin.ModelAdmin):
    form = AIModelConfigurationForm
    list_display = ('name', 'model_name', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'model_name')
    list_editable = ('is_active',)