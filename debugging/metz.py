import socket
import time
import urllib.request

TV_IP = "192.168.1.131"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1)

# Search for UPnP devices using multicast and unicast
for target in ("upnp:rootdevice", "ssdp:all"):
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {target}\r\n\r\n"
    ).encode()

    sock.sendto(request, ("239.255.255.250", 1900))
    sock.sendto(request, (TV_IP, 1900))

locations = set()
deadline = time.monotonic() + 6

while time.monotonic() < deadline:
    try:
        data, addr = sock.recvfrom(65535)
    except socket.timeout:
        continue

    if addr[0] != TV_IP:
        continue

    response = data.decode("utf-8", errors="replace")
    print("\nSSDP response:\n", response)

    for line in response.splitlines():
        if line.lower().startswith("location:"):
            locations.add(line.split(":", 1)[1].strip())

sock.close()

for url in sorted(locations):
    print(f"\nDevice description: {url}")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            print(r.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        print(f"Could not retrieve description: {exc}")

if not locations:
    print("No UPnP description found.")