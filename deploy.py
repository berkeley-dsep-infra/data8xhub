#!/usr/bin/env python3
"""
Deploy script for entire MOOC's JupyterHub

Every function must be idempotent, calling multiple times should work A-OK
"""
import glob
import os
import time
import argparse
import logging
import tempfile
import subprocess
import json
import glob
from jinja2 import Environment, FileSystemLoader
from ruamel.yaml import YAML


yaml = YAML()

def render_template(name, data):
    template_env = Environment(
        loader=FileSystemLoader('templates')
    )
    template_env.filters['jsonify'] = json.dumps

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
    cluster_name = '{}-{}'.format(deployment, cluster)
    gcloud('container', 'clusters', 'get-credentials', cluster_name, '--zone', zone)


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


def init_support(deployment, dry_run, debug):
    data = get_data(deployment)

    for name, cluster in data['config']['clusters'].items():
        use_cluster(deployment, name, cluster['zone'])

        # Get Helm RBAC set up!
        helm_rbac = render_template('helm-rbac.yaml', data)
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=helm_rbac.encode(), check=True)

        # Initialize Helm!
        subprocess.run(['helm', 'init', '--service-account', 'tiller', '--upgrade'], check=True)
        # wait for tiller to be up
        kubectl('rollout', 'status', '--watch', 'deployment/tiller-deploy', '--namespace=kube-system')

        # Install cluster-wide charts
        helm('dep', 'up', cwd='cluster-support')
        install_cmd = [
            'upgrade',
            '--install',
            '--wait',
            'cluster-support',
            '--namespace', 'cluster-support',
            'cluster-support'
        ]
        if debug:
            install_cmd.append('--debug')
        if dry_run:
            install_cmd.append('--dry-run')
        helm(*install_cmd)

def deploy(deployment, dry_run, debug):
    data = get_data(deployment)
    helm('repo', 'add', 'jupyterhub', 'https://jupyterhub.github.io/helm-chart')

    for name, cluster in data['config']['clusters'].items():
        use_cluster(deployment, name, cluster['zone'])

        helm('dep', 'up', cwd='hub')

        for name, hub in cluster['hubs'].items():
            with tempfile.NamedTemporaryFile() as values, tempfile.NamedTemporaryFile() as secrets, tempfile.NamedTemporaryFile() as hub_secrets:
                template_data = get_data(deployment)
                template_data['hub'] = hub
                template_data['name'] = name

                values.write(render_template('values.yaml', template_data).encode())
                values.flush()

                secrets.write(render_template('secrets/common.yaml', template_data).encode())
                secrets.flush()

                hub_secrets.write(render_template('secrets/{}.yaml'.format(name), template_data).encode())
                hub_secrets.flush()

                install_cmd = [
                    'upgrade',
                    '--install',
                    '--wait',
                    '--debug',
                    name,
                    '--namespace', name,
                    'hub',
                    '-f', values.name,
                    '-f', secrets.name,
                    '-f', hub_secrets.name
                ]
                if dry_run:
                    install_cmd.append('--dry-run')
                if debug:
                    install_cmd.append('--debug')
                helm(*install_cmd)

def teardown(deployment):
    data = get_data(deployment)

    for cluster_name, cluster in data['config']['clusters'].items():
        use_cluster(deployment, cluster_name, cluster['zone'])

        for name in cluster['hubs']:
            try:
                helm('delete', '--purge', name)
            except subprocess.CalledProcessError:
                print("Helm Release {} already deleted".format(name))
            try:
                kubectl('delete', 'namespace', name)
            except subprocess.CalledProcessError:
                print("Namespace {} already deleted".format(name))
            for i in range(16):
                try:
                    kubectl('get', 'namespace', name)
                    print("Waiting for namespace {} to delete...".format(name))
                    time.sleep(2**i)
                except subprocess.CalledProcessError:
                    # Successfully deleted!
                    break



    gcloud('deployment-manager', 'deployments', 'delete', deployment)


def main():
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        '--deployment',
        help='Name of deployment to run commands against'
    )
    argparser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help='Turn on debug level logging'
    )

    argparser.add_argument(
        '--dry-run',
        action='store_true',
        default=False,
        help='Do not execute action'
    )

    subparsers = argparser.add_subparsers(
        help='Actions to perform',
        dest='action'
    )

    gdm_parser = subparsers.add_parser(
        'gdm',
        help='Deploy GDM related changes'
    )
    gdm_parser.add_argument('--create', action='store_true', default=False)

    subparsers.add_parser(
        'init_support',
        help='Set up support packages for the cluster'
    )

    subparsers.add_parser(
        'deploy',
        help='Deploy changes to the hub chart'
    )

    subparsers.add_parser(
        'teardown',
        help='Tear everything down!'
    )

    args = argparser.parse_args()

    print(args)
    if args.action == 'gdm':
        gdm(args.deployment, args.create, args.dry_run, args.debug)
    elif args.action == 'init_support':
        init_support(args.deployment, args.dry_run, args.debug)
    elif args.action == 'deploy':
        deploy(args.deployment, args.dry_run, args.debug)
    elif args.action == 'teardown':
        teardown(args.deployment)



if __name__ == '__main__':
    main()
