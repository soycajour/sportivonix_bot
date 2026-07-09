# =============================================================================
# CONFIGURACIÓN PLANTILLA DEL BOT — SPORTIVONIX (NO SUBIR CREDENCIALES A GIT)
# Copia este archivo como config.py y rellena con tus llaves reales.
# =============================================================================

# LLM Providers (API Keys vacías para seguridad)
LLM_PROVIDERS = [
    {
        "name": "Groq (Rápido y gratuito)",
        "type": "openai_compatible",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key": "TU_GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile"
    },
    {
        "name": "Cerebras 1 (Velocidad extrema)",
        "type": "openai_compatible",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "api_key": "TU_CEREBRAS_API_KEY",
        "model": "gemma-4-31b"
    },
    {
        "name": "OpenRouter 1 (Llama 3.3 70B)",
        "type": "openai_compatible",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": "TU_OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.3-70b-instruct:free"
    },
    {
        "name": "Gemini AI Studio 1",
        "type": "gemini",
        "api_key": "TU_GEMINI_API_KEY",
        "model": "gemini-2.5-flash"
    }
]

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_KEY = "TU_GEMINI_API_KEY"

# WordPress REST API
WP_URL = "https://tu-sitio.com"
WP_USER = "UsuarioAdmin"
WP_APP_PASSWORD = "TuPasswordDeAplicacion"

# Ciclo de publicación (en horas)
CICLO_HORAS = 1

# Nuevas categorías (IDs de WordPress)
CAT_NEWS = 2
CAT_FINANCE = 4
CAT_TRANSFERS = 11
CAT_GOSSIP = 12

# Artículos a publicar por sección por ciclo
ARTICULOS_NEWS = 3
ARTICULOS_TRANSFERS = 1
ARTICULOS_GOSSIP = 1

# Cooldown por jugador (días)
COOLDOWN_JUGADOR_DIAS = 3

# Telegram alertas
TELEGRAM_BOT_TOKEN = "TU_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TU_TELEGRAM_CHAT_ID"

# Longitud mínima y máxima del artículo (palabras)
MIN_PALABRAS = 600
MAX_PALABRAS = 900
MIN_PALABRAS_GOSSIP = 600
MAX_PALABRAS_GOSSIP = 800

# Archivo de registro de noticias publicadas
ARCHIVO_PUBLICADAS = "publicadas.json"

# Archivo de log
ARCHIVO_LOG = "bot_futbol.log"

# Directorio de imágenes temporales
DIR_IMAGENES = "imagenes_temp"

# Fuentes RSS de noticias de fútbol generales
RSS_FEEDS = [
    "https://www.espn.com/espn/rss/soccer/news",
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
]

# Fuentes RSS específicas de Transfers
FEEDS_TRANSFERS = [
    "https://www.skysports.com/rss/12661",
]

# Fuentes RSS específicas de Gossip
FEEDS_GOSSIP = [
    "https://feeds.bbci.co.uk/sport/football/gossip/rss.xml",
]

# Categoría de WordPress por defecto (News)
WP_CATEGORY_ID = 2

# Estado de los posts: "publish" para publicar directo, "draft" para borradores
WP_POST_STATUS = "publish"

# Pexels API Key
PEXELS_API_KEY = "TU_PEXELS_API_KEY"

# Pixabay API Key
PIXABAY_API_KEY = "TU_PIXABAY_API_KEY"

#solo para probar que todo salio bien el server