from kubespawner import KubeSpawner
import escapism
import os
import yaml
import z2jh

def setup_homedir_sharding():
    # Inside a function to prevent scopes from leaking

    username = os.environ['SHARDER_DB_USERNAME']
    password = os.environ['SHARDER_DB_PASSWORD']
    dbname = os.environ['SHARDER_DB_NAME']
    engine = sqlalchemy.create_engine(f'postgres+psycopg2://{username}:{password}@localhost:5432/{dbname}')

    config = z2jh.get_config('custom.full-config')
    deployment = z2jh.get_config('custom.deployment')
    nfs_server_template = '{deployment}-{name}'
    fileservers = [
        nfs_server_template.format(deployment=deployment, name=name)
        for name in config['fileservers']
    ]
    sharder = Sharder(engine, 'homedir', fileservers)

    class CustomSpawner(KubeSpawner):
        def start(self):
            nfsserver = sharder.shard(self.user.name)
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
            return super().start()

    c.JupyterHub.spawner_class = CustomSpawner

setup_homedir_sharding()
