import signal
import sys
import threading
import time
from lora_gateway import LoRaGateway

# Flag für das Beenden
shutdown_event = threading.Event() # type: threading.Event


def graceful_shutdown(signum, frame):
    print(f"[LoRaGateway] Signal {signum} empfangen, fahre sauber herunter ...")
    shutdown_event.set()

handled_signals = [
    #signal.SIGTERM,
    #signal.SIGINT,
    #signal.SIGHUP,
    #signal.SIGQUIT
]
for sig in handled_signals:
    signal.signal(sig, graceful_shutdown)


def main():
    print("Programm läuft. Drücke Ctrl+C zum Beenden.")
    try:
        while not shutdown_event.is_set():
            gateway = LoRaGateway(shutdown_event)
            gateway.run()
            time.sleep(0.5)
    except Exception as e:
        print(f"Fehler aufgetreten: {e}")
    finally:
        print("Cleanup läuft ...")
        # Hier Ressourcen freigeben, Dateien schließen etc.
        print("Shutdown abgeschlossen.")
        sys.exit(0)


if __name__ == "__main__":
        main()