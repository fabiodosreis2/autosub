# CMD LINE: tor -f torrc
# IF HAS A TOR SERVICE RUNNING: service tor stop
import os
import socks  # PySocks
import socket
import requests
import tempfile
from datetime import datetime
from stem import Signal
from stem.control import Controller


class IPChanger:
    def __init__(self, socks_port=9050, control_port=9051):
        self.__controller = None
        self.__socks_port = socks_port
        self.__control_port = control_port

    def __del__(self):
        if self.__controller is not None:
            del self.__controller
            socks.set_default_proxy()

    def do(self):
        try:
            if self.__controller is not None:
                del self.__controller
                socks.set_default_proxy()
            self.__controller = Controller.from_port(port=self.__control_port)
            self.__controller.authenticate(password="b32SD!@q sjfg 324#$ 324fasd3242$")
            self.__controller.signal(Signal.NEWNYM)
            socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", self.__socks_port)
            socket.socket = socks.socksocket
            print("Current IP address: {}".format(requests.get("http://api.ipify.org").text))
        except:
            print("Change IP exception")
            pass

    @staticmethod
    def call_tor(socks_port=9050, control_port=9051, bootstrap_timeout=240):
        temp_dir = tempfile.TemporaryDirectory().name
        p = os.popen(
            'tor SocksPort {} ControlPort {} DataDirectory {}'
            ' HashedControlPassword 16:C09D6F7E83C7856D606455D0285F394DAAEF95AE4B1F474F47171704EE'.format(
                socks_port, control_port, temp_dir), 'r')
        first_time = datetime.now()
        while True:
            line = p.readline()
            print(line)
            if not line:
                return False
            if 'bootstrapped 100%: done' in line.lower() or 'is tor already running?' in line.lower():
                return True
            delta = datetime.now() - first_time
            if delta.seconds > bootstrap_timeout:
                p.close()
                return False


def call_tors(instance_count, retires=3):
    ports_list = []
    for i in range(instance_count):
        for j in range(retires):
            socks_port = choice(range(9000, 15000))
            control_port = socks_port + 1
            if IPChanger(socks_port, control_port).call_tor(socks_port, control_port):
                ports_list.append((socks_port, control_port))
                break
    return ports_list


if __name__ == '__main__':
    from random import choice

    print(call_tors(5))
    while True:
        pass
        # ip_changer.do()
        # ip_changer.do()
