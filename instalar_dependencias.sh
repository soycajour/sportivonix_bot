#!/bin/bash
# =============================================================
# INSTALADOR DE DEPENDENCIAS — BOT FUTBOL SPORTIVONIX
# Ejecutar una sola vez para preparar el entorno
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📦 Instalando dependencias para Bot Futbol Sportivonix..."
echo "   Directorio: $SCRIPT_DIR"

# Instalar pip si no está disponible
if ! python3 -m pip --version &>/dev/null; then
    echo "⚙️  pip no encontrado. Bootstrapeando pip..."
    curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    python3 /tmp/get-pip.py --break-system-packages
fi

# Instalar dependencias Python
echo "⚙️  Instalando paquetes Python..."
python3 -m pip install --break-system-packages feedparser Pillow requests google-generativeai duckduckgo-search

echo ""
echo "✅ Dependencias instaladas correctamente."
echo ""
echo "⚙️  Configurando cron job (cada 1 horas)..."

# Añadir cron job si no existe ya
CRON_CMD="0 * * * * /usr/bin/python3 \"$SCRIPT_DIR/bot_futbol.py\" >> \"$SCRIPT_DIR/bot_futbol.log\" 2>&1"
(crontab -l 2>/dev/null | grep -v "bot_futbol.py"; echo "$CRON_CMD") | crontab -

echo "✅ Cron job configurado:"
crontab -l | grep "bot_futbol"
echo ""
echo "🚀 Para ejecutar el bot manualmente AHORA:"
echo "   python3 \"$SCRIPT_DIR/bot_futbol.py\""
echo ""
echo "📋 Para ver el log en tiempo real:"
echo "   tail -f \"$SCRIPT_DIR/bot_futbol.log\""

#solo para probar que todo salio bien el server