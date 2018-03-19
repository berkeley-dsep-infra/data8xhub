from kubespawner import KubeSpawner
import escapism
import os
import yaml
import z2jh
from tornado import gen, concurrent, log
from concurrent.futures import ThreadPoolExecutor

def setup_homedir_sharding():
    # Inside a function to prevent scopes from leaking

    username = os.environ['SHARDER_DB_USERNAME']
    password = os.environ['SHARDER_DB_PASSWORD']
    dbname = os.environ['SHARDER_DB_NAME']

    config = z2jh.get_config('custom.full-config')
    deployment = z2jh.get_config('custom.deployment')
    nfs_server_template = '{deployment}-{name}'
    fileservers = [
        nfs_server_template.format(deployment=deployment, name=name)
        for name in config['fileservers']
    ]
    sharder = Sharder('localhost', username, password, dbname, 'homedir', fileservers, log.app_log)


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
            return (yield super().start())

    c.JupyterHub.spawner_class = CustomSpawner


setup_homedir_sharding()
