#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
import json
from ruamel.yaml import YAML

import os
from tornado import httpserver, ioloop, web, gen, log, concurrent, httpclient, httputil
import psycopg2
import psycopg2.extras

from ltivalidator import LTILaunchValidator, LTILaunchValidationError
from sharder import Sharder
from tornado.httpclient import AsyncHTTPClient

# Configure JupyterHub to use the curl backend for making HTTP requests,
# rather than the pure-python implementations. The default one starts
# being too slow to make a large number of requests to the proxy API
# at the rate required.
AsyncHTTPClient.configure("tornado.curl_httpclient.CurlAsyncHTTPClient")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lti_launch_info_v1 (
    id                  SERIAL NOT NULL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    resource_link_id    TEXT NOT NULL,
    launch_info         JSONB NOT NULL,
    UNIQUE (user_id, resource_link_id)
);
CREATE INDEX IF NOT EXISTS user_id_resource_link_id_lti_launch_info_v1 ON lti_launch_info_v1 (
    user_id, resource_link_id
)
"""

class ShardHandler(web.RequestHandler):
    _sharder_thread_pool = ThreadPoolExecutor(max_workers=1)

    @concurrent.run_on_executor(executor='_sharder_thread_pool')
    def shard(self, username):
        return self.settings['sharder'].shard(username)

    _lti_saver_thread_pool = ThreadPoolExecutor(max_workers=1)

    @concurrent.run_on_executor(executor='_lti_saver_thread_pool')
    def save_lti_info(self, lti_info):
        user_id = lti_info['user_id']
        resource_link_id = lti_info['resource_link_id']

        with self.settings['dbpool'].getconn() as conn:
            try:
                with conn.cursor() as cur:
                    # Make sure that we have at least one dummy entry for each fileserver
                    cur.execute("""
                    INSERT INTO lti_launch_info_v1 (user_id, resource_link_id, launch_info)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, resource_link_id)
                    DO
                        UPDATE SET launch_info=%s
                    """, (user_id, resource_link_id, psycopg2.extras.Json(lti_info), psycopg2.extras.Json(lti_info)))
                    conn.commit()
                    log.app_log.info(f'Saved lti launch info for user:{user_id} resource_link_id:{resource_link_id}')
            finally:
                self.settings['dbpool'].putconn(conn)


    @gen.coroutine
    def proxy_post(self, path, cluster_ip, hub):
        body = self.request.body
        client_url = f'http://{cluster_ip}{path}'

        client = httpclient.AsyncHTTPClient()

        headers = self.request.headers.copy()
        headers['Cookie'] = f'hub={hub}'
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

        # handle multiple layers of proxied protocol (comma separated) and take the outermost
        if 'x-forwarded-proto' in self.request.headers:
            # x-forwarded-proto might contain comma delimited values
            # left-most value is the one sent by original client
            hops = [h.strip() for h in self.request.headers['x-forwarded-proto'].split(',')]
            protocol = hops[0]
        else:
            protocol = self.request.protocol

        launch_url = protocol + "://" + self.request.host + self.request.uri

        try:
            if validator.validate_launch_request(
                    launch_url,
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

        yield self.save_lti_info(auth_state)

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
    dbpool = psycopg2.pool.ThreadedConnectionPool(1, 4, user=username, host='localhost', password=password, dbname=dbname)

    with dbpool.getconn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA)
                conn.commit()
            log.app_log.info('Finished running schema creation SQL')
        finally:
            dbpool.putconn(conn)

    application = web.Application([
        (r"/hub/lti/launch", ShardHandler),
    ], sharder=sharder, consumers=consumers, debug=True, dbpool=dbpool)
    http_server = httpserver.HTTPServer(application)
    http_server.listen(8888)
    ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
