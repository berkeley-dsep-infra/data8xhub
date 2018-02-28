from ltiauthenticator import LTIAuthenticator
from dummyauthenticator import DummyAuthenticator
from tornado import gen
import os

class CustomAuthenticator(DummyAuthenticator):
    @gen.coroutine
    def authenticate(self, handler, data=None):
        ret = (yield super().authenticate(handler, data))
        handler.set_cookie('hub', os.environ['HUB_NAME'], httponly=True)
        return ret

c.JupyterHub.authenticator_class = CustomAuthenticator