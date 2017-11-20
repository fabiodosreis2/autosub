from tor_ip_changer import IPChanger
from requests import get

ports = [(12277, 12278), (12103, 12104), (10432, 10433)]

p = [(10749, 10750), (9502, 9503), (11378, 11379)]

c = IPChanger(10749, 10750)
c.do()
print(get("http://api.ipify.org").text)
print(get("http://api.ipify.org").text)