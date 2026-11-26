from django.urls import path
from . import views


urlpatterns = [
    path('cotizador/', views.vista_chat, name='vista_chat'),
    path('api/chat/', views.chatbot_mensaje, name='chatbot_mensaje'),
    path('cotizador/limpiar/', views.limpiar_cotizacion, name='limpiar_cotizacion'),
    path('cotizador/pdf/', views.exportar_cotizacion_pdf, name='exportar_cotizacion_pdf'),
    #path('cotizador/subir-odepa/', views.subir_excel_odepa, name='subir_excel_odepa'),
    path("boletin/", views.metricas_boletin, name="metricas"),
]