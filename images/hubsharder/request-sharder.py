#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
import json
from ruamel.yaml import YAML

import os
from tornado import httpserver, ioloop, web, gen, log, concurrent, httpclient, httputil

from ltivalidator import LTILaunchValidator, LTILaunchValidationError
from sharder import Sharder


class ShardHandler(web.RequestHandler):
    _sharder_thread_pool = ThreadPoolExecutor(max_workers=1)

    @concurrent.run_on_executor(executor='_sharder_thread_pool')
    def shard(self, username):
        return self.settings['sharder'].shard(username)

    @gen.coroutine
    def proxy_post(self, path, cluster_ip, hub):
        body = self.request.body
        client_url = f'http://{cluster_ip}{path}'

        client = httpclient.AsyncHTTPClient()

        headers = {
            'Cookie': f'hub={hub}',
            'User-Agent': 'HubSharder',
            'Host': self.request.host
        }
        req = httpclient.HTTPRequest(
            client_url, method='POST', body=body,
            headers=headers, follow_redirects=False
        )

        response = yield client.fetch(req, raise_error=False)

        if response.error and type(response.error) is not httpclient.HTTPError:
            self.set_status(500)
            self.write(str(response.error))
        else:
            self.set_status(response.code, response.reason)

            # clear tornado default header
            self._headers = httputil.HTTPHeaders()

            for header, v in response.headers.get_all():
                if header not in ('Content-Length', 'Transfer-Encoding',
                    'Content-Encoding', 'Connection'):
                    # some header appear multiple times, eg 'Set-Cookie'
                    self.add_header(header, v)


            if response.body:
                self.write(response.body)


    @gen.coroutine
    def post(self):
        validator = LTILaunchValidator(self.settings['consumers'])

        args = {}
        for k, values in self.request.body_arguments.items():
            args[k] = values[0].decode() if len(values) == 1 else [v.decode() for v in values]

        username = self.get_body_argument('user_id')
        try:
            if validator.validate_launch_request(
                    self.request.full_url(),
                    self.request.headers,
                    args
            ):
                log.app_log.info(f'Validated LTI request for user {username}')
                # Should be pushed into a db later
                auth_state = {k: v for k, v in args.items() if not k.startswith('oauth_')}
        except LTILaunchValidationError as e:
            log.app_log.error(f'LTI Validation failed for user {username}')
            raise web.HTTPError(401, e.message + self.request.full_url() + self.request.body.decode())

        shard_info = json.loads((yield self.shard(username)))

        #self.set_cookie('hub', shard_info['hub'], httponly=True)
        #self.set_cookie('cluster', shard_info['cluster'], httponly=True)

        yield self.proxy_post(self.request.path, shard_info['ip'], shard_info['hub'])


def main():
    log.enable_pretty_logging()

    username = os.environ['SHARDER_DB_USERNAME']
    password = os.environ['SHARDER_DB_PASSWORD']
    dbname = os.environ['SHARDER_DB_NAME']
    consumers = {os.environ['LTI_KEY']: os.environ['LTI_SECRET']}
    # Stringify each line so we can use it as keys
    sharder_buckets = [l for l in json.loads(os.environ['SHARDER_BUCKETS']).split('\n') if l.strip()]
    sharder = Sharder('localhost', username, password, dbname, 'hub', sharder_buckets, log.app_log)
    application = web.Application([
        (r"/hub/lti/launch", ShardHandler),
    ], sharder=sharder, consumers=consumers, debug=True)
    http_server = httpserver.HTTPServer(application)
    http_server.listen(8888)
    ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
