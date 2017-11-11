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


def get_data():
    with open('config.yaml') as f:
        return yaml.load(f)

def gcloud(*args):
    logging.info("Executing gcloud", ' '.join(args))
    return subprocess.check_call(['gcloud'] + list(args))

@click.command()
@click.option('--deployment', default='hubs', help='Name of deployment to use')
@click.option('--create', default=False, help='Create deployment rather than update it', is_flag=True)
@click.option('--dry-run', default=False, help='Do not actually run commands, just do a dry run', is_flag=True)
@click.option('--debug', default=False, help='Print out debug info', is_flag=True)
def gdm(deployment, create, dry_run, debug):
    data = get_data()
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


if __name__ == '__main__':
    gdm()
