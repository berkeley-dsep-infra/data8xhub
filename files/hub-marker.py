from ltiauthenticator import LTIAuthenticator
from dummyauthenticator import DummyAuthenticator
from tornado import gen
import os

class CustomAuthenticator(DummyAuthenticator):
    @gen.coroutine
    def authenticate(self, handler, data=None):
        ret = (yield super().authenticate(handler, data))
        handler.set_cookie('hub', os.environ['HUB_NAME'])
        handler.set_cookie('cluster', os.environ['CLUSTER_NAME'])
        if isinstance(ret, str):
            username = ret
        else:
            username = ret['name']
        handler.set_cookie('username', username)
        return ret

c.JupyterHub.authenticator_class = CustomAuthenticator

c.JupyterHub.tornado_settings = {
    'slow_spawn_timeout': 1,
}