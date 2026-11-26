import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "clave-solo-para-pruebas-locales")
DEBUG = os.environ.get("DEBUG") == "1"

ALLOWED_HOSTS = [".vercel.app", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary_storage',
    'cloudinary',
    'tienda',
    'carrito',
    'pedidos',
    'chatbot_usuario',
    'django_browser_reload',
    'django.contrib.humanize',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if DEBUG:
    MIDDLEWARE += ['django_browser_reload.middleware.BrowserReloadMiddleware']

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'carrito.context_processors.carrito',
                'tienda.context_processors.categorias_navbar',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    "default": dj_database_url.config(conn_max_age=0)
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

AUTH_USER_MODEL = 'tienda.CustomUser'

ROLES = (
    ('cliente', 'Cliente'),
    ('admin', 'Administrador'),
)

SECURE_CONTENT_TYPE_NOSNIFF = True

EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'Florería <noreply@floreria.cl>'

TRANSBANK_AMBIENTE = 'TEST'
TRANSBANK_COMMERCE_CODE = "597055555532"
TRANSBANK_API_KEY = "579B532A7440BB0C9072DED5305E76fc2F62D8082F70757e490d181a1b8d810d"

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.environ["CLOUDINARY_CLOUD_NAME"],
    "API_KEY": os.environ["CLOUDINARY_API_KEY"],
    "API_SECRET": os.environ["CLOUDINARY_API_SECRET"],
}
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

STORAGES = {
    "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}