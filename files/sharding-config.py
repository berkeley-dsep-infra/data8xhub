from kubespawner import KubeSpawner
import escapism
import os
import yaml
import z2jh
from tornado import gen, concurrent, log
from concurrent.futures import ThreadPoolExecutor
import socket

def setup_homedir_sharding():
    # Inside a function to prevent scopes from leaking

    username = os.environ['SHARDER_DB_USERNAME']
    password = os.environ['SHARDER_DB_PASSWORD']
    dbname = os.environ['SHARDER_DB_NAME']

    deployment = z2jh.get_config('custom.deployment')
    nfs_server_template = '{deployment}-{name}'
    fileservers = [
        nfs_server_template.format(deployment=deployment, name=name)
        for name in yaml.safe_load(z2jh.get_config('custom.fileservers'))
    ]
    sharder = Sharder('localhost', username, password, dbname, 'homedir', fileservers, log.app_log)

    allowed_external_hosts = z2jh.get_config('custom.allowed-external-hosts')


    class CustomSpawner(KubeSpawner):
        _sharder_thread_pool = ThreadPoolExecutor(max_workers=1)

        @concurrent.run_on_executor(executor='_sharder_thread_pool')
        def shard(self, username):
            if hasattr(self, '_fileserver_shard'):
                return self._fileserver_shard

            self._fileserver_shard = sharder.shard(username)
            return self._fileserver_shard

        @gen.coroutine
        def start(self):
            nfsserver = yield self.shard(self.user.name)
            self.volumes = [{
                'name': 'home',
                'hostPath': {
                    'path': '/mnt/fileservers/{fileserver}/{username}'.format(
                        fileserver=nfsserver,
                        username=escapism.escape(self.user.name)
                    )
                }
            }]
            self.volume_mounts = [{
                'name': 'home',
                'mountPath': '/home/jovyan'
            }]

            if self.user.admin:
                self.volumes.append({
                    'name': 'fileservers',
                    'hostPath': {
                        'path': '/mnt/fileservers'
                    }
                })
                self.volume_mounts.append({
                    'name': 'fileservers',
                    'mountPath': '/home/jovyan/fileservers'
                })

            self.singleuser_extra_pod_config = {
                'hostAliases': [
                    {
                        'ip': socket.gethostbyname('egress-proxy'),
                        'hostnames': allowed_external_hosts
                    }
                ]

            }
            return (yield super().start())

    c.JupyterHub.spawner_class = CustomSpawner


setup_homedir_sharding()
