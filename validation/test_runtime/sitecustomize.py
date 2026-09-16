"""Injected only through the isolated acceptance test PYTHONPATH."""
import os
import socket
if os.environ.get('PQM_TEST_NETWORK_ISOLATION') == '1':
    # HTTPServer calls getfqdn before listening. Tests need no external reverse DNS.
    socket.getfqdn = lambda name='': name or 'localhost'
    original_connect=socket.socket.connect
    def loopback_only(sock,address):
        if isinstance(address,tuple) and address[0] not in {'127.0.0.1','localhost','::1'}:
            raise RuntimeError('Outbound network forbidden in WEB acceptance')
        return original_connect(sock,address)
    socket.socket.connect=loopback_only
