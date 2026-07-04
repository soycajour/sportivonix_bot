#!/usr/bin/env python3
# =============================================================================
# BOT AUTÓNOMO DE FÚTBOL — SPORTIVONIX
# Autor: Antigravity (trabajador autónomo 24/7)
# Descripción: Busca noticias, redacta artículos humanos y publica en WordPress
# =============================================================================

import os
import sys
import json
import time
import base64
import hashlib
import logging
import requests
import feedparser
import subprocess
import textwrap
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from duckduckgo_search import DDGS

# ─── Configuración ───────────────────────────────────────────────────────────
# Ajustar el path para importar config.py desde el mismo directorio
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from config import (
    WP_URL, WP_USER, WP_APP_PASSWORD,
    ARCHIVO_PUBLICADAS, ARCHIVO_LOG,
    DIR_IMAGENES, RSS_FEEDS, WP_CATEGORY_ID, WP_POST_STATUS,
    GEMINI_API_KEY as CONFIG_GEMINI_KEY,
    GEMINI_MODEL,
    CAT_NEWS, CAT_FINANCE, CAT_TRANSFERS, CAT_GOSSIP,
    ARTICULOS_NEWS, ARTICULOS_TRANSFERS, ARTICULOS_GOSSIP,
    COOLDOWN_JUGADOR_DIAS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    MIN_PALABRAS_GOSSIP, MAX_PALABRAS_GOSSIP,
    FEEDS_TRANSFERS, FEEDS_GOSSIP,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_PATH = SCRIPT_DIR / ARCHIVO_LOG
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("BotFutbol")

# ─── Registro de publicadas ───────────────────────────────────────────────────
PUBLICADAS_PATH = SCRIPT_DIR / ARCHIVO_PUBLICADAS
DIR_IMG_PATH = SCRIPT_DIR / DIR_IMAGENES
DIR_IMG_PATH.mkdir(exist_ok=True)

# ─── WordPress Auth ───────────────────────────────────────────────────────────
WP_AUTH = (WP_USER, WP_APP_PASSWORD)
WP_HEADERS = {"Content-Type": "application/json"}


# =============================================================================
# 1. REGISTRO DE NOTICIAS PUBLICADAS
# =============================================================================

def cargar_publicadas() -> dict:
    if PUBLICADAS_PATH.exists():
        with open(PUBLICADAS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"publicadas": [], "total_publicados": 0, "ultima_actualizacion": None}


def guardar_publicadas(data: dict):
    data["ultima_actualizacion"] = datetime.now(timezone.utc).isoformat()
    with open(PUBLICADAS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ya_fue_publicada(url: str, data: dict) -> bool:
    url_hash = hashlib.md5(url.encode()).hexdigest()
    return url_hash in data["publicadas"]


def marcar_como_publicada(url: str, data: dict):
    url_hash = hashlib.md5(url.encode()).hexdigest()
    data["publicadas"].append(url_hash)
    data["total_publicados"] = len(data["publicadas"])
    # Limitar el historial a los últimos 500 para no crecer indefinidamente
    if len(data["publicadas"]) > 500:
        data["publicadas"] = data["publicadas"][-500:]
    guardar_publicadas(data)


# =============================================================================
# 1.5. FUNCIONES DE INVESTIGACIÓN, COOLDOWNS Y ALERTAS
# =============================================================================

COOLDOWNS_PATH = SCRIPT_DIR / "cooldowns.json"

def buscar_web(query: str, num_results: int = 5) -> list:
    """Realiza una búsqueda web usando DuckDuckGo y devuelve una lista de resultados."""
    log.info(f"🔍 Buscando en la web: '{query}'")
    resultados = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                resultados.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", "")
                })
    except Exception as e:
        log.error(f"Error al buscar en la web: {e}")
    return resultados


def enviar_alerta_telegram(titulo: str, url: str, palabras: list) -> bool:
    """Envía una alerta de contenido sensible por Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    
    mensaje = (
        f"🚨 *ALERTA DE CONTENIDO SENSIBLE*\n\n"
        f"El bot ha publicado un artículo que contiene palabras de riesgo:\n\n"
        f"📌 *Título:* {titulo}\n"
        f"🔗 *Enlace:* {url}\n"
        f"⚠️ *Palabras detectadas:* {', '.join(palabras)}\n\n"
        f"Revisa el artículo. Si algo está mal, edítalo o bórralo."
    )
    
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(telegram_url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info("Alerta de Telegram enviada con éxito.")
            return True
        else:
            log.error(f"Error al enviar alerta de Telegram: {r.status_code} - {r.text}")
    except Exception as e:
        log.error(f"Excepción al enviar Telegram: {e}")
    return False


def fuente_tier(url: str) -> str:
    """Clasifica el origen de la noticia en 3 niveles de confianza: 🟢 CONFIRMED, 🟡 REPORTED, 🔴 RUMOR."""
    domain = urlparse(url).netloc.lower()
    
    # Fuentes confirmadas / oficiales
    if any(d in domain for d in [
        ".fc.com", "realmadrid.com", "barcelona.fc", "arsenal.com", "chelseafc.com",
        "manutd.com", "mancity.com", "liverpoolfc.com", "bbc.co.uk/sport", "bbc.com/sport",
        "reuters.com", "apnews.com"
    ]):
        return "🟢 CONFIRMED"
        
    # Medios deportivos reputados
    if any(d in domain for d in [
        "espn.com", "skysports.com", "marca.com", "as.com", "goal.com",
        "lequipe.fr", "gazzetta.it", "football-italia.net", "theathletic.com"
    ]):
        return "🟡 REPORTED"
        
    # Tabloides y foros (por defecto para el resto)
    return "🔴 RUMOR"


def cargar_cooldowns() -> dict:
    """Carga los cooldowns de jugadores desde el archivo json."""
    if COOLDOWNS_PATH.exists():
        try:
            with open(COOLDOWNS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def guardar_cooldowns(data: dict):
    """Guarda los cooldowns de jugadores al archivo json."""
    try:
        with open(COOLDOWNS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Error al guardar cooldowns: {e}")


def verificar_cooldown(jugador: str, seccion: str) -> bool:
    """Devuelve True si el jugador está en cooldown para esa sección (menor a 3 días)."""
    cooldowns = cargar_cooldowns()
    player_data = cooldowns.get(jugador, {})
    last_pub_str = player_data.get(seccion)
    if not last_pub_str:
        return False
        
    try:
        last_pub = datetime.fromisoformat(last_pub_str)
        delta = datetime.now(timezone.utc) - last_pub
        if delta.days < COOLDOWN_JUGADOR_DIAS:
            return True
    except Exception:
        pass
    return False


def registrar_cooldown(jugador: str, seccion: str):
    """Registra la fecha actual como última publicación de ese jugador en esa sección."""
    cooldowns = cargar_cooldowns()
    if jugador not in cooldowns:
        cooldowns[jugador] = {}
    cooldowns[jugador][seccion] = datetime.now(timezone.utc).isoformat()
    guardar_cooldowns(cooldowns)


def extraer_entidades(titulo: str, resumen: str) -> tuple:
    """Usa el LLM principal para extraer el nombre del jugador y equipo mencionados."""
    prompt = f"""Extract the main professional football player name and their associated club/national team mentioned in this news.
Return a clean JSON object with keys "player" and "team". If no player or team is found, return empty strings. Do NOT output markdown, backticks, or any extra text. ONLY raw JSON.

Headline: {titulo}
Summary: {resumen}
"""
    try:
        from config import LLM_PROVIDERS
        provider = LLM_PROVIDERS[0]
        ptype = provider.get("type", "")
        api_key = provider.get("api_key", "")
        model = provider.get("model", "")
        url = provider.get("url", "")
        
        if ptype == "openai_compatible":
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r'```json\s*', '', raw)
            raw = re.sub(r'\s*```', '', raw)
            data = json.loads(raw)
            return data.get("player", "").strip(), data.get("team", "").strip()
    except Exception as e:
        log.warning(f"Error al extraer entidades con IA: {e}")
    return "", ""


def obtener_o_crear_tag(name: str) -> int:
    """Busca un tag por nombre en WordPress; si no existe, lo crea y devuelve su ID."""
    if not name:
        return None
    name_clean = name.strip()
    try:
        search_url = f"{WP_URL}/wp-json/wp/v2/tags?search={requests.utils.quote(name_clean)}"
        r = requests.get(search_url, auth=WP_AUTH)
        if r.status_code == 200:
            results = r.json()
            for tag in results:
                if tag["name"].lower() == name_clean.lower():
                    return tag["id"]
        
        create_url = f"{WP_URL}/wp-json/wp/v2/tags"
        payload = {"name": name_clean}
        rc = requests.post(create_url, auth=WP_AUTH, json=payload, headers=WP_HEADERS)
        if rc.status_code == 201:
            return rc.json()["id"]
    except Exception as e:
        log.error(f"Error al obtener/crear tag '{name_clean}': {e}")
    return None


# =============================================================================
# 2. OBTENCIÓN DE NOTICIAS (RSS)
# =============================================================================

def obtener_noticias_rss(feeds_a_leer: list = None) -> list:
    """Lee múltiples feeds RSS y devuelve lista de entradas únicas de fútbol."""
    noticias = []
    palabras_clave_futbol = [
        "fútbol", "futbol", "football", "soccer", "gol", "goal", "liga",
        "champions", "premier", "laliga", "bundesliga", "serie a", "ligue 1",
        "uefa", "fifa", "mundial", "copa", "fichaje", "transfer", "real madrid",
        "barcelona", "manchester", "liverpool", "chelsea", "juventus", "psg",
        "atletico", "sevilla", "arsenal", "city", "united", "inter", "milan",
        "bayern", "dortmund", "seleccion", "mbappe", "messi", "ronaldo",
        "haaland", "vinicius", "bellingham", "neymar", "lewandowski"
    ]

    target_feeds = feeds_a_leer if feeds_a_leer is not None else RSS_FEEDS
    for feed_url in target_feeds:
        try:
            log.info(f"Leyendo feed: {feed_url}")
            feed = feedparser.parse(feed_url, request_headers={
                "User-Agent": "Mozilla/5.0 (compatible; SportivoNixBot/1.0)"
            })
            for entry in feed.entries[:10]:  # Máximo 10 por feed
                titulo = entry.get("title", "").lower()
                resumen = entry.get("summary", entry.get("description", "")).lower()
                texto_completo = titulo + " " + resumen
                # Filtrar solo noticias de fútbol
                if any(kw in texto_completo for kw in palabras_clave_futbol):
                    noticias.append({
                        "titulo": entry.get("title", ""),
                        "url": entry.get("link", entry.get("id", "")),
                        "resumen": entry.get("summary", entry.get("description", "")),
                        "publicado": entry.get("published", ""),
                        "fuente": urlparse(feed_url).netloc,
                    })
        except Exception as e:
            log.warning(f"Error leyendo feed {feed_url}: {e}")

    # Eliminar duplicados por URL
    vistos = set()
    unicas = []
    for n in noticias:
        if n["url"] and n["url"] not in vistos:
            vistos.add(n["url"])
            unicas.append(n)

    log.info(f"Total noticias de fútbol encontradas: {len(unicas)}")
    return unicas


def elegir_noticia_nueva(noticias: list, publicadas: dict):
    """Devuelve la primera noticia que no haya sido publicada aún."""
    for noticia in noticias:
        if noticia["url"] and not ya_fue_publicada(noticia["url"], publicadas):
            return noticia
    return None


# =============================================================================
# 3. REDACCIÓN DEL ARTÍCULO (Anti-IA, tono periodístico humano)
# =============================================================================

def limpiar_html(texto: str) -> str:
    """Elimina etiquetas HTML básicas del texto."""
    return re.sub(r"<[^>]+>", "", texto).strip()


# ─── BANNED AI WORDS & PHRASES ────────────────────────────────────────────────
# From the avoid-ai-writing skill: 43-entry replacement table + 21 pattern categories
BANNED_WORDS_PROMPT = """
BANNED WORDS AND PHRASES — Using ANY of these is an automatic failure:
- Moreover, Furthermore, Additionally, Notably, Importantly, Significantly
- In today's landscape, In the fast-paced world, In the ever-evolving
- Pivotal, Crucial, Key (as adjective for people/moments), Vital, Essential
- Seamless, Seamlessly, Robust, Cutting-edge, State-of-the-art
- Leverage, Unlock, Empower, Streamline, Utilize, Harness, Foster
- Embark, Delve, Dive into, Navigate (metaphorical), Underscore
- Testament to, Serves as a, A testament to, Speaks volumes
- It's worth noting, It's important to note, It goes without saying
- At the end of the day, Without further ado, That being said
- In conclusion, In summary, To sum up, All in all, As we can seeo hag
- Only time will tell, Remains to be seen, The stage is set
- Best-in-class, Industry-leading, World-class (for non-specific praise)
- We're excited/thrilled to announce, We can't wait to see
- In this article we will explore, Let's take a look at, Let's dive in
- Landscape, Realm, Arena (metaphorical), Tapestry, Paradigm shift
- Spearhead, Bolster, Catapult, Propel, Galvanize

BANNED STRUCTURAL PATTERNS:
- Do NOT use the "Rule of Three" pattern (listing exactly 3 adjectives/items repeatedly)
- Do NOT start consecutive paragraphs the same way
- Do NOT use em dashes (—) more than once per article
- Do NOT bold random words for emphasis; use <strong> only for names or stats
- Do NOT cycle through synonyms artificially (e.g., "the club/the team/the outfit/the side" in sequence)
- Do NOT hedge with "perhaps", "might", "could potentially", "arguably" more than once total
- Do NOT use hollow intensifiers: "incredibly", "extremely", "absolutely", "truly", "really"
"""


def construir_prompt(titulo: str, resumen: str, fuente: str, seccion: str = "news", datos_investigacion: str = "", tier: str = "") -> str:
    resumen_limpio = limpiar_html(resumen)[:800]
    
    # Cargar longitud según sección
    try:
        from config import MIN_PALABRAS_GOSSIP, MAX_PALABRAS_GOSSIP, MIN_PALABRAS, MAX_PALABRAS
    except ImportError:
        MIN_PALABRAS_GOSSIP, MAX_PALABRAS_GOSSIP = 600, 800
        MIN_PALABRAS, MAX_PALABRAS = 600, 900
        
    min_w = MIN_PALABRAS_GOSSIP if seccion == "gossip" else MIN_PALABRAS
    max_w = MAX_PALABRAS_GOSSIP if seccion == "gossip" else MAX_PALABRAS
    
    # 1. Definición del rol del periodista según sección
    if seccion == "gossip":
        persona = """You are a sassy, sharp, and highly opinionated football lifestyle and gossip columnist. You write the "Football Gossip" column for Sportivonix. You speak to the reader like you are sharing juicy secrets and banter with a close mate at a local pub — informal, witty, free-spirited, and engaging."""
    elif seccion == "transfers":
        persona = """You are an experienced football financial analyst and transfer specialist. You write the "Transfers & Finance" column for Sportivonix. You know player values, salaries, and contract details inside out. You speak in a highly informed, analytical yet conversational tone — opinionated, direct, and focused on whether a deal makes financial and sport sense."""
    else:
        persona = """You are a veteran football journalist who has covered the sport for 20 years across England, Spain, and Italy. You write a column for Sportivonix. You have strong opinions, you know the game inside out, and you write the way you talk after a match at the pub with fellow journalists — direct, colorful, and full of real insight."""

    # 2. Instrucciones de fuentes y atribución (Tiers)
    instrucciones_tier = ""
    if seccion in ["transfers", "gossip"] and tier:
        if "CONFIRMED" in tier:
            instrucciones_tier = f"SOURCE CONFIDENCE TIER: 🟢 CONFIRMED. This fact has been officially confirmed by clubs, players, or highly reputable agencies. You must state it directly as a fact. E.g. 'Arsenal have officially signed...'"
        elif "REPORTED" in tier:
            instrucciones_tier = f"SOURCE CONFIDENCE TIER: 🟡 REPORTED. This comes from reputable sports news outlets. You must attribute the facts to the reporting outlets. E.g., 'As reported by ESPN...', 'According to Sky Sports...'"
        else: # RUMOR
            instrucciones_tier = f"SOURCE CONFIDENCE TIER: 🔴 RUMOR. This comes from tabloid journals or unverified social media chatter. You MUST treat this strictly as unconfirmed. E.g., 'Unconfirmed reports suggest...', 'Rumours are circulating that...'. Do NOT state it as a fact under any circumstances."

    # 3. Datos de investigación si están disponibles
    bloque_investigacion = ""
    if datos_investigacion:
        bloque_investigacion = f"""
ADDITIONAL WEB RESEARCH RESULTS (integrate these facts into your column to add depth):
{datos_investigacion}
"""

    # 4. Reglas específicas por sección
    if seccion == "gossip":
        reglas_especificas = f"""
WRITING RULES:
1. LANGUAGE: Write entirely in English. Translate any Spanish/other language source material.
2. LENGTH: {min_w}-{max_w} words.
3. OPENING: Start with a striking, dramatic, or scandalous hook about the player's life or choices. E.g. 'Neymar has once again proven that money cannot buy discretion.'
4. STYLE: Free-style, opinionated, and gossipy. Discuss salaries, purchases, relationships, or fan sentiment, but always include the official response/denial if present in the research.
5. NO FIRST PERSON: Absolutely no first-person pronouns ("I", "we", "my", "our", "in my opinion", "having watched"). Write in analytical, objective third person.
6. TEMPORAL CONSISTENCY: All dates must align with the current year (2026). E.g. treat the 2026 World Cup as the upcoming or current major tournament. Avoid past references like 2024.
7. SOURCE HANDLING: {instrucciones_tier}
8. CROSS-LINKING: Near the end, include exactly one paragraph referring to the player's professional performance, linking to their tag (e.g. '<p><em>Curious about his actual performance on the pitch? Check out our <a href="/tag/[player-name-slug]/">Transfers analysis</a>.</em></p>' substituting [player-name-slug] with the actual lowercased hyphenated player name).
"""
    elif seccion == "transfers":
        reglas_especificas = f"""
WRITING RULES:
1. LANGUAGE: Write entirely in English.
2. LENGTH: {min_w}-{max_w} words.
3. OPENING: Start with the most dramatic financial figure or contract length. E.g. 'Eintracht Frankfurt have pulled off one of the cleanest robbery jobs in Bundesliga history.'
4. STYLE: Conversational but heavily analytical on finances. Discuss player values, wages, and whether the club overpaid.
5. NO FIRST PERSON: Absolutely no first-person pronouns ("I", "we", "my", "our", "in my opinion"). Write in analytical, objective third person.
6. TEMPORAL CONSISTENCY: All dates must align with the current year (2026).
7. SOURCE HANDLING: {instrucciones_tier}
8. CROSS-LINKING: Near the end, include exactly one paragraph referring to their life off the pitch, linking to their tag (e.g. '<p><em>Want to know more about his life off the pitch? Read our <a href="/tag/[player-name-slug]/">Football Gossip section</a>.</em></p>' substituting [player-name-slug] with the actual lowercased hyphenated player name).
"""
    else:
        reglas_especificas = f"""
WRITING RULES:
1. LANGUAGE: Write entirely in English.
2. LENGTH: {min_w}-{max_w} words.
3. OPENING: Start with the single most dramatic fact, stat, or consequence. Drop the reader into the middle of the action.
4. STYLE: Standard columns, news, and controversy.
5. NO FIRST PERSON: Absolutely no first-person pronouns ("I", "we", "my", "our", "in my opinion"). Write in analytical, objective third person.
6. TEMPORAL CONSISTENCY: All dates must align with the current year (2026).
"""

    # 5. Categorías a sugerir
    if seccion == "gossip":
        cat_instrucciones = "Always include category 12 (Football Gossip) only."
    elif seccion == "transfers":
        cat_instrucciones = "Always include categories 11 (Transfers) and 4 (Finance) together."
    else:
        cat_instrucciones = "Always include category 2 (News). Add 4 (Finance) if the story involves money/transfers. Add 5 (Controversy) if there is genuine dispute."

    return f"""{persona}

You are NOT an AI. You are NOT a content writer. You are a journalist.

{BANNED_WORDS_PROMPT}

SOURCE MATERIAL:
Headline: {titulo}
Summary: {resumen_limpio}
Source: {fuente}
{bloque_investigacion}

{reglas_especificas}

SUBTITLES: Use <h2> tags. Make them punchy and specific to THIS story. Good: "Forty-Two Million for Six Starts" or "The Midfield Problem Nobody Wants to Admit". Bad: "Analysis", "The Context", "Looking Ahead", "What This Means".
FORMATTING: Raw HTML only. <p> for paragraphs, <h2> for subtitles, <strong> sparingly for key names or numbers. No markdown.
Do NOT include the main title in the body.
CATEGORIES: {cat_instrucciones}

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:
[TITLE]
A specific, opinionated title that a fan would click on (NOT a generic announcement)

[BODY]
<p>Opening paragraph — drop the reader into the story with the most striking fact...</p>
<p>Second paragraph — immediate context, what happened and who is involved...</p>
<h2>A Punchy Subtitle About This Specific Story</h2>
<p>Deeper analysis with real names and numbers...</p>
<p>Your opinion backed by evidence...</p>
<h2>Another Specific Subtitle</h2>
<p>What happens next — concrete consequences, upcoming fixtures, transfer deadlines...</p>
<p>Strong closing line with a fact, not a platitude.</p>

[CATEGORIES]
3, 5

[SEARCH_QUERY]
Provide a simple 2-3 word search query in English representing the main subject of this story (e.g., "Jules Kounde", "Real Madrid", "Harry Kane", "Champions League").
"""


def limpiar_texto_ia(texto_html: str, titulo: str, resumen: str, fuente: str) -> str:
    """Segunda pasada: envía el artículo generado al LLM para eliminar AI-isms supervivientes."""
    prompt_limpieza = f"""You are a grumpy copy editor at a sports newspaper. Your only job is to clean up this draft.

RULES:
- NO FIRST PERSON: Absolutely no first-person pronouns ("I", "we", "my", "our", "in my opinion", "having watched"). Rewrite those parts into objective third-person analysis.
- TEMPORAL CONSISTENCY: Ensure all dates make sense relative to the current year (2026).
- Remove any phrase that sounds robotic, generic, or AI-generated
- Replace vague praise ("incredible", "remarkable", "stellar") with specific descriptions of what happened
- Cut any sentence that adds no information (filler)
- Fix any synonym cycling (don't call the same team 5 different names in 5 paragraphs)
- Keep ALL facts, names, numbers, and HTML tags exactly as they are
- Keep the same structure and paragraph count
- Do NOT add new information or opinions
- Do NOT change <h2>, <p>, or <strong> tags
- Output ONLY the cleaned HTML. No explanations, no commentary.

DRAFT TO CLEAN:
{texto_html}"""

    try:
        from config import LLM_PROVIDERS
    except ImportError:
        return texto_html

    for provider in LLM_PROVIDERS:
        name = provider.get("name", "Unknown")
        ptype = provider.get("type", "")
        api_key = provider.get("api_key", "")
        model = provider.get("model", "")
        url = provider.get("url", "")

        try:
            log.info(f"🧹 Limpieza anti-IA con {name}...")

            if ptype == "gemini":
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt_limpieza}]}],
                    "generationConfig": {"temperature": 0.3, "topP": 0.9, "maxOutputTokens": 1500}
                }
                resp = requests.post(gemini_url, json=payload, timeout=60)
                if resp.status_code == 429:
                    continue
                resp.raise_for_status()
                cleaned = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

            elif ptype == "openai_compatible":
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                if "openrouter" in url:
                    headers["HTTP-Referer"] = "https://sportivonix.com"
                    headers["X-Title"] = "Bot Futbol"
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt_limpieza}],
                    "temperature": 0.3,
                }
                resp = requests.post(url, json=payload, headers=headers, timeout=60)
                if resp.status_code == 429:
                    continue
                resp.raise_for_status()
                cleaned = resp.json()["choices"][0]["message"]["content"].strip()
            else:
                continue

            # Limpiar posibles envolturas markdown
            cleaned = re.sub(r"^```(?:html|markdown|text)?\n?", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\n?```$", "", cleaned)

            # Validación básica: el texto limpio debe tener al menos 60% del largo original
            if len(cleaned) > len(texto_html) * 0.6 and "<p>" in cleaned:
                log.info(f"✅ Limpieza anti-IA completada con {name}")
                return cleaned
            else:
                log.warning(f"Limpieza devolvió texto demasiado corto o sin HTML. Usando original.")
                return texto_html

        except Exception as e:
            log.warning(f"Error en limpieza con {name}: {e}")
            continue

    log.warning("No se pudo ejecutar la limpieza anti-IA. Usando texto original.")
    return texto_html


def redactar_articulo(titulo: str, resumen: str, fuente: str, seccion: str = "news", datos_investigacion: str = "", tier: str = "") -> tuple[str, str, list[int], str]:
    """Prueba múltiples proveedores LLM (Groq, Cerebras, OpenRouter, Gemini) hasta que uno funcione."""
    prompt = construir_prompt(titulo, resumen, fuente, seccion, datos_investigacion, tier)
    
    try:
        from config import LLM_PROVIDERS
    except ImportError:
        LLM_PROVIDERS = []
        
    ultimo_error = None
    
    for provider in LLM_PROVIDERS:
        name = provider.get("name", "Unknown")
        ptype = provider.get("type", "")
        api_key = provider.get("api_key", "")
        model = provider.get("model", "")
        url = provider.get("url", "")
        
        for intento in range(2): # 2 intentos por proveedor
            try:
                log.info(f"Intentando redactar con {name} (Intento {intento + 1}/2)...")
                
                if ptype == "gemini":
                    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.85, "topP": 0.95, "maxOutputTokens": 1500}
                    }
                    resp = requests.post(gemini_url, json=payload, timeout=60)
                    
                    if resp.status_code == 429:
                        log.warning(f"⚠️ Límite 429 alcanzado en {name}. Pasando al siguiente proveedor.")
                        ultimo_error = ValueError("429 Too Many Requests")
                        break
                        
                    resp.raise_for_status()
                    raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    
                elif ptype == "openai_compatible":
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    if "openrouter" in url:
                        headers["HTTP-Referer"] = "https://sportivonix.com"
                        headers["X-Title"] = "Bot Futbol"
                        
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.85,
                    }
                    
                    resp = requests.post(url, json=payload, headers=headers, timeout=60)
                    if resp.status_code == 429:
                        log.warning(f"⚠️ Límite 429 alcanzado en {name}. Pasando al siguiente proveedor.")
                        ultimo_error = ValueError("429 Too Many Requests")
                        break
                        
                    resp.raise_for_status()
                    raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                else:
                    break # Tipo no soportado
                    
                # Parsear respuesta usando las etiquetas [TITLE], [BODY], [CATEGORIES] y [SEARCH_QUERY]
                if "[BODY]" in raw_text:
                    parts = raw_text.split("[BODY]")
                    title_part = parts[0].replace("[TITLE]", "").strip()
                    # Limpiar etiquetas HTML del título (como <h1>) y comillas
                    title_part = re.sub(r'<[^>]+>', '', title_part)
                    title_part = title_part.strip('\'" ')
                    body_part = parts[1].strip()
                    
                    # Extraer SEARCH_QUERY
                    search_query = "football match"
                    match_sq = re.search(r'\**\[SEARCH_QUERY\]\**:?.*', body_part, re.IGNORECASE | re.DOTALL)
                    if match_sq:
                        sq_str = match_sq.group(0)
                        body_part = body_part[:match_sq.start()].strip()
                        sq_lines = [l.strip() for l in sq_str.replace("[SEARCH_QUERY]", "").replace(":", "").split("\n") if l.strip()]
                        if sq_lines:
                            search_query = sq_lines[0].replace("*", "").strip()

                    # Extraer CATEGORIES
                    categorias_list = [3] # Siempre 3 (Noticias) por defecto
                    match_cat = re.search(r'\**\[CATEGOR(?:Y|IES)\]\**:?.*', body_part, re.IGNORECASE | re.DOTALL)
                    if match_cat:
                        cat_str = match_cat.group(0)
                        body_part = body_part[:match_cat.start()].strip()
                        nums = re.findall(r'\d+', cat_str)
                        if nums:
                            categorias_list = list(set([3] + [int(n) for n in nums if int(n) in [3, 4, 5, 6]]))

                    # Limpiar las posibles etiquetas markdown (```html o ```)
                    body_part = re.sub(r"^```(?:html|markdown|text)?\n?", "", body_part, flags=re.IGNORECASE)
                    body_part = re.sub(r"\n?```$", "", body_part)
                    log.info(f"✅ Artículo redactado exitosamente con {name}: {len(body_part.split())} palabras aprox. Categorías: {categorias_list}. Query imagen: {search_query}")
                    # Segunda pasada: limpiar AI-isms
                    body_part = limpiar_texto_ia(body_part, titulo, resumen, fuente)
                    return title_part, body_part, categorias_list, search_query
                else:
                    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                    if len(lines) > 1:
                        return lines[0], "\n".join(lines[1:]), [3], "football match"
                    raise ValueError("Respuesta mal formateada sin [TITLE] y [BODY]")
                    
            except Exception as e:
                ultimo_error = e
                if "429" in str(e):
                    log.warning(f"⚠️ Límite 429 alcanzado en {name}.")
                    break
                if intento < 1:
                    log.warning(f"Error con {name}: {e}. Reintentando...")
                    time.sleep(5)
                    
    # Respaldo final absoluto si todas las APIs fallan
    log.error("❌ Todas las APIs fallaron. Usando texto básico de respaldo.")
    resumen_limpio = limpiar_html(resumen)
    fallback_content = f"<h2>Breaking News</h2><p>{resumen_limpio}</p><p>This breaking news is being covered extensively by Sportivonix. We will update as more information becomes available. Original source: <strong>{fuente}</strong>.</p>"
    return titulo, fallback_content, [3], "football match"


# =============================================================================
# 4. GENERACIÓN DE IMAGEN (via generate_image de Antigravity)
# =============================================================================

def describir_imagen_para_prompt(titulo: str) -> str:
    """Genera un prompt fotorrealista para la imagen de portada."""
    titulo_lower = titulo.lower()
    # Detectar equipos o competiciones para personalizar el prompt
    equipos_colores = {
        "real madrid": "white and gold jersey, Santiago Bernabéu stadium",
        "barcelona": "blaugrana jersey, Camp Nou stadium",
        "manchester city": "sky blue jersey, Etihad Stadium",
        "manchester united": "red jersey, Old Trafford",
        "liverpool": "red jersey, Anfield",
        "chelsea": "blue jersey, Stamford Bridge",
        "arsenal": "red and white jersey, Emirates Stadium",
        "juventus": "black and white jersey, Allianz Stadium",
        "psg": "blue jersey, Parc des Princes",
        "bayern": "red jersey, Allianz Arena",
        "atletico": "red and white stripes, Metropolitano",
        "champions": "Champions League trophy, blue and white lights",
        "mundial": "World Cup trophy, colorful flags",
    }
    contexto_visual = "professional football match atmosphere, dramatic stadium lights"
    for equipo, desc in equipos_colores.items():
        if equipo in titulo_lower:
            contexto_visual = desc
            break

    return (
        f"Photorealistic sports photography, football scene: {contexto_visual}. "
        f"Action shot of a footballer in motion, blurred crowd in background, "
        f"cinematic lighting, high contrast, 4K quality, dramatic atmosphere, "
        f"no text, no logos, editorial style photography"
    )


def buscar_imagen_wikimedia(search_query: str) -> tuple[str, str] | None:
    """Busca una imagen libre de derechos en Wikimedia Commons usando la consulta especificada."""
    # Eliminar acentos y caracteres especiales de la consulta
    import unicodedata
    search_query = unicodedata.normalize('NFKD', search_query).encode('ASCII', 'ignore').decode('ASCII')
    
    # Filtrar búsquedas genéricas
    excluir = {"the", "a", "an", "breaking", "news", "exclusive", "football", "soccer", "match"}
    words = [w for w in search_query.split() if w.lower() not in excluir]
    
    if not words:
        search_query = "football match"
    else:
        search_query = " ".join(words)

    log.info(f"Buscando en Wikimedia Commons para: '{search_query}'")
    
    import random
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {search_query}",
        "gsrnamespace": "6",
        "gsrlimit": "8",
        "iiprop": "url|extmetadata",
        "iiextmetadatafilter": "Artist|LicenseShortName"
    }
    headers = {
        "User-Agent": "SportivoNixBot/1.0 (sportivonix@gmail.com) Python-requests"
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            pages = data.get("query", {}).get("pages", {})
            valid_images = []
            for page_id, page in pages.items():
                imageinfo = page.get("imageinfo", [])
                if imageinfo:
                    info = imageinfo[0]
                    img_url = info.get("url")
                    extmetadata = info.get("extmetadata", {})
                    
                    artist_raw = extmetadata.get("Artist", {}).get("value", "Unknown Photographer")
                    artist = limpiar_html(artist_raw)
                    license_name = extmetadata.get("LicenseShortName", {}).get("value", "CC BY-SA")
                    
                    if img_url and img_url.lower().endswith(('.jpg', '.jpeg', '.png')):
                        valid_images.append({
                            "url": img_url,
                            "credit": f"Image: {artist} ({license_name}) via Wikimedia Commons"
                        })
            
            if valid_images:
                selected = random.choice(valid_images)
                img_path = DIR_IMG_PATH / f"wikimedia_{int(time.time())}_{random.randint(100, 999)}.jpg"
                log.info(f"Descargando imagen de Wikimedia: {selected['url']}")
                img_data = requests.get(selected["url"], headers=headers, timeout=30).content
                with open(img_path, 'wb') as f:
                    f.write(img_data)
                return str(img_path), selected["credit"]
    except Exception as e:
        log.warning(f"Error en búsqueda de Wikimedia: {e}")
        
    return None


def generar_imagen_portada(titulo: str, search_query: str = "football match", equipo_asociado: str = "") -> tuple[str, str | None] | None:
    """
    Intenta buscar una imagen real en Wikimedia Commons con atribución usando el search_query optimizado.
    Si falla, busca una imagen fotorrealista de stock usando Pexels/Pixabay.
    """
    import random

    # 1. Resolver el query usando el mapeo de clubes
    query_final = search_query.strip().lower()
    
    MAPEO_IMAGENES_CLUBES = {
        "real madrid": ["santiago bernabeu", "madrid stadium", "white soccer jersey"],
        "barcelona": ["camp nou", "fc barcelona", "blue and red soccer"],
        "manchester united": ["old trafford", "red soccer jersey"],
        "manchester city": ["etihad stadium", "sky blue soccer"],
        "chelsea": ["stamford bridge", "blue soccer jersey"],
        "arsenal": ["emirates stadium", "red white soccer jersey"],
        "liverpool": ["anfield", "red soccer jersey"],
        "psg": ["parc des princes", "paris soccer"],
        "bayern munich": ["allianz arena", "red soccer jersey"],
        "juventus": ["juventus stadium", "black and white soccer jersey"],
        "inter milan": ["san siro", "blue and black soccer jersey"],
        "ac milan": ["san siro", "red and black soccer jersey"],
        "real sociedad": ["anoeta stadium", "blue and white soccer jersey"],
        "seleccion espanola": ["spain football", "red soccer jersey"],
        "argentina": ["argentina football", "blue and white soccer jersey"],
    }
    
    # Intentar coincidencia por el equipo detectado por la IA
    coincidencia_equipo = None
    if equipo_asociado:
        eq_clean = equipo_asociado.strip().lower()
        for k, v in MAPEO_IMAGENES_CLUBES.items():
            if k in eq_clean or eq_clean in k:
                coincidencia_equipo = random.choice(v)
                break
                
    # Si no hay, intentar por palabras clave en el título
    if not coincidencia_equipo:
        titulo_l = titulo.lower()
        for k, v in MAPEO_IMAGENES_CLUBES.items():
            if k in titulo_l:
                coincidencia_equipo = random.choice(v)
                break
                
    if coincidencia_equipo:
        query_final = coincidencia_equipo
        log.info(f"📍 Mapeo de imagen activado. Query final: '{query_final}'")
    else:
        # Fallbacks genéricos si no es un equipo conocido o el query es muy abstracto
        if "champions" in titulo.lower():
            query_final = "champions league stadium"
        elif "premier" in titulo.lower():
            query_final = "english football stadium"
        elif not query_final or any(w in query_final for w in ["contract", "deal", "transfer", "gossip", "money", "signing", "football match"]):
            query_final = "soccer player pitch"

    # 1. Intentar Wikimedia Commons primero con la consulta optimizada
    wiki_res = buscar_imagen_wikimedia(query_final)
    if wiki_res:
        log.info("✅ Usando imagen de Wikimedia Commons.")
        return wiki_res

    # 2. Respaldo a Pexels / Pixabay
    log.info("⚠️ No se encontró imagen en Wikimedia. Usando imágenes de stock...")
    img_path = DIR_IMG_PATH / f"portada_{int(time.time())}_{random.randint(100, 999)}.jpg"
    
    pexels_key = "" 
    pixabay_key = ""
    try:
        from config import PEXELS_API_KEY, PIXABAY_API_KEY
        pexels_key = PEXELS_API_KEY
        pixabay_key = PIXABAY_API_KEY
    except ImportError:
        pass
    
    img_url = None

    # 1. Intentar Pexels
    try:
        if pexels_key and pexels_key != "TU_CLAVE_AQUI":
            log.info(f"Buscando imagen en Pexels para: {query_final}")
            url = f"https://api.pexels.com/v1/search?query={query_final}&per_page=15&orientation=landscape"
            headers = {"Authorization": pexels_key}
            req = requests.get(url, headers=headers, timeout=15)
            if req.status_code == 200:
                photos = req.json().get('photos', [])
                if photos:
                    img_url = random.choice(photos)['src']['large2x']
    except Exception as e:
        log.warning(f"Error con Pexels: {e}")

    # 2. Intentar Pixabay si Pexels falló
    if not img_url:
        try:
            if pixabay_key and pixabay_key != "TU_CLAVE_AQUI":
                log.info(f"Buscando imagen en Pixabay para: {query_final}")
                query_pix = query_final.replace(" ", "+")
                url = f"https://pixabay.com/api/?key={pixabay_key}&q={query_pix}&image_type=photo&orientation=horizontal&per_page=15"
                req = requests.get(url, timeout=15)
                if req.status_code == 200:
                    hits = req.json().get('hits', [])
                    if hits:
                        img_url = random.choice(hits)['largeImageURL']
        except Exception as e:
            log.warning(f"Error con Pixabay: {e}")

    # 3. Imagen genérica si ambos fallaron
    if not img_url:
        log.warning("No se pudo obtener imagen de Pexels ni Pixabay. Usando genérica.")
        img_url = "https://images.pexels.com/photos/114296/pexels-photo-114296.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=1"
        
    # Descargar
    try:
        log.info("Descargando imagen fotográfica...")
        img_data = requests.get(img_url, timeout=30).content
        with open(img_path, 'wb') as f:
            f.write(img_data)
        log.info(f"Imagen descargada con éxito: {img_path}")
        return str(img_path), None
    except Exception as e:
        log.warning(f"Error final al descargar la imagen: {e}")
        return None


# =============================================================================
# 5. PUBLICACIÓN EN WORDPRESS
# =============================================================================

def subir_imagen_a_wordpress(img_path: str, titulo: str) -> int | None:
    """Sube la imagen al Media Library de WordPress. Devuelve el ID del media."""
    try:
        filename = Path(img_path).name
        with open(img_path, "rb") as f:
            img_data = f.read()

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "image/png",
        }
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            auth=WP_AUTH,
            headers=headers,
            data=img_data,
            timeout=60,
        )
        resp.raise_for_status()
        media_id = resp.json().get("id")
        log.info(f"Imagen subida a WordPress. Media ID: {media_id}")
        return media_id
    except Exception as e:
        log.error(f"Error subiendo imagen a WordPress: {e}")
        return None


def generar_slug(titulo: str) -> str:
    """Genera un slug SEO-friendly a partir del título."""
    slug = titulo.lower()
    # Reemplazar caracteres especiales
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ü": "u", "ñ": "n", "ç": "c",
    }
    for char, repl in reemplazos.items():
        slug = slug.replace(char, repl)
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]  # Máximo 80 caracteres


def generar_excerpt(contenido_html: str) -> str:
    """Genera un extracto de 160 caracteres sin HTML para SEO."""
    texto = limpiar_html(contenido_html)
    return texto[:157] + "..." if len(texto) > 157 else texto


def publicar_en_wordpress(titulo: str, contenido: str, media_id: int | None, categorias: list[int] = None, tags: list[int] = None) -> dict | None:
    """Publica el artículo en WordPress. Devuelve la respuesta JSON o None."""
    payload = {
        "title": titulo,
        "content": contenido,
        "status": WP_POST_STATUS,
        "slug": generar_slug(titulo),
        "excerpt": generar_excerpt(contenido),
        "format": "standard",
    }
    if media_id:
        payload["featured_media"] = media_id
        
    if categorias:
        payload["categories"] = categorias
    elif WP_CATEGORY_ID:
        payload["categories"] = [WP_CATEGORY_ID]

    if tags:
        payload["tags"] = tags

    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            auth=WP_AUTH,
            headers=WP_HEADERS,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        post_data = resp.json()
        log.info(f"✅ Post publicado: {post_data.get('link')} (ID: {post_data.get('id')})")
        return post_data
    except Exception as e:
        log.error(f"Error publicando en WordPress: {e}")
        if hasattr(e, "response") and e.response is not None:
            log.error(f"Respuesta del servidor: {e.response.text[:500]}")
        return None


# =============================================================================
# 6. CICLO PRINCIPAL
# =============================================================================

def ejecutar_ciclo():
    """Ejecuta un ciclo completo con las secciones: News, Transfers y Football Gossip."""
    log.info("=" * 60)
    log.info(f"🚀 INICIO DE CICLO MULTI-SECCIÓN — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    publicadas = cargar_publicadas()
    log.info(f"Artículos publicados hasta ahora: {publicadas['total_publicados']}")

    # 1. Obtener noticias de cada sección
    noticias_news = obtener_noticias_rss(RSS_FEEDS)
    noticias_transfers = obtener_noticias_rss(FEEDS_TRANSFERS)
    noticias_gossip = obtener_noticias_rss(FEEDS_GOSSIP)
    
    # 2. Configurar límites
    secciones = [
        {"name": "news", "limit": ARTICULOS_NEWS, "pool": noticias_news, "categories": [CAT_NEWS]},
        {"name": "transfers", "limit": ARTICULOS_TRANSFERS, "pool": noticias_transfers, "categories": [CAT_TRANSFERS, CAT_FINANCE]},
        {"name": "gossip", "limit": ARTICULOS_GOSSIP, "pool": noticias_gossip, "categories": [CAT_GOSSIP]}
    ]
    
    articulos_publicados_en_ciclo = 0

    for sec in secciones:
        log.info(f"\n--- Procesando sección: {sec['name'].upper()} (Límite: {sec['limit']}) ---")
        publicados_seccion = 0
        pool = sec["pool"]
        
        if not pool:
            log.warning(f"No hay noticias disponibles en el pool de {sec['name']}.")
            continue
            
        total_noticias = len(pool)
        for idx, noticia in enumerate(pool):
            if publicados_seccion >= sec["limit"]:
                break
                
            if ya_fue_publicada(noticia["url"], publicadas):
                continue

            log.info(f"📰 [{sec['name'].upper()}] [{idx+1}/{total_noticias}] Noticia seleccionada: {noticia['titulo']}")
            log.info(f"   URL: {noticia['url']}")

            # Extraer entidad (jugador y equipo)
            jugador, equipo = extraer_entidades(noticia["titulo"], noticia["resumen"])
            if jugador:
                log.info(f"   Entidades detectadas: Jugador={jugador}, Equipo={equipo}")
                # Verificar Cooldown
                if verificar_cooldown(jugador, sec["name"]):
                    log.warning(f"   ⚠️ Jugador '{jugador}' está en cooldown para la sección '{sec['name']}'. Saltando.")
                    marcar_como_publicada(noticia["url"], publicadas)
                    continue
            
            # Clasificar fuente (Tier)
            tier = fuente_tier(noticia["url"])
            log.info(f"   Clasificación de confianza de la fuente: {tier}")

            # Investigación adicional
            datos_investigacion = ""
            if sec["name"] == "transfers" and jugador:
                results = buscar_web(f"{jugador} market value salary transfer fee history", num_results=3)
                datos_investigacion = "\n".join([f"- Title: {r['title']}\n  Snippet: {r['snippet']}\n  URL: {r['url']}" for r in results])
            elif sec["name"] == "gossip" and jugador:
                # Buscar rumores y cotilleo
                results_g = buscar_web(f"{jugador} gossip private lifestyle purchases", num_results=3)
                # Buscar respuesta oficial del jugador
                results_resp = buscar_web(f"{jugador} official statement responds denies", num_results=2)
                
                datos_investigacion = "Gossip & Fan Reaction:\n"
                datos_investigacion += "\n".join([f"- Title: {r['title']}\n  Snippet: {r['snippet']}" for r in results_g])
                if results_resp:
                    datos_investigacion += "\n\nOfficial Responses/Denials:\n"
                    datos_investigacion += "\n".join([f"- Title: {r['title']}\n  Snippet: {r['snippet']}" for r in results_resp])

            # Redactar artículo
            try:
                titulo_es, contenido, _, query_imagen = redactar_articulo(
                    titulo=noticia["titulo"],
                    resumen=noticia["resumen"],
                    fuente=noticia["fuente"],
                    seccion=sec["name"],
                    datos_investigacion=datos_investigacion,
                    tier=tier
                )
            except Exception as e:
                log.error(f"Error en redacción: {e}")
                marcar_como_publicada(noticia["url"], publicadas)
                continue

            # Generar imagen
            media_id = None
            credits = None
            img_res = generar_imagen_portada(titulo_es, query_imagen, equipo)
            if img_res:
                img_path, credits = img_res
                if img_path and Path(img_path).exists():
                    media_id = subir_imagen_a_wordpress(img_path, titulo_es)
                    try:
                        Path(img_path).unlink()
                    except Exception:
                        pass

            # Créditos del fotógrafo
            if credits:
                contenido += f'\n\n<p style="font-size: 11px; color: #777777; font-style: italic; text-align: right; margin-top: 20px;">{credits}</p>'

            # Crear tags de jugador y equipo
            tags_ids = []
            if jugador:
                id_tag_jugador = obtener_o_crear_tag(jugador)
                if id_tag_jugador:
                    tags_ids.append(id_tag_jugador)
            if equipo:
                id_tag_equipo = obtener_o_crear_tag(equipo)
                if id_tag_equipo:
                    tags_ids.append(id_tag_equipo)

            # Publicar en WordPress
            resultado = publicar_en_wordpress(
                titulo=titulo_es,
                contenido=contenido,
                media_id=media_id,
                categorias=sec["categories"],
                tags=tags_ids if tags_ids else None
            )

            if resultado:
                marcar_como_publicada(noticia["url"], publicadas)
                publicados_seccion += 1
                articulos_publicados_en_ciclo += 1
                if jugador:
                    registrar_cooldown(jugador, sec["name"])
                log.info(f"✅ [{sec['name'].upper()}] [{publicados_seccion}/{sec['limit']}] Publicado: {resultado.get('link')}")
                
                # Filtro de palabras sensibles (Gossip) y Telegram Alerta
                if sec["name"] == "gossip":
                    PALABRAS_SENSIBLES = [
                        "affair", "divorce", "arrested", "assault", "lawsuit", "sued",
                        "cheating", "scandal", "drugs", "doping", "racism", "abuse",
                        "court", "prison", "domestic", "victim", "sexual"
                    ]
                    palabras_detectadas = [w for w in PALABRAS_SENSIBLES if w in contenido.lower() or w in titulo_es.lower()]
                    if palabras_detectadas:
                        log.warning(f"⚠️ Palabras de riesgo detectadas: {palabras_detectadas}. Enviando alerta por Telegram...")
                        enviar_alerta_telegram(titulo_es, resultado.get("link"), palabras_detectadas)
            else:
                log.error("❌ Falló la publicación del artículo.")
                marcar_como_publicada(noticia["url"], publicadas)

            # Pausa de 150 segundos entre artículos para emular flujo humano
            time.sleep(150)

    log.info(f"🏁 FIN DE CICLO MULTI-SECCIÓN — Artículos publicados: {articulos_publicados_en_ciclo}")
    log.info("=" * 60)


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    log.info("Bot Futbol Sportivonix arrancando en modo bucle continuo...")
    # Importar CICLO_HORAS localmente por si acaso
    try:
        from config import CICLO_HORAS
    except ImportError:
        CICLO_HORAS = 1

    while True:
        try:
            ejecutar_ciclo()
        except Exception as e:
            log.error(f"Error inesperado durante la ejecución del ciclo: {e}")
        
        segundos_espera = CICLO_HORAS * 3600
        log.info(f"Esperando {CICLO_HORAS} hora(s) ({segundos_espera} segundos) antes de iniciar el próximo ciclo de noticias...")
        time.sleep(segundos_espera)
