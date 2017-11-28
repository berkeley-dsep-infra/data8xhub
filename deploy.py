#!/usr/bin/env python3
"""
Deploy script for entire MOOC's JupyterHub

Every function must be idempotent, calling multiple times should work A-OK
"""
import glob
import os
import time
import click
import logging
import tempfile
import subprocess
import glob
from jinja2 import Environment, FileSystemLoader
from ruamel.yaml import YAML


yaml = YAML()

def render_template(name, data):
    template_env = Environment(
        loader=FileSystemLoader('templates')
    )

    return template_env.get_template(name).render(data)


def get_data(deployment):
    with open('config.yaml') as f:
        config = yaml.load(f)
    files = {}
    for filename in glob.glob('files/*'):
        if not os.path.basename(filename).startswith('.'):
            with open(filename) as f:
                files[os.path.basename(filename)] = f.read()

    return {
        'config': config,
        'files': files,
        'deployment': deployment
    }

def gcloud(*args):
    logging.info("Executing gcloud", ' '.join(args))
    return subprocess.check_call(['gcloud', '--quiet'] + list(args))

def helm(*args, **kwargs):
    logging.info("Executing helm", ' '.join(args))
    return subprocess.check_call(['helm'] + list(args), **kwargs)

def kubectl(*args, **kwargs):
    logging.info("Executing kubectl", ' '.join(args))
    return subprocess.check_call(['kubectl'] + list(args), **kwargs)

def use_cluster(deployment, cluster, zone):
    cluster_name = '{}-cluster-{}'.format(deployment, cluster)
    gcloud('container', 'clusters', 'get-credentials', cluster_name, '--zone', zone)

@click.group()
def cli():
    pass

@cli.command()
@click.option('--deployment', default='hubs', help='Name of deployment to use')
@click.option('--create', default=False, help='Create deployment rather than update it', is_flag=True)
@click.option('--dry-run', default=False, help='Do not actually run commands, just do a dry run', is_flag=True)
@click.option('--debug', default=False, help='Print out debug info', is_flag=True)
def gdm(deployment, create, dry_run, debug):
    data = get_data(deployment)
    gdm = render_template('gdm.yaml', data)
    if debug:
        logging.info(gdm)
    with tempfile.NamedTemporaryFile(delete=(not debug)) as out:
        out.write(gdm.encode())
        out.flush()

        args = [
            'deployment-manager',
            'deployments',
            'create' if create else 'update',
            deployment,
            '--config', out.name
        ]

        if dry_run:
            args.append('--preview')
        gcloud(*args)


@cli.command()
@click.option('--deployment', default='hubs', help='Name of deployment to use')
def cluster_up(deployment):
    data = get_data(deployment)

    for cluster in data['config']['clusters']:
        use_cluster(deployment, cluster['name'], cluster['zone'])

        # Get Helm RBAC set up!
        helm_rbac = render_template('helm-rbac.yaml', data)
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=helm_rbac.encode(), check=True)

        # Initialize Helm!
        subprocess.run(['helm', 'init', '--service-account', 'tiller', '--upgrade'], check=True)
        # wait for tiller to be up
        kubectl('rollout', 'status', '--watch', 'deployment/tiller-deploy', '--namespace=kube-system')

        # Install cluster-wide charts
        helm('dep', 'up', cwd='cluster-support')
        helm(
            'upgrade',
            '--install',
            '--wait',
            'cluster-support',
            '--namespace', 'cluster-support',
            'cluster-support'
        )

@cli.command()
@click.option('--deployment', default='hubs', help='Name of deployment to use')
def deploy(deployment):
    data = get_data(deployment)
    helm('repo', 'add', 'jupyterhub', 'https://jupyterhub.github.io/helm-chart')

    for cluster in data['config']['clusters']:
        use_cluster(deployment, cluster['name'], cluster['zone'])

        helm('dep', 'up', cwd='hub')

        for hub in cluster['hubs']:
            hub_name = 'hub-{}'.format(hub['name'])
            with tempfile.NamedTemporaryFile() as out:
                values = render_template('values.yaml', get_data(deployment))
                out.write(values.encode())
                out.flush()

                helm(
                    'upgrade',
                    '--install',
                    '--wait',
                    hub_name,
                    '--namespace', hub_name,
                    'hub',
                    '-f', out.name
                )

@cli.command()
@click.option('--deployment', default='hubs', help='Name of deployment to use')
def teardown(deployment):
    data = get_data(deployment)

    for cluster in data['config']['clusters']:
        use_cluster(deployment, cluster['name'], cluster['zone'])

        for hub in cluster['hubs']:
            hub_name = 'hub-{}'.format(hub['name'])
            try:
                helm('delete', '--purge', hub_name)
            except subprocess.CalledProcessError:
                print("Helm Release {} already deleted".format(hub_name))
            try:
                kubectl('delete', 'namespace', hub_name)
            except subprocess.CalledProcessError:
                print("Namespace {} already deleted".format(hub_name))
            for i in range(16):
                try:
                    kubectl('get', 'namespace', hub_name)
                    print("Waiting for namespace {} to delete...".format(hub_name))
                    time.sleep(2**i)
                except subprocess.CalledProcessError:
                    # Successfully deleted!
                    break



    gcloud('deployment-manager', 'deployments', 'delete', deployment)


if __name__ == '__main__':
    cli()
