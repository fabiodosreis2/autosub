from sys import stdin
import os
from multiprocessing import Pool, Array, Process, Manager
from ctypes import Structure, POINTER, byref, c_ubyte, c_int, cast, create_string_buffer
import mymodule


class SomeTuple(Structure):
    _fields_ = [
        ('pid', POINTER(c_int)),
        ('port', POINTER(c_int))
    ]


def get_port(pid, arr):
    for st in arr:
        print(st.pid)
        if st.pid == pid:
            return st.port
    return 0


def count_it(key):
    if os.getpid() not in mymodule.toShare:
        if mymodule.toShare_list:
            mymodule.toShare[os.getpid()] = mymodule.toShare_list.pop()
        print('not in')
    else:
        print('in', mymodule.toShare[os.getpid()])
    return key + 1


def initProcess(share, sh_list):
    mymodule.toShare = share
    mymodule.toShare_list = sh_list


if __name__ == '__main__':
    manager = Manager()
    shared_dict = manager.dict()
    shared_list = manager.list([(1, 2), (3, 4)])
    # fork
    pool = Pool(processes=2, initializer=initProcess, initargs=(shared_dict, shared_list))

    for cc in pool.map(count_it, [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3]):
        print(cc)

    print(shared_list)
    print(shared_dict)
