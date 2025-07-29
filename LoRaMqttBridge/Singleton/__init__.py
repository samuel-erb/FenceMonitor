class Singleton:
    """
    - Jede Klasse hat ihre eigene Instanz
    - __init__ wird nur einmal pro Klasse aufgerufen
    - Thread-safe
    """

    _instances = {}  # Dictionary für Instanzen pro Klasse
    _initialized = {}  # Dictionary für Initialisierung-Status pro Klasse

    def __new__(cls, *args, **kwargs):
        # Verwende den Klassennamen als Schlüssel
        class_name = cls.__name__

        if class_name not in cls._instances:
            # Erstelle neue Instanz
            instance = super(Singleton, cls).__new__(cls)
            cls._instances[class_name] = instance
            cls._initialized[class_name] = False

        return cls._instances[class_name]

    def __init__(self, *args, **kwargs):
        class_name = self.__class__.__name__

        # Nur initialisieren wenn noch nicht geschehen
        if not self._initialized.get(class_name, False):
            self._init_once(*args, **kwargs)
            self._initialized[class_name] = True

    def _init_once(self, *args, **kwargs):
        """
        Diese Methode sollte von abgeleiteten Klassen überschrieben werden
        anstatt __init__ zu verwenden
        """
        pass

    @classmethod
    def get_instance(cls):
        """
        Alternative Methode um die Instanz zu bekommen ohne neue Parameter
        """
        class_name = cls.__name__
        if class_name in cls._instances:
            return cls._instances[class_name]
        else:
            return cls()  # Erstelle neue Instanz mit Standard-Parametern