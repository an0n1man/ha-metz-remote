from metzctl import MetzRemote
import time

tv = MetzRemote("192.168.1.131")

for code in [49, 24, 24, 39, 39]:
    tv.control(code)
    time.sleep(0.65)