"""
Deploy script for entire MOOC's JupyterHub

Every function must be idempotent, calling multiple times should work A-OK
"""
import glob
import os
import click
import logging
import tempfile
import subprocess
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
        data = yaml.load(f)
    data['deployment'] = deployment
    return data

def gcloud(*args):
    logging.info("Executing gcloud", ' '.join(args))
    return subprocess.check_call(['gcloud'] + list(args))

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

    for cluster in data['clusters']:
        # Get credentials
        cluster_name = '{}-cluster-{}'.format(deployment, cluster['name'])
        gcloud('container', 'clusters', 'get-credentials', cluster_name, '--zone', cluster['zone'])

        # Get Helm RBAC set up!
        helm_rbac = render_template('helm-rbac.yaml', data)
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=helm_rbac.encode(), check=True)

        # Initialize Helm!
        subprocess.run(['helm', 'init', '--service-account', 'tiller', '--upgrade'], check=True)
        # wait for tiller to be up
        subprocess.run(['kubectl', 'rollout', 'status', '--watch', 'deployment/tiller-deploy', '--namespace=kube-system'], check=True)

        # Install cluster-wide charts
        subprocess.run(['helm', 'dep', 'up'], cwd='cluster-support')
        subprocess.run([
            'helm', 'upgrade',
            '--install',
            '--wait',
            'cluster-support',
            '--namespace', 'cluster-support',
            'cluster-support'
        ])

if __name__ == '__main__':
    cli()
