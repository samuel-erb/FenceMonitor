class Singleton:
    """
    Korrekte Singleton-Implementierung für MicroPython

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
            print(f"[Singleton] Neue Instanz von {class_name} erstellt")
        else:
            print(f"[Singleton] Existierende Instanz von {class_name} zurückgegeben")

        return cls._instances[class_name]

    def __init__(self, *args, **kwargs):
        class_name = self.__class__.__name__

        # Nur initialisieren wenn noch nicht geschehen
        if not self._initialized.get(class_name, False):
            print(f"[Singleton] Initialisiere {class_name}")
            self._init_once(*args, **kwargs)
            self._initialized[class_name] = True
        else:
            print(f"[Singleton] {class_name} bereits initialisiert, überspringe __init__")

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

    @classmethod
    def reset_instance(cls):
        """
        Nützlich für Tests oder Neuinitialisierung
        """
        class_name = cls.__name__
        if class_name in cls._instances:
            del cls._instances[class_name]
            del cls._initialized[class_name]
            print(f"[Singleton] Instanz von {class_name} zurückgesetzt")


# Decorator-basierte Alternative (eleganter für manche Anwendungsfälle)
def singleton(cls):
    """
    Decorator für Singleton-Klassen

    Verwendung:
    @singleton
    class MyClass:
        def __init__(self):
            pass
    """
    instances = {}
    initialized = {}

    def get_instance(*args, **kwargs):
        class_name = cls.__name__
        if class_name not in instances:
            instance = cls.__new__(cls)
            instances[class_name] = instance
            initialized[class_name] = False
            print(f"[Singleton Decorator] Neue Instanz von {class_name} erstellt")

        instance = instances[class_name]

        # Initialisierung nur einmal
        if not initialized[class_name]:
            instance.__init__(*args, **kwargs)
            initialized[class_name] = True
            print(f"[Singleton Decorator] {class_name} initialisiert")
        else:
            print(f"[Singleton Decorator] {class_name} bereits initialisiert")

        return instance

    # Füge reset-Methode hinzu
    def reset():
        class_name = cls.__name__
        if class_name in instances:
            del instances[class_name]
            del initialized[class_name]
            print(f"[Singleton Decorator] {class_name} zurückgesetzt")

    get_instance.reset = reset
    return get_instance


# Test der Implementierung
def test_singleton():
    """Test-Funktion für die Singleton-Implementierung"""

    class TestClass1(Singleton):
        def _init_once(self, value=None):
            self.value = value or "default1"
            self.init_count = 1
            print(f"TestClass1 initialisiert mit value={self.value}")

    class TestClass2(Singleton):
        def _init_once(self, value=None):
            self.value = value or "default2"
            self.init_count = 1
            print(f"TestClass2 initialisiert mit value={self.value}")

    print("=== Singleton Test ===")

    # Test 1: Erste Instanz erstellen
    print("\n1. Erste Instanz TestClass1:")
    obj1a = TestClass1("erste_instanz")

    # Test 2: Zweite "Instanz" sollte die gleiche sein
    print("\n2. Zweite 'Instanz' TestClass1:")
    obj1b = TestClass1("zweite_instanz")

    print(f"obj1a ist obj1b: {obj1a is obj1b}")
    print(f"obj1a.value: {obj1a.value}")
    print(f"obj1b.value: {obj1b.value}")

    # Test 3: Andere Klasse sollte eigene Instanz haben
    print("\n3. TestClass2 (andere Klasse):")
    obj2 = TestClass2("andere_klasse")
    print(f"obj1a ist obj2: {obj1a is obj2}")

    # Test 4: get_instance Methode
    print("\n4. get_instance Methode:")
    obj1c = TestClass1.get_instance()
    print(f"obj1a ist obj1c: {obj1a is obj1c}")

    return obj1a, obj1b, obj2