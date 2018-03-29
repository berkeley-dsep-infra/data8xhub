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
import copy
import glob
from jinja2 import Environment, FileSystemLoader
from ruamel.yaml import YAML
from multiprocessing import Pool
from functools import partial

yaml = YAML()

def render_template(name, data):
    template_env = Environment(
        loader=FileSystemLoader('templates')
    )
    template_env.filters['jsonify'] = json.dumps

    return template_env.get_template(name).render(data)

def merge_dictionaries(a, b, path=None, update=True):
    """
    Merge two dictionaries recursively.

    From https://stackoverflow.com/a/25270947
    """
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dictionaries(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass # same leaf value
            elif isinstance(a[key], list) and isinstance(b[key], list):
                for idx, val in enumerate(b[key]):
                    a[key][idx] = merge_dictionaries(a[key][idx],
                                                     b[key][idx],
                                                     path + [str(key), str(idx)],
                                                     update=update)
            elif update:
                a[key] = b[key]
            else:
                raise Exception('Conflict at %s' % '.'.join(path + [str(key)]))
        else:
            a[key] = b[key]
    return a

def get_data(deployment, config_files):
    config = {}
    for config_file in config_files:
        with open(config_file) as f:
            config = merge_dictionaries(config, yaml.load(f))
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

def use_cluster(deployment, cluster, region):
    cluster_name = '{}-{}'.format(deployment, cluster)
    gcloud('beta', 'container', 'clusters', 'get-credentials', cluster_name, '--region', region)


def create_cluster(name, region, node_zone, node_type, initial_nodecount, min_nodecount, max_nodecount, tags):
    gcloud(
        'beta', 'container', 'clusters', 'create',
        '--image-type', 'ubuntu',
        '--machine-type', node_type,
        '--disk-size', '100',
        '--region', region,
        '--node-locations', node_zone,
        '--num-nodes',  str(initial_nodecount),
        '--enable-autoscaling',
        '--min-nodes', str(min_nodecount),
        '--max-nodes', str(max_nodecount),
        '--tags', ','.join(tags),
        '--cluster-version', '1.9.4-gke.1',
        '--disable-addons', 'HttpLoadBalancing,KubernetesDashboard',
        '--enable-network-policy',
        name
    )

def delete_cluster(name, region):
    gcloud(
        'beta', 'container', 'clusters', 'delete',
        '--region', region,
        name
    )

def gdm(deployment, data, create, dry_run, debug):
    gdm = render_template('gdm.yaml', data)
    if debug:
        logging.info(gdm)

    config = data['config']

    cluster_calls = []
    for cluster_name, cluster in config['clusters'].items():
        cluster_calls.append((
            f'{deployment}-{cluster_name}',
            config['region'],
            cluster['zone'],
            cluster['machineType'],
            cluster['initialNodeCount'],
            cluster['initialNodeCount'],
            100,
            [f'deployment-{deployment}', 'role-hub-cluster']
        ))

    try:
        Pool(4).starmap(create_cluster, cluster_calls)
    except Exception as e:
        # This is what passes for idempotency now lol
        print(e)

    try:
        misc_cluster = config['miscCluster']
        create_cluster(
            f'{deployment}-misc',
            config['region'],
            misc_cluster['zone'],
            misc_cluster['machineType'] ,
            misc_cluster['initialNodeCount'],
            misc_cluster['initialNodeCount'],
            50,
            [f'role-misc-cluster']
        )
    except Exception as e:
        print(e)

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


def init_support(deployment, data, dry_run, debug):

    clusters = list(data['config']['clusters'].keys())
    clusters.append('misc')
    for name in clusters:
        use_cluster(deployment, name, data['config']['region'])

        # Get Helm RBAC set up!
        helm_rbac = render_template('helm-rbac.yaml', data)
        subprocess.run(['kubectl', 'apply', '-f', '-'], input=helm_rbac.encode(), check=True)

        # Initialize Helm!
        subprocess.run(['helm', 'init', '--service-account', 'tiller', '--upgrade'], check=True)
        # wait for tiller to be up
        kubectl('rollout', 'status', '--watch', 'deployment/tiller-deploy', '--namespace=kube-system')

        with tempfile.NamedTemporaryFile() as values:
            # Install cluster-wide charts
            template_data = copy.deepcopy(data)
            template_data['cluster_name'] = name

            values.write(render_template('cluster-support.yaml', template_data).encode())
            values.flush()

            helm('dep', 'up', cwd='cluster-support')
            install_cmd = [
                'upgrade',
                '--install',
                '--wait',
                'cluster-support',
                '--namespace', 'cluster-support',
                'cluster-support',
                '-f', values.name
            ]
            if debug:
                install_cmd.append('--debug')
            if dry_run:
                install_cmd.append('--dry-run')
            helm(*install_cmd)

def deploy_hub(deployment, data, dry_run, debug, cluster_name, name, hub):
    with tempfile.NamedTemporaryFile() as values, tempfile.NamedTemporaryFile() as secrets, tempfile.NamedTemporaryFile() as hub_secrets:
        template_data = copy.deepcopy(data)
        template_data['hub'] = hub
        template_data['name'] = name
        template_data['cluster_name'] = cluster_name

        values.write(render_template('values.yaml', template_data).encode())
        values.flush()

        secrets.write(render_template('secrets/common.yaml', template_data).encode())
        secrets.flush()

        if os.path.exists(f'templates/secrets/{name}.yaml'):
            hub_secrets.write(render_template('secrets/{}.yaml'.format(name), template_data).encode())
            hub_secrets.flush()

        install_cmd = [
            'upgrade',
            '--install',
            '--wait',
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

def deploy(deployment, data, dry_run, debug):
    helm('repo', 'add', 'jupyterhub', 'https://jupyterhub.github.io/helm-chart')

    for name, cluster in data['config']['clusters'].items():
        use_cluster(deployment, name, data['config']['region'])

        # deploy the hubs
        helm('dep', 'up', cwd='hub')

        Pool(4).starmap(partial(deploy_hub, deployment, data, dry_run, debug, name), cluster['hubs'].items())

        # Install inner-edge
        helm('dep', 'up', cwd='inner-edge')

        with tempfile.NamedTemporaryFile() as values, tempfile.NamedTemporaryFile() as secrets:
            template_data = copy.deepcopy(data)
            template_data['cluster'] = cluster
            template_data['cluster_name'] = name

            values.write(render_template('inner-edge.yaml', template_data).encode())
            values.flush()

            secrets.write(render_template('secrets/inner-edge.yaml', template_data).encode())
            secrets.flush()

            install_cmd = [
                'upgrade',
                '--install',
                '--wait',
                'inner-edge',
                '--namespace', 'inner-edge',
                'inner-edge',
                '-f', values.name,
                '-f', secrets.name,
            ]
            if dry_run:
                install_cmd.append('--dry-run')
            if debug:
                install_cmd.append('--debug')
            helm(*install_cmd)
            # Add the label required for network-policy to work
            kubectl('label', '--overwrite', 'namespace', 'inner-edge', 'name=inner-edge')

    # Install outer-edge
    helm('dep', 'up', cwd='outer-edge')

    with tempfile.NamedTemporaryFile() as values, tempfile.NamedTemporaryFile() as secrets:
        template_data = copy.deepcopy(data)
        # Dynamically figure out the loadbalancer IPs of the inner-edges of each cluster
        for name, cluster in template_data['config']['clusters'].items():
            use_cluster(deployment, name, data['config']['region'])

            edge_ip = subprocess.check_output([
                'kubectl',
                '--namespace', 'inner-edge',
                'get', 'svc', 'proxy',
                '-o', "jsonpath={.status.loadBalancer.ingress[0].ip}"
            ]).decode().strip()
            cluster['ip'] = edge_ip

        values.write(render_template('outer-edge.yaml', template_data).encode())
        values.flush()

        secrets.write(render_template('secrets/outer-edge.yaml', template_data).encode())
        secrets.flush()

        install_cmd = [
            'upgrade',
            '--install',
            '--wait',
            'outer-edge',
            '--namespace', 'outer-edge',
            'outer-edge',
            '-f', values.name,
            '-f', secrets.name,
        ]
        if dry_run:
            install_cmd.append('--dry-run')
        if debug:
            install_cmd.append('--debug')
        use_cluster(deployment, 'misc', data['config']['region'])
        helm(*install_cmd)



def teardown(deployment, data):
    """
    Tear down the deployment.

    We explicitly delete anything in the k8s cluster that might be holding cloud resources.
    1. PVCs (which hold disks)
    2. Deployments with PVCs attached (so the disks can be released)
    3. Services (which might hold LoadBalancer instances)

    Then we call gdm to delete the whole deployment
    """
    for cluster_name, cluster in data['config']['clusters'].items():
        try:
            use_cluster(deployment, cluster_name, data['config']['region'])
        except:
            continue

        kubectl('--namespace', 'cluster-support', 'delete', 'deployment', '--all', '--now')
        kubectl('--namespace', 'cluster-support', 'delete', 'pvc', '--all', '--now')
        kubectl('--namespace', 'cluster-support', 'delete', 'service', '--all', '--now')
        kubectl('--namespace', 'inner-edge', 'delete', 'service', '--all', '--now')

        for name in cluster['hubs']:
            # Kill deployments so PVCs can be released, then kill PVCs too
            try:
                kubectl('--namespace', name, 'delete', 'deployment', 'hub', '--now')
            except subprocess.CalledProcessError:
                pass
            try:
                kubectl('--namespace', name, 'delete', 'pvc', '--all', '--now')
            except subprocess.CalledProcessError:
                pass

        delete_cluster(f'{deployment}-{cluster_name}', data['config']['region'])

    try:
        use_cluster(deployment, 'misc', data['config']['region'])
        kubectl('--namespace', 'outer-edge', 'delete', 'service', '--all', '--now')
        delete_cluster(f'{deployment}-misc', data['config']['region'])
    except subprocess.CalledProcessError:
        pass

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
    config_files = [f'deployments/{args.deployment}/config.yaml', f'deployments/{args.deployment}/secret.yaml']
    data = get_data(args.deployment, config_files)
    if args.action == 'gdm':
        gdm(args.deployment, data, args.create, args.dry_run, args.debug)
    elif args.action == 'init_support':
        init_support(args.deployment, data, args.dry_run, args.debug)
    elif args.action == 'deploy':
        deploy(args.deployment, data, args.dry_run, args.debug)
    elif args.action == 'teardown':
        teardown(args.deployment, data)



if __name__ == '__main__':
    main()
