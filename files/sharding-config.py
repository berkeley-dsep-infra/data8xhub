from kubespawner import KubeSpawner
import escapism
import os
import yaml

def get_config(key, default=None):
    """
    Find a config item of a given name & return it

    Parses everything as YAML, so lists and dicts are available too
    """
    path = os.path.join('/etc/jupyterhub/config', key)
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
            return data
    except FileNotFoundError:
        return default

def setup_homedir_sharding():
    # Inside a function to prevent scopes from leaking

    engine = sqlalchemy.create_engine('sqlite:///sharding.sqlite')

    config = get_config('custom.full-config')
    deployment = get_config('custom.deployment')
    nfs_server_template = '{deployment}-nfs-vm-{name}'
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
                'flexVolume': {
                    'driver': 'yuvi.in/nfs-flex-volume',
                    'options': {
                        'share': '{}:/export/pool0/homes'.format(nfsserver),
                        'mountOptions': 'rw,soft',
                        'subPath': escapism.escape(self.user.name),
                        'createIfNecessary': 'true',
                        'createMode': '0755'
                    }
                }
            }]
            self.volume_mounts = [{
                'name': 'home',
                'mountPath': '/home/jovyan'
            }]
            return super().start()

    c.JupyterHub.spawner_class = CustomSpawner

setup_homedir_sharding()
