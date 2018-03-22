from ltiauthenticator import LTIAuthenticator
from dummyauthenticator import DummyAuthenticator
from tornado import gen
import os

class CustomAuthenticator(LTIAuthenticator):
    @gen.coroutine
    def authenticate(self, handler, data=None):
        ret = (yield super().authenticate(handler, data))
        handler.set_cookie('hub', os.environ['HUB_NAME'], httponly=True)
        handler.set_cookie('cluster', os.environ['CLUSTER_NAME'], httponly=True)
        return ret

c.JupyterHub.authenticator_class = CustomAuthenticator

c.JupyterHub.tornado_settings = {
    'slow_spawn_timeout': 1,
}