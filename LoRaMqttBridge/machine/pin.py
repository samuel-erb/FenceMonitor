from __future__ import annotations
from typing import Callable, Optional, Final, Any
import RPi.GPIO as GPIO


class Pin:
    """
    Kompatibilitätsschicht für MicroPython Pin-Klasse auf Raspberry Pi mit RPi.GPIO
    """

    # Konstanten für Pin-Modi
    IN: Final[int] = 1
    OUT: Final[int] = 3
    OPEN_DRAIN: Final[int] = 7
    ALT: Final[int] = 0  # Alternative Funktion (nicht direkt unterstützt in RPi.GPIO)
    ALT_OPEN_DRAIN: Final[int] = 8
    ANALOG: Final[int] = 9  # Analog (nicht direkt unterstützt in RPi.GPIO)

    # Konstanten für Pull-Widerstände
    PULL_UP: Final[int] = 2
    PULL_DOWN: Final[int] = 1
    PULL_HOLD: Final[int] = 4  # Nicht unterstützt in RPi.GPIO

    # Konstanten für Interrupts
    IRQ_FALLING: Final[int] = 2
    IRQ_RISING: Final[int] = 1
    IRQ_LOW_LEVEL: Final[int] = 4  # Nicht direkt unterstützt in RPi.GPIO
    IRQ_HIGH_LEVEL: Final[int] = 8  # Nicht direkt unterstützt in RPi.GPIO

    # Konstanten für Wake-Modi
    WAKE_LOW: Final[int] = 4
    WAKE_HIGH: Final[int] = 5

    # Konstanten für Drive-Stärke (nicht unterstützt in RPi.GPIO)
    DRIVE_0: Final[int] = 0
    DRIVE_1: Final[int] = 1
    DRIVE_2: Final[int] = 2
    DRIVE_3: Final[int] = 3

    def __init__(
            self,
            id: Any,
            /,
            mode: int = -1,
            pull: int = -1,
            *,
            value: Any = None,
            drive: Optional[int] = None,
            alt: Optional[int] = None,
    ) -> None:
        """
        Initialisiert einen Pin
        """
        # GPIO-Setup
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Pin-Nummer speichern
        if isinstance(id, tuple):
            # Für (port, pin) Format - verwende nur die Pin-Nummer
            self._pin = id[1]
        else:
            self._pin = int(id)

        # Interne Zustände
        self._mode = mode
        self._pull = pull
        self._drive = drive
        self._alt = alt
        self._irq_handler = None
        self._irq_enabled = False

        # Pin initialisieren
        if mode != -1:
            self.init(mode=mode, pull=pull, value=value, drive=drive, alt=alt)

    def init(
            self,
            mode: int = -1,
            pull: int = -1,
            *,
            value: Any = None,
            drive: Optional[int] = None,
            alt: Optional[int] = None,
    ) -> None:
        """
        Re-initialisiert den Pin mit den gegebenen Parametern
        """
        # Modus setzen
        if mode != -1:
            self._mode = mode
            if mode == self.IN:
                # Pull-Widerstand konfigurieren
                if pull == self.PULL_UP:
                    GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                elif pull == self.PULL_DOWN:
                    GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                else:
                    GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
            elif mode == self.OUT or mode == self.OPEN_DRAIN:
                # RPi.GPIO unterstützt Open-Drain nicht direkt
                initial = GPIO.LOW if value == 0 else GPIO.HIGH if value == 1 else GPIO.LOW
                GPIO.setup(self._pin, GPIO.OUT, initial=initial)
            elif mode == self.ALT or mode == self.ALT_OPEN_DRAIN:
                # Alternative Funktionen werden von RPi.GPIO nicht direkt unterstützt
                print(f"Warning: Alternative function mode not directly supported")
            elif mode == self.ANALOG:
                # Analog-Modus wird von RPi.GPIO nicht direkt unterstützt
                print(f"Warning: Analog mode not directly supported")

        # Pull-Widerstand aktualisieren
        if pull != -1:
            self._pull = pull

        # Wert setzen, wenn angegeben
        if value is not None and (self._mode == self.OUT or self._mode == self.OPEN_DRAIN):
            self.value(value)

        # Drive und Alt speichern (auch wenn RPi.GPIO sie nicht nutzt)
        if drive is not None:
            self._drive = drive
        if alt is not None:
            self._alt = alt

    def value(self, x: Any = None) -> Optional[int]:
        """
        Setzt oder liest den Pin-Wert
        """
        if x is None:
            # Wert lesen
            if self._mode == self.IN:
                return GPIO.input(self._pin)
            elif self._mode == self.OUT or self._mode == self.OPEN_DRAIN:
                # Bei Output-Pins könnte der aktuelle Zustand zurückgegeben werden
                # RPi.GPIO bietet keine direkte Methode dafür
                return None
            return None
        else:
            # Wert setzen
            if self._mode == self.OUT:
                GPIO.output(self._pin, GPIO.HIGH if bool(x) else GPIO.LOW)
            elif self._mode == self.OPEN_DRAIN:
                # Open-Drain Simulation: LOW = Ausgang LOW, HIGH = High-Impedance (Input)
                if bool(x):
                    GPIO.setup(self._pin, GPIO.IN)
                else:
                    GPIO.setup(self._pin, GPIO.OUT)
                    GPIO.output(self._pin, GPIO.LOW)
            elif self._mode == self.IN:
                # Wert wird im Ausgangspuffer gespeichert, aber Pin bleibt Input
                pass
            return None

    def __call__(self, x: Any = None) -> Optional[int]:
        """
        Shortcut für value() Methode
        """
        return self.value(x)

    def on(self) -> None:
        """
        Setzt Pin auf HIGH
        """
        self.value(1)

    def off(self) -> None:
        """
        Setzt Pin auf LOW
        """
        self.value(0)

    def toggle(self) -> None:
        """
        Wechselt Pin-Zustand
        """
        if self._mode == self.OUT:
            # Versuche den aktuellen Zustand zu ermitteln und umzuschalten
            # Da RPi.GPIO keinen direkten Zugriff auf Output-Zustand bietet,
            # müssen wir einen internen Zustand verwalten
            current = GPIO.input(self._pin)
            GPIO.output(self._pin, GPIO.LOW if current else GPIO.HIGH)

    def irq(
            self,
            /,
            handler: Optional[Callable[["Pin"], None]] = None,
            trigger: int = (IRQ_FALLING | IRQ_RISING),
            *,
            priority: int = 1,
            wake: Optional[int] = None,
            hard: bool = False,
    ) -> Optional[Callable]:
        """
        Konfiguriert einen Interrupt-Handler
        """
        # Entferne vorherigen Handler wenn vorhanden
        if self._irq_enabled:
            GPIO.remove_event_detect(self._pin)
            self._irq_enabled = False

        # Setze neuen Handler wenn angegeben
        if handler is not None:
            self._irq_handler = handler

            # Wrapper für GPIO Callback
            def gpio_callback(channel):
                handler(self)

            # Event-Erkennung einrichten
            if trigger == self.IRQ_FALLING:
                GPIO.add_event_detect(self._pin, GPIO.FALLING, callback=gpio_callback)
            elif trigger == self.IRQ_RISING:
                GPIO.add_event_detect(self._pin, GPIO.RISING, callback=gpio_callback)
            elif trigger == (self.IRQ_FALLING | self.IRQ_RISING):
                GPIO.add_event_detect(self._pin, GPIO.BOTH, callback=gpio_callback)
            else:
                print(f"Warning: Trigger mode {trigger} not fully supported")
                return None

            self._irq_enabled = True
            return gpio_callback

        return None

    def mode(self, mode: Optional[int] = None) -> Optional[int]:
        """
        Setzt oder liest den Pin-Modus
        """
        if mode is None:
            return self._mode
        else:
            self.init(mode=mode)
            return None

    def pull(self, pull: Optional[int] = None) -> Optional[int]:
        """
        Setzt oder liest den Pull-Widerstand
        """
        if pull is None:
            return self._pull
        else:
            self.init(pull=pull)
            return None

    def drive(self, drive: Optional[int] = None) -> Optional[int]:
        """
        Setzt oder liest die Drive-Stärke (nicht unterstützt in RPi.GPIO)
        """
        if drive is None:
            return self._drive
        else:
            self._drive = drive
            print(f"Warning: Drive strength not supported by RPi.GPIO")
            return None

    class board:
        """
        Board-spezifische Pin-Definitionen können hier hinzugefügt werden
        """

        def __init__(self, *argv, **kwargs) -> None:
            pass

    def __del__(self):
        """
        Cleanup bei Objekt-Zerstörung
        """
        try:
            if self._irq_enabled:
                GPIO.remove_event_detect(self._pin)
            # Hinweis: GPIO.cleanup() nicht hier aufrufen, da andere Pins noch aktiv sein könnten
        except:
            pass

# Optional: Wrapper-Funktion für sauberes Beenden
def cleanup():
    """
    Räumt alle GPIO-Einstellungen auf
    """
    GPIO.cleanup()