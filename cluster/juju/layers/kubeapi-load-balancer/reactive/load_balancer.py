import os
import socket
import subprocess

from charms import layer
from charms.reactive import when
from charmhelpers.core import hookenv

from charms.layer import nginx

from subprocess import Popen
from subprocess import PIPE
from subprocess import STDOUT


@when('certificates.available')
def request_server_certificates(tls):
    '''Send the data that is required to create a server certificate for
    this server.'''
    # Use the public ip of this unit as the Common Name for the certificate.
    common_name = hookenv.unit_public_ip()
    # Create SANs that the tls layer will add to the server cert.
    sans = [
        hookenv.unit_public_ip(),
        hookenv.unit_private_ip(),
        socket.gethostname(),
    ]
    # Create a path safe name by removing path characters from the unit name.
    certificate_name = hookenv.local_unit().replace('/', '_')
    # Request a server cert with this information.
    tls.request_server_cert(common_name, sans, certificate_name)


@when('nginx.available', 'apiserver.available',
      'certificates.server.cert.available')
def install_load_balancer(apiserver, tls):
    ''' Create the default vhost template for load balancing '''
    # Get the tls paths from the layer data.
    layer_options = layer.options('tls-client')
    server_cert_path = layer_options.get('server_certificate_path')
    cert_exists = server_cert_path and os.path.isfile(server_cert_path)
    server_key_path = layer_options.get('server_key_path')
    key_exists = server_key_path and os.path.isfile(server_key_path)
    # Do both the the key and certificate exist?
    if cert_exists and key_exists:
        # At this point the cert and key exist, and they are owned by root.
        chown = ['chown', 'www-data:www-data', server_cert_path]
        # Change the owner to www-data so the nginx process can read the cert.
        subprocess.call(chown)
        chown = ['chown', 'www-data:www-data', server_key_path]
        # Change the owner to www-data so the nginx process can read the key.
        subprocess.call(chown)

        hookenv.open_port(hookenv.config('port'))
        services = apiserver.services()
        nginx.configure_site(
                'apilb',
                'apilb.conf',
                server_name='_',
                services=services,
                port=hookenv.config('port'),
                server_certificate=server_cert_path,
                server_key=server_key_path,
        )
        hookenv.status_set('active', 'Loadbalancer ready.')


@when('nginx.available')
def set_nginx_version():
    ''' Surface the currently deployed version of nginx to Juju '''
    cmd = 'nginx -v'
    p = Popen(cmd, shell=True,
              stdin=PIPE,
              stdout=PIPE,
              stderr=STDOUT,
              close_fds=True)
    raw = p.stdout.read()
    # The version comes back as:
    # nginx version: nginx/1.10.0 (Ubuntu)
    version = raw.split(b'/')[-1].split(b' ')[0]
    hookenv.application_version_set(version.rstrip())


@when('website.available')
def provide_application_details(website):
    ''' re-use the nginx layer website relation to relay the hostname/port
    to any consuming kubernetes-workers, or other units that require the
    kubernetes API '''
    website.configure(port=hookenv.config('port'))


@when('loadbalancer.available')
def provide_loadbalancing(loadbalancer):
    '''Send the public address and port to the public-address interface, so
    the subordinates can get the public address of this loadbalancer.'''
    loadbalancer.set_address_port(hookenv.unit_get('public-address'),
                                  hookenv.config('port'))