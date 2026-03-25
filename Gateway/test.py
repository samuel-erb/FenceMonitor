import _thread
import threading
import time
import traceback

from LoRaNetworking.LoRaTCPTest import LoRaTCPTest


def test():
    print("Starting test...")
    _thread.start_new_thread(_gateway_worker, ())
    _thread.start_new_thread(_sensor_worker, ())
    
    # Run for limited time instead of infinite loop
    for i in range(40):  # 40 seconds total
        time.sleep(1)
        print(f"Test running... {i+1}s")
    
    print("Test finished")



def _gateway_worker():
    print("Gateway worker started")
    gateway = LoRaTCPTest(gateway=True)
    try:
        # Start listening in a separate thread
        listen_thread = threading.Thread(target=gateway.listen, daemon=True)
        listen_thread.start()
        print("Gateway listening...")
        
        # Main loop: handle PING/PONG (run() is now called automatically by TCPDataLink)
        for i in range(150):  # Run for 15 seconds (150 * 0.1s)
            # Check if we received PING and respond with PONG
            try:
                data = gateway.read()
                if data == b'PING':
                    print("Gateway received PING, sending PONG")
                    gateway.write(b'PONG')
                    # Gateway keeps connection open, sensor will initiate close
            except:
                pass  # No data available
            time.sleep(0.1)  # 100ms intervals
        
    except Exception as e:
        print(f"Error during LoRaGateway: {e}")
        print(traceback.format_exc())

def _sensor_worker():
    print("Sensor worker started")
    time.sleep(2)  # Wait for gateway to start listening
    sensor = LoRaTCPTest(gateway=False)
    try:
        sensor.connect(("127.0.0.1", 8080))  # Use localhost with unprivileged port
        print("Sensor connected")
        
        # Wait for connection to be established (run() is now called automatically by TCPDataLink)
        for i in range(50):  # Wait up to 5 seconds
            if sensor.tcb.state == 4:  # STATE_ESTAB
                print("Connection established!")
                break
            time.sleep(0.1)
        
        sensor.send(b'PING')
        print("Sensor sent PING")
        
        # Wait for response
        data = None
        for i in range(50):  # Wait up to 5 seconds for response
            try:
                data = sensor.read()
                if data:
                    break
            except:
                pass
            time.sleep(0.1)
        
        print(f"Sensor received: {data}")
        
        if data == b'PONG':
            print("Test successful!")
        
        sensor.close()
        print("Sensor connection closed")
    except Exception as e:
        print(f"Sensor error: {e}")
        print(traceback.format_exc())
test()