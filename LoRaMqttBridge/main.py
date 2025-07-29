import signal
import sys
import threading

from LoRaNetworking.LoRaNetworking import LoRaNetworking
from lora_gateway import LoRaGateway




def main():
    # Flag für das Beenden
    shutdown_event = threading.Event()  # type: threading.Event
    gateway = LoRaGateway(shutdown_event)

    def graceful_shutdown(signum, frame):
        print(f"[LoRaGateway] Signal {signum} empfangen, fahre sauber herunter ...")
        shutdown_event.set()
        LoRaNetworking().stop()
        gateway.stop()

    handled_signals = [
        signal.SIGTERM,
        signal.SIGINT,
        signal.SIGHUP,
        signal.SIGQUIT
    ]
    for sig in handled_signals:
        signal.signal(sig, graceful_shutdown)

    try:
        gateway.run()
    except KeyboardInterrupt:
        print("[LoRaGateway] Ctrl+C empfangen, fahre sauber herunter ...")
        shutdown_event.set()
    except Exception as e:
        print(f"Fehler aufgetreten: {e}")
        shutdown_event.set()
    finally:
        print("Cleanup läuft ...")
        if gateway:
            gateway.stop()
        print("Shutdown abgeschlossen.")
        sys.exit(0)


if __name__ == "__main__":
        main()