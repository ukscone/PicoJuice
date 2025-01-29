from machine import Pin, UART
import network
import time
import urequests
import json
import os
import socket

# Core system configuration
UART_BAUDRATE = 115200        # Communication speed with host
WIFI_TIMEOUT = 10            # Seconds to wait for WiFi connection
VERSION = "0.0.3"

class Hardware:
    def __init__(self):
        # LED initialization
        self.led = Pin("LED", Pin.OUT)     # PicoW On-board LED used as READY indicator 
        self.red_led = Pin(11, Pin.OUT)    # TX indicator
        self.yellow_led = Pin(12, Pin.OUT)  # RX indicator
        self.green_led = Pin(13, Pin.OUT)   # WiFi status
        
        # Set initial LED states to off
        self.led.off()
        self.red_led.off()
        self.yellow_led.off()
        self.green_led.off()
        
        # Initialize UART and WiFi
        self.uart = UART(0, baudrate=UART_BAUDRATE)
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        

class PicoJuice:
    def __init__(self):
        # Initialize hardware interface
        self.hw = Hardware()
        time.sleep(5)  # Startup delay for system stability. Not required, but why not?.
        self.hw.led.on()
        
        # Wait for initial handshake. 
        # Yellow LED might also light up during this time.
        while True:
            line = self.read_line()
            if line == "OK":
                break
        
        # Display startup banner
        self.send_response(f"\n'PICOJUICE {VERSION}")
        
        # Initialize and load bookmarks
        self.bookmarks = {}
        self.load_bookmarks()
        
        # Restore previous WiFi connection if possible
        try:
            with open('wifi.json', 'r') as f:
                creds = json.load(f)
                ip = self.wifi_connect(creds['ssid'], creds['password'])
                if ip:
                    self.send_response(f"'Connected to {creds['ssid']}, IP: {ip}")
        except:
            pass
        
        # Create PROGRAMS directory if it doesn't exist
        try:
            os.mkdir('PROGRAMS')
        except OSError:
            pass
        
    def load_bookmarks(self):
        try:
            with open('bookmarks.json', 'r') as f:
                self.bookmarks = json.load(f)
        except:
            self.bookmarks = {}

    def handle_bookmark(self, key, url):
        if not key.startswith('**'):
            return "'Bookmark keys must start with **"
        
        self.bookmarks[key] = url
        with open('bookmarks.json', 'w') as f:
            json.dump(self.bookmarks, f)
        self.load_bookmarks()
        return "'Bookmark saved"

    def handle_list_bookmarks(self):
        if not self.bookmarks:
            return "'No bookmarks found"
        return '\n'.join(f"'{key}: {url}" for key, url in self.bookmarks.items())

    def resolve_bookmark(self, url_or_key):
        resolved = url_or_key
        if url_or_key.startswith('**'):
            resolved = self.bookmarks.get(url_or_key, url_or_key)
        print(resolved)
        return resolved

    def read_line(self):
        buffer = []
        self.hw.yellow_led.on()
        
        while True:
            if self.hw.uart.any():
                char = self.hw.uart.read(1).decode('ascii')
                if char in '\r\n':
                    received = ''.join(buffer).strip()
                    print("Received:", received)
                    self.hw.yellow_led.off()
                    return received
                buffer.append(char)
            time.sleep(0.01)

    def send_response(self, text):
        print("Sent:", text)
        self.hw.red_led.on()
        self.hw.uart.write(f"{text}\r\n".encode())
        self.hw.red_led.off()

    def get_help_text(self):
        return "\n".join([
            "'PICOJUICE Commands:",
            "'HELP - Show this help",
            "'VER - Show firmware version",
            "'APL - List available WiFi networks",
            "'APC ssid password - Connect to WiFi",
            "'APD - Disconnect from WiFi",
            "'API - Show WiFi network info",
            "'APS - Show WiFi connection status (0/1)",
            "'APW - Show WiFi network name",
            "'APR - Reset WiFi",
            "'MAC - Show WiFi MAC address",
            "'GET(S) url - HTTP GET(S)",
            "'UDP ip port message - Send UDP",
            "'LOAD filename - Load .IJB file",
            "'SAVE filename - Save to file",
            "'DIR - List .IJB files",
            "'DEL filename - Delete .IJB file",
            "'BOOKMARK **key url - Save URL bookmark",
            "'BOOKMARKS - List all saved URL bookmarks"
        ])

    def normalize_url(self, url):
        if url.upper().startswith('HTTP://'):
            return 'http://' + url[7:]
        elif url.upper().startswith('HTTPS://'):
            return 'https://' + url[8:]
        return url

    def handle_apl(self):
        connected_ssid = self.hw.wlan.config('ssid') if self.hw.wlan.isconnected() else None
        return '\n'.join(
            f"'{'*' if net[0].decode('utf-8') == connected_ssid else ''}{net[0].decode('utf-8')}"
            for net in self.hw.wlan.scan()
        )

    def handle_apc(self, ssid, password):
        ip = self.wifi_connect(ssid, password)
        return f"'Connected to {ssid}, IP: {ip}" if ip else "'Connection failed"

    def handle_apd(self):
        self.hw.wlan.disconnect()
        self.hw.green_led.off()
        return "'Disconnected"

    def handle_apr(self):
        self.hw.wlan.disconnect()
        self.hw.wlan.active(False)
        self.hw.green_led.off()
        time.sleep(1)
        self.hw.wlan.active(True)
        return "'WiFi Reset"

    def handle_api(self):
        if self.hw.wlan.isconnected():
            status = self.hw.wlan.ifconfig()
            return f"'Connected, IP: {status[0]}, Netmask: {status[1]}, Gateway: {status[2]}"
        return "'Not connected"

    def handle_aps(self):
        return "1" if self.hw.wlan.isconnected() else "0"

    def handle_apw(self):
        return f"'{self.hw.wlan.config('ssid')}" if self.hw.wlan.isconnected() else "'Not connected"

    def wifi_connect(self, ssid, password):
        self.hw.wlan.connect(ssid, password)
        for _ in range(WIFI_TIMEOUT):
            if self.hw.wlan.isconnected():
                self.save_wifi_credentials(ssid, password)
                self.hw.green_led.on()
                return self.hw.wlan.ifconfig()[0]
            time.sleep(1)
        self.hw.green_led.off()
        return None

    def save_wifi_credentials(self, ssid, password):
        with open('wifi.json', 'w') as f:
            json.dump({'ssid': ssid, 'password': password}, f)

    def handle_get(self, url, secure=False):
        if not self.hw.wlan.isconnected():
            return "'Not Connected"
        
        resolved_url = self.resolve_bookmark(url)
        if not any(resolved_url.lower().startswith(proto.lower()) for proto in ('http://', 'https://')):
            resolved_url = f"{'https' if secure else 'http'}://{resolved_url}"

        print(resolved_url)
        try:
            normalized_url = self.normalize_url(resolved_url)
            response = urequests.get(normalized_url)
            text = response.text
            response.close()
            return text
        except Exception as e:
            print("Full exception:", repr(e))
            return f"'{str(e)}"

    def handle_udp(self, ip, port, message):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(message.encode(), (ip, int(port)))
            sock.close()
            return "'UDP sent"
        except Exception as e:
            return f"'Error: {str(e)}"

    def handle_save(self, filename):
        self.send_response("LIST")
        collected = []
        first_ok = True
        
        while True:
            line = self.read_line()
            if line == "OK":
                if first_ok:
                    first_ok = False
                else:
                    with open(f"PROGRAMS/{filename}.IJB", 'w') as f:
                        f.write('\n'.join(collected))
                    return "'File saved"
            elif line:
                collected.append(line)

    def handle_dir(self):
        files = [f for f in os.listdir('PROGRAMS') if f.endswith('.IJB')]
        if not files:
            return "'No .IJB files found"
        return '\n'.join(f"'{f} {os.stat('PROGRAMS/' + f)[6]}" for f in files)

    def handle_del(self, filename):
        try:
            os.remove(f"PROGRAMS/{filename}.IJB")
            return "'File deleted"
        except:
            return "'Error deleting file"

    def handle_load(self, filename):
        try:
            with open(f"PROGRAMS/{filename}.IJB", 'r') as f:
                for line in f:
                    self.send_response(line.strip())
            return "'File loaded"
        except:
            return "'Error loading file"
    def get_mac_address(self):
        mac = self.hw.wlan.config('mac')
        return f"'{''.join([f'{b:02x}' for b in mac])}"

    def handle_command(self, cmd):
        parts = cmd.strip().split(None, 2)
        command = parts[0].upper()
        
        handlers = {
            'VER': lambda: f"'PICOJUICE Version {VERSION}",
            'MAC': self.get_mac_address,
            'HELP': self.get_help_text,
            'APL': self.handle_apl,
            'APC': lambda: self.handle_apc(parts[1], parts[2]) if len(parts) >= 3 else "'Error: Missing parameters",
            'APD': self.handle_apd,
            'APR': self.handle_apr,
            'API': self.handle_api,
            'APS': self.handle_aps,
            'APW': self.handle_apw,
            'GET': lambda: self.handle_get(parts[1]) if len(parts) >= 2 else "'Error: Missing URL",
            'GETS': lambda: self.handle_get(parts[1], secure=True) if len(parts) >= 2 else "'Error: Missing URL",
            'UDP': lambda: self.handle_udp(parts[1], parts[2], parts[3]) if len(parts) >= 4 else "'Error: Missing parameters",
            'SAVE': lambda: self.handle_save(parts[1]) if len(parts) >= 2 else "'Error: Missing filename",
            'DIR': self.handle_dir,
            'DEL': lambda: self.handle_del(parts[1]) if len(parts) >= 2 else "'Error: Missing filename",
            'LOAD': lambda: self.handle_load(parts[1]) if len(parts) >= 2 else "'Error: Missing filename",
            'BOOKMARK': lambda: self.handle_bookmark(parts[1], parts[2]) if len(parts) >= 3 else "'Error: Missing parameters",
            'BOOKMARKS': self.handle_list_bookmarks
        }
        
        if command in handlers:
            return handlers[command]()
        return None

    def run(self):
        while True:
            if self.hw.uart.any():
                line = self.read_line()
                if line and line.upper().startswith('MJ'):
                    cmd = line[line.upper().find('MJ')+2:]
                    response = self.handle_command(cmd)
                    if response:
                        self.send_response(response)
            time.sleep(0.01)

def main():
    pico = PicoJuice()
    pico.run()

if __name__ == '__main__':
    main()
