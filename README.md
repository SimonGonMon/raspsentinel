# Raspsentinel

Raspsentinel vigila tu red local, notifica por Telegram cuando aparece un dispositivo nuevo y permite administrarlo (permitir, bloquear o ignorar) desde el bot o la CLI. Pensado para Raspberry Pi OS, consume pocos recursos y corre como servicio systemd.

## Instalación express

Ejecuta en tu Raspberry Pi (requiere sudo). El script instala dependencias, despliega la app en `/opt/raspsentinel` y registra el servicio.

```bash
curl -sSL https://raw.githubusercontent.com/simongonmon/raspsentinel/main/install.sh | sudo bash
```

> Usa la variable `REPO_URL` si quieres instalar desde un fork:  
> `curl -sSL ... | sudo REPO_URL=https://github.com/tu-usuario/raspsentinel.git bash`

## Configuración inicial

1. Lanza el asistente:
   ```bash
   sudo raspsentinel setup
   ```
   Necesitas:
   - Token del bot de Telegram (via `@BotFather`).
   - Tu `chat_id` (obtenlo con `@userinfobot`).
   - Interfaz de red a vigilar (`wlan0`, `eth0`, ...). El asistente intenta detectarla y la propone por defecto.
   - IP del gateway/router (para el bloqueo por ARP spoofing). También se sugiere automáticamente y puedes modificarla.
2. Activa el servicio:
   ```bash
   sudo raspsentinel enable
   sudo raspsentinel start
   sudo raspsentinel status
   ```
3. Sigue los logs:
   ```bash
   sudo raspsentinel logs
   ```

La configuración se guarda en `/etc/raspsentinel/config.yaml`.

## Comandos útiles

- `sudo raspsentinel setup` – asistente de configuración.
- `sudo raspsentinel start|stop|restart` – controla el servicio.
- `sudo raspsentinel enable|disable` – gestiona el arranque automático.
- `sudo raspsentinel status` – estado del servicio.
- `sudo raspsentinel logs -n 100 --no-follow` – muestra logs sin seguir.
- `sudo raspsentinel config show|get|set|wizard` – opciones avanzadas.

## Uso del bot

Comandos disponibles (solo para el `chat_id` autorizado):

- `/connected` – lista de dispositivos vistos recientemente con paginación (5 por página) y botón de refresco.
- `/allowlist` / `/blocklist` – listas actuales.
- `/add_allow <MAC> [nombre]` / `/rm_allow <MAC>`.
- `/add_block <MAC> [motivo]` / `/rm_block <MAC>`.
- `/settings` – muestra la ubicación del archivo de config.
- `/id` – devuelve tu `chat_id` actual.

Cuando aparece un MAC desconocido el bot envía un mensaje con botones **Permitir**, **Bloquear** o **Ignorar**.

## Bloqueo por ARP spoofing

Si habilitas el bloqueo, Raspsentinel envía respuestas ARP falsas al dispositivo objetivo, indicando que la Raspberry Pi es el gateway. De este modo el tráfico se corta sin necesidad de reglas nftables. Para que funcione:

- La Raspberry Pi debe estar en la misma LAN que el objetivo y el gateway.
- El servicio se ejecuta con CAP_NET_RAW para poder emitir paquetes ARP.
- El bloqueo se mantiene mientras el dispositivo esté en la blocklist y el servicio en ejecución.

> Importante: esto solo evita que el cliente alcance el gateway. No elimina rutas alternativas ni actúa como ataque de desautenticación Wi‑Fi.

## Requisitos

- Raspberry Pi OS (Bookworm/Bullseye) o Debian/Ubuntu con `apt`.
- Python 3.11+.
- Paquetes: `git`, `python3-venv`, `python3-pip`, `arp-scan`.
- Conectividad a Internet durante la instalación (para clonar e instalar dependencias).

## Desinstalación

```bash
sudo raspsentinel stop
sudo raspsentinel disable
sudo rm -rf /opt/raspsentinel /etc/raspsentinel /var/lib/raspsentinel
sudo userdel raspsentinel
sudo rm -f /usr/local/bin/raspsentinel /etc/systemd/system/raspsentinel.service
sudo systemctl daemon-reload
```

Listo. El servicio y sus archivos quedan eliminados.
