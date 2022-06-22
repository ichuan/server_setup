#!/usr/bin/env python
# coding: utf-8
# yc@2016/12/28

from __future__ import unicode_literals

import json
import textwrap
import urllib2
from pkg_resources import parse_version

from fabric import task
from patchwork.files import exists, contains
from distutils.version import LooseVersion as _V

# wget max try
WGET_TRIES = 3
G = {}


def append(c, filepath, text, sudo=True):
    if type(text) is list:
        text = '\n'.join(text)
    text = text.replace('\n', '\\n')
    prefix = 'sudo' if sudo else ''
    cmd = 'echo -e "{}" | {} tee -a {}'.format(text, prefix, filepath)
    return c.run(cmd)


@task
def setup(c, what=''):
    '''
    Fresh setup. Optional arguments: \
    letsencrypt, nodejs, yarn, mysql, mongodb, redis, mariadb, solc, mono, go
    '''
    if what:
        for name in what.split(','):
            func = globals().get('_setup_%s' % name, None)
            if func is None:
                print('No such task: %s' % name)
            else:
                func(c)
        return
    _setup_debian(c)


def _disable_ipv6(c):
    for line in [
        'net.ipv6.conf.all.disable_ipv6 = 1',
        'net.ipv6.conf.default.disable_ipv6 = 1',
        'net.ipv6.conf.lo.disable_ipv6 = 1',
    ]:
        if not contains(c, '/etc/sysctl.conf', line):
            append(c, '/etc/sysctl.conf', line)
    c.sudo('sysctl -p')


@task
def reboot(c):
    '''
    Restart a server.
    '''
    c.sudo('reboot')


def _get_ubuntu_info(c):
    # returns {release, codename, is_64bit}
    if 'sysinfo' not in G:
        G['sysinfo'] = {
            'release': c.run("lsb_release -sr", hide=True).stdout.strip(),
            'codename': c.run("lsb_release -sc", hide=True).stdout.strip(),
            'x64': c.run('test -d /lib64', warn=True, hide=True).ok,
            'dist': c.run(
                "lsb_release -is | tr [:upper:] [:lower:]", hide=True
            ).stdout.strip(),
        }
    return G['sysinfo']


def _setup_aptget(c):
    c.sudo('apt-get update -yq')
    c.sudo(
        'DEBIAN_FRONTEND=noninteractive '
        'apt-get -yq -o Dpkg::Options::="--force-confdef" '
        '-o Dpkg::Options::="--force-confold" upgrade'
    )


def _setup_env(c):
    # dotfiles
    c.run(
        '[ ! -f ~/.tmux.conf ] && { '
        'wget https://github.com/ichuan/dotfiles/releases/latest/download/dotfiles.'
        'tar.gz -O - | tar xzf - && bash dotfiles/bootstrap.sh -f; }',
        warn=True,
    )
    c.run('rm -rf dotfiles ~/Tomorrow_Night_Bright.terminal')
    # UTC timezone
    c.sudo('cp /usr/share/zoneinfo/UTC /etc/localtime', warn=True)
    # limits.conf, max open files
    _limits(c)
    # sysctl.conf
    _sysctl(c)
    # disable ubuntu upgrade check
    c.sudo(
        "sed -i 's/^Prompt.*/Prompt=never/' /etc/update-manager/release-upgrades",
        warn=True,
    )


def _limits(c):
    c.run(
        r'echo -e "*    soft    nofile  500000\n*    hard    nofile  500000'
        r'\nroot soft    nofile  500000\nroot hard    nofile  500000"'
        r' | sudo tee /etc/security/limits.conf'
    )
    # https://underyx.me/2015/05/18/raising-the-maximum-number-of-file-descriptors
    line = 'session required pam_limits.so'
    for p in ('/etc/pam.d/common-session', '/etc/pam.d/common-session-noninteractive'):
        if exists(c, p) and not contains(c, p, line):
            append(c, p, line)
    # "systemd garbage"
    systemd_conf = '/etc/systemd/system.conf'
    if exists(c, systemd_conf):
        c.sudo(
            'sed -i "s/^#DefaultLimitNOFILE=.*/DefaultLimitNOFILE=500000/g" {}'
            ''.format(systemd_conf),
            warn=True,
        )


def _sysctl(c):
    path = '/etc/sysctl.conf'
    for line in (
        'vm.overcommit_memory = 1',
        'net.core.somaxconn = 65535',
        'fs.file-max = 6553560',
    ):
        if not contains(c, path, line):
            append(c, path, line)
    c.sudo('sysctl -p')


def _setup_optional(c):
    _setup_mysql(c)
    _setup_mongodb(c)


def _setup_certbot(c):
    _setup_letsencrypt(c)


def _setup_letsencrypt(c):
    # https://certbot.eff.org/
    bin_name = '/usr/bin/certbot-auto'
    c.sudo(
        'wget https://dl.eff.org/certbot-auto -O %s --tries %s'
        % (bin_name, WGET_TRIES),
        warn=True,
    )
    c.sudo('chmod +x %s' % bin_name)
    path = c.run('echo $PATH', hide=True).stdout
    print('-' * 56)
    print(
        textwrap.dedent(
            '''\
            Usage:
              new: certbot-auto -d example.com -d www.example.com --nginx
            renew: certbot-auto renew --no-self-upgrade
            Or, with DNS:
              certbot-auto --manual --preferred-challenges=dns --expand \\
              --renew-by-default --manual-public-ip-logging-ok  --text \\
              --agree-tos --email i.yanchuan@gmail.com certonly -d xx.co
        '''
        )
    )
    print('Crontab:')
    print(
        '0 0 * * * PATH=%s %s renew -n --nginx --no-self-upgrade '
        '>> /tmp/certbot.log 2>&1' % (path, bin_name)
    )
    print(
        'After obtain certs, change file permissions:\n'
        '  chmod 755 /etc/letsencrypt/{live,archive}'
    )
    print('-' * 56)


def _setup_nodejs(c):
    versions = json.load(
        urllib2.urlopen('https://npm.taobao.org/mirrors/node/index.json')
    )
    lts = sorted(
        (i for i in versions if i['lts']), key=lambda i: parse_version(i['version'])
    )[-1]
    # already has?
    if c.run(
        'which node && test `node --version` = "%s"' % lts['version'], warn=True
    ).ok:
        print('Already installed nodejs')
        return
    dist_url = 'https://nodejs.org/dist/latest-{}/node-{}-linux-x64.tar.gz'
    # dist_url = 'https://npm.taobao.org/mirrors/node/latest-{}/node-{}-linux-x64.tar.gz'
    dist_url = dist_url.format(lts['lts'].lower(), lts['version'])
    c.run('wget -O /tmp/node.tar.xz --tries %s %s' % (WGET_TRIES, dist_url))
    c.sudo(
        'tar -C /usr/ --exclude CHANGELOG.md --exclude LICENSE '
        '--exclude README.md --strip-components 1 -xf /tmp/node.tar.xz'
    )
    # can listening on 80 and 443
    # sudo('setcap cap_net_bind_service=+ep /usr/bin/node')


def _setup_yarn(c):
    if c.run('which yarn', warn=True).ok:
        print('Already installed yarn')
        return
    c.run('curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | sudo apt-key add -')
    c.run(
        'echo "deb https://dl.yarnpkg.com/debian/ stable main" | sudo '
        'tee /etc/apt/sources.list.d/yarn.list'
    )
    c.run('sudo apt-get update -yq && sudo apt-get install -yq yarn')


def _setup_mysql(c):
    if c.run('which mysqld', warn=True).ok:
        print('Already installed mysql')
        return
    # user/password => root/root
    c.sudo(
        "debconf-set-selections <<< 'mysql-server mysql-server/"
        "root_password password root'"
    )
    c.sudo(
        "debconf-set-selections <<< 'mysql-server mysql-server/"
        "root_password_again password root'"
    )
    c.sudo(
        'apt-get install -yq libmysqld-dev mysql-server mysql-client '
        'libmysqlclient-dev'
    )


def _setup_mongodb(c):
    if c.run('which mongod', warn=True).ok:
        print('Already installed mongod')
        return
    sysinfo = _get_ubuntu_info(c)
    if not sysinfo['x64']:
        print('mongodb only supports 64bit system')
        return
    c.sudo(
        'apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 '
        '--recv 9DA31620334BD75D9DCB49F368818C72E52529D4'
    )
    if sysinfo['dist'] == 'debian':
        line = (
            'deb http://repo.mongodb.org/apt/debian '
            '{}/mongodb-org/4.0 main'.format(sysinfo['codename'])
        )
    else:
        line = (
            'deb [ arch=amd64 ] https://repo.mongodb.org/apt/ubuntu '
            '{}/mongodb-org/4.0 multiverse'.format(sysinfo['codename'])
        )
    c.run(
        'echo "{}" | sudo tee /etc/apt/sources.list.d/mongodb-org-4.0.list'
        ''.format(line)
    )
    c.run('sudo apt-get update -yq && sudo apt-get install -yq mongodb-org')


def _setup_nginx(c):
    if c.run('which nginx', warn=True).ok:
        print('Already installed nginx')
        return
    sysinfo = _get_ubuntu_info(c)
    # key
    c.run('curl https://nginx.org/keys/nginx_signing.key | sudo apt-key add -')
    # repo
    c.run(
        'echo -e "deb http://nginx.org/packages/%s/ %s nginx\\n'
        'deb-src http://nginx.org/packages/%s/ %s nginx" | sudo tee '
        '/etc/apt/sources.list.d/nginx.list'
        % (sysinfo['dist'], sysinfo['codename'], sysinfo['dist'], sysinfo['codename'])
    )
    c.run('sudo apt-get update -yq && sudo apt-get install -yq nginx')
    c.put('nginx.conf.example', '/tmp/')
    c.run('sudo mv /tmp/nginx.conf.example /etc/nginx/conf.d/')


def _setup_redis(c):
    if c.run('which redis-server', warn=True).ok:
        print('Already installed redis')
        return
    c.sudo('apt-get install redis-server -yq')


def _setup_docker(c):
    # https://docs.docker.com/install/linux/docker-ce/ubuntu/
    if c.run('which docker', warn=True).ok:
        print('Already installed docker')
        return
    sysinfo = _get_ubuntu_info(c)
    if sysinfo['dist'] == 'ubuntu' and sysinfo['release'] == '14.04':
        c.sudo('apt-get update -yq')
        c.sudo(
            'apt-get install -yq linux-image-extra-virtual '
            'linux-image-extra-$(uname -r)'
        )
    c.sudo(
        'apt-get install -yq apt-transport-https ca-certificates '
        'software-properties-common curl gnupg2'
    )
    c.run(
        'curl -fsSL https://download.docker.com/linux/{}/gpg | '
        'sudo apt-key add -'.format(sysinfo['dist'])
    )
    c.sudo(
        'add-apt-repository -y "deb [arch=amd64] '
        'https://download.docker.com/linux/{dist} {codename} stable"'
        ''.format(**sysinfo)
    )
    c.run('sudo apt-get update -yq && sudo apt-get install -yq docker-ce')
    # docker logging rotate
    c.run(
        r'''echo -e '{\n  "log-driver": "json-file",\n  "log-opts": '''
        r'''{\n    "max-size": "100m",\n    "max-file": "5"\n  }\n}' '''
        r'''| sudo tee /etc/docker/daemon.json'''
    )
    c.sudo('service docker restart', warn=True)
    # fix permission issue
    if c.run('test $USER = root', warn=True).failed:
        c.run('sudo usermod -a -G docker $USER', warn=True)
    # docker-compose
    c.sudo(
        'curl -L "https://github.com/docker/compose/releases/latest/download/'
        'docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose',
        warn=True,
    )
    c.sudo('chmod +x /usr/local/bin/docker-compose', warn=True)


def _setup_mariadb(c):
    '''
    can be used to migrate mysql to mariadb
    '''
    if c.run('test -f /etc/mysql/conf.d/mariadb.cnf ', warn=True).ok:
        print('Already installed mariadb')
        return
    # user/password => root/root
    c.sudo(
        "debconf-set-selections <<< 'mariadb-server mysql-server/"
        "root_password password root'"
    )
    c.sudo(
        "debconf-set-selections <<< 'mariadb-server mysql-server/"
        "root_password_again password root'"
    )
    # https://mariadb.com/kb/en/mariadb/installing-mariadb-deb-files/
    sysinfo = _get_ubuntu_info(c)
    key = '0xcbcb082a1bb943db'
    if _V(sysinfo['release']) >= _V('16.04'):
        key = '0xF1656F24C74CD1D8'
    c.sudo('apt-key adv --recv-keys --keyserver hkp://keyserver.ubuntu.com:80 %s' % key)
    c.sudo('apt-get install -yq software-properties-common')
    c.sudo(
        "add-apt-repository -y 'deb http://ftp.osuosl.org/pub/mariadb/repo/"
        "10.2/ubuntu %s main'" % sysinfo['codename']
    )
    c.sudo('apt-get update -yq')
    c.sudo('service mysql stop', warn=True)
    c.sudo('apt-get install -yq mariadb-server libmysqld-dev', warn=True)


def _setup_solc(c):
    # https://docs.docker.com/engine/installation/linux/ubuntu/
    if c.run('which solc', warn=True).ok:
        print('Already installed solc')
        return
    c.sudo('add-apt-repository -y ppa:ethereum/ethereum')
    c.sudo('apt-get update -yq')
    c.sudo('apt-get install -yq solc')


def _setup_mono(c):
    # http://www.mono-project.com/download/#download-lin
    if c.run('which mono', warn=True).ok:
        print('Already installed mono')
        return
    c.sudo(
        'apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys '
        '3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF',
        warn=True,
    )
    sysinfo = _get_ubuntu_info(c)
    c.run(
        'echo "deb http://download.mono-project.com/repo/ubuntu %s main" | sudo tee'
        ' /etc/apt/sources.list.d/mono-official.list' % sysinfo['codename'],
        warn=True,
    )
    c.run('sudo apt-get update -yq && sudo apt-get install -y mono-devel')


def _setup_go(c):
    # https://golang.org/doc/install
    url = 'https://dl.google.com/go/go1.11.5.linux-amd64.tar.gz'
    if c.run('which go', warn=True).ok:
        print('Already installed go')
        return
    c.run(
        'wget %s -O - --tries %s | sudo tar -C /usr/local -xzf -' % (url, WGET_TRIES),
        warn=True,
    )
    append(c, '/etc/profile', 'export PATH=$PATH:/usr/local/go/bin')


def _setup_debian(c):
    if not c.run('which sudo', warn=True).ok:
        c.run('apt-get install sudo -y')
    _setup_aptget(c)
    c.sudo(
        'apt-get install -yq git unzip curl wget tar sudo zip '
        'sqlite3 tmux ntp build-essential gettext libcap2-bin netcat '
        'silversearcher-ag htop jq python2 dirmngr cron rsync locales'
    )
    c.sudo('systemctl enable ntp.service')
    c.sudo('systemctl start ntp.service')
    # add-apt-repository
    c.sudo('apt-get install -yq software-properties-common', warn=True)
    _setup_env(c)
    # locale
    c.run('echo en_US.UTF-8 UTF-8 | sudo tee /etc/locale.gen')
    c.sudo('locale-gen en_US.UTF-8')
    _setup_bbr(c)
    _disable_ipv6(c)


@task
def setup_swap(c, size=1):
    '''
    Install $size GiB swapfile
    '''
    path = '/swap%sG' % size
    if c.run('test -f %s' % path, warn=True).ok:
        print('%s already exists' % path)
        return
    c.sudo('fallocate -l %sG %s' % (size, path))
    c.sudo('chmod 600 ' + path)
    c.sudo('mkswap ' + path)
    c.sudo('swapon ' + path)
    if not contains(c, '/etc/sysctl.conf', 'vm.swappiness=10'):
        append(c, '/etc/sysctl.conf', 'vm.swappiness=10')
    line = "%s none swap sw 00" % path
    if not contains(c, '/etc/fstab', line):
        append(c, '/etc/fstab', line)


def _setup_python3(c):
    _setup_python(c)


def _setup_python(c):
    # Prerequisites: git, dotfiles (in debian)
    c.run(
        'curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash'
    )
    c.sudo(
        'apt install -y build-essential checkinstall libncursesw5-dev libssl-dev '
        'libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev '
        'libreadline-dev liblzma-dev'
    )
    # c.run('pyenv install 2.7.18')
    c.run('pyenv install 3.10.5')
    c.run('pyenv global 3.10.5')


def _setup_bbr(c):
    '''
    Google bbr: https://github.com/google/bbr
    '''
    if c.sudo(
        'sysctl net.ipv4.tcp_available_congestion_control | grep -q bbr', warn=True
    ).ok:
        print('bbr already enabled')
        return
    kernel_version = c.run('uname -r', hide=True).stdout.strip()
    if _V(kernel_version) < _V('4.9'):
        print('bbr need linux 4.9+, please upgrade your kernel')
        return
    for line in [
        'net.core.default_qdisc = fq',
        'net.ipv4.tcp_congestion_control = bbr',
    ]:
        if not contains(c, '/etc/sysctl.conf', line):
            append(c, '/etc/sysctl.conf', line)
    c.sudo('sysctl -p')


def _setup_ossutil(c):
    '''
    aliyun ossutil
    https://help.aliyun.com/document_detail/120075.html
    '''
    c.run(
        'sudo wget -O /usr/local/bin/ossutil http://gosspublic.alicdn.com/ossutil/'
        '1.7.0/ossutil64 && sudo chmod +x /usr/local/bin/ossutil',
        warn=True,
    )
    print(
        'Usage: ossutil --access-key-id=<AK> --access-key-secret=<SK> '
        '--endpoint=oss-cn-zhangjiakou-internal.aliyuncs.com cp <SRC_FILE> '
        'oss://<BUCKET_NAME>/<PATH>'
    )
