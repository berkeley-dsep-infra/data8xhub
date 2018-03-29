#!/usr/bin/env python3
import os
import sys
import base64
import json
from jinja2 import Environment, FileSystemLoader
from tornado import httpserver, ioloop, web, log
from ltivalidator import LTILaunchValidator, LTILaunchValidationError


class HomeWorkHandler(web.RequestHandler):
    def render_template(self, name, **extra_ns):
        """Render an HTML page"""
        ns = {
            'static_url': self.static_url,
        }
        ns.update(extra_ns)
        template = self.settings['jinja2_env'].get_template(name)
        html = template.render(**ns)
        self.write(html)

    def finish_upload(self, hw):
        signed_launch_args = self.get_argument('signed-launch-args')

        launch_args = json.loads(web.decode_signed_value(
            self.settings['cookie_secret'],
            'launch-args',
            signed_launch_args
        ).decode('utf-8'))

        target_dir = os.path.join(self.settings['upload_base_dir'], hw)
        # Protect ourselves from path traversal attacks
        # NOTE: This is why it is important that upload_base_dir ends with a /
        if not target_dir.startswith(self.settings['upload_base_dir']):
            raise web.HTTPError(400, 'Invalid homework name')

        os.makedirs(target_dir, exist_ok=True)

        sourced_id = launch_args['lis_result_sourcedid']
        target_path = os.path.join(target_dir, sourced_id)
        if not target_path.startswith(target_dir):
            raise web.HTTPError(400, 'Invalid launch_args')

        if len(self.request.files) != 1:
            raise web.HTTPError(400, 'Only one file can be uploaded at a time')

        uploaded_file = list(self.request.files.values())[0][0]

        try:
            file_contents = uploaded_file.body.decode('utf-8')
        except UnicodeDecodeError:
            raise web.HTTPError(400, 'Could not decode uploaded file as UTF-8')

        # Explicitly just write these as binary files, so we don't fudge with encoding here.
        with open(target_path, 'w') as f:
            f.write(json.dumps(launch_args) + '\n')
            f.write(file_contents)

        log.app_log.info('Saved file {target_path} for launch {launch_info}'.format(target_path=target_path, launch_info=json.dumps(launch_args)))

        self.write(f"Done!")

    def post(self, hw):
        if self.request.files:
            return self.finish_upload(hw)
        else:
            consumers = self.settings['consumers']
            validator = LTILaunchValidator(consumers)

            args = {}
            for k, values in self.request.body_arguments.items():
                # Convert everything to strings rather than bytes
                args[k] = values[0].decode() if len(values) == 1 else [v.decode() for v in values]


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
                    user_id = self.get_body_argument('user_id')
                    log.app_log.info(f'{user_id} successfully logged in')
            except LTILaunchValidationError as e:
                raise web.HTTPError(401, e.message)

            launch_args = {}
            for k, values in self.request.body_arguments.items():
                launch_args[k] = values[0].decode() if len(values) == 1 else [v.decode() for v in values]

            signed_launch_args = self.create_signed_value('launch-args', json.dumps(launch_args)).decode('utf-8')
            self.render_template('main.html', signed_launch_args=signed_launch_args)

def main():
    log.enable_pretty_logging()
    if 'COOKIE_SECRET' not in os.environ:
        log.app_log.error('Set a 32byte hex-encoded value as COOKIE_SECRET environment variable first!')
        sys.exit(1)

    if 'UPLOAD_BASE_DIR' not in os.environ:
        log.app_log.error('Provide dir to store uploaded files in as UPLOAD_BASE_DIR (with trailing slash!) environment variable')
        sys.exit(1)

    if not os.environ['UPLOAD_BASE_DIR'].endswith('/'):
        log.app_log.error('UPLOAD_BASE_DIR must end with a trailing /')
        sys.exit(1)

    consumers = {os.environ['LTI_KEY']: os.environ['LTI_SECRET']}

    jinja2_env = Environment(loader=FileSystemLoader([os.path.dirname(__file__)]), autoescape=True)

    settings = {
        'jinja2_env': jinja2_env,
        'cookie_secret': os.environ['COOKIE_SECRET'],
        'consumers': consumers,
        'upload_base_dir': os.environ['UPLOAD_BASE_DIR']
    }

    application = web.Application([
        (r"/hwuploader/(\w+)", HomeWorkHandler),
    ], **settings)

    http_server = httpserver.HTTPServer(application)
    http_server.listen(8888)
    ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()