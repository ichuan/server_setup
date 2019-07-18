#!/usr/bin/env python
# coding: utf-8
# yc@2016/12/28

from __future__ import print_function

from fabric.api import run, env, sudo, put, cd
from fabric.api import reboot as restart
from fabric.contrib.files import append, contains, comment, sed, exists
from distutils.version import LooseVersion as _V

env.use_ssh_config = True
env.colorize_errors = True
# wget max try
WGET_TRIES = 3
G = {}


def setup(*what):
    '''
    Fresh setup. Optional arguments: \
    letsencrypt, nodejs, yarn, mysql, mongodb, redis, mariadb, solc, mono, go
    '''
    if what:
        for name in what:
            func = globals().get('_setup_%s' % name, None)
            if func is None:
                print('No such task: %s' % name)
            else:
                func()
        return
    _disable_ipv6()
    _setup_debian()
    _setup_env()
    # _setup_optional()


def _disable_ipv6():
    sysconf_no_ipv6 = [
        'net.ipv6.conf.all.disable_ipv6 = 1',
        'net.ipv6.conf.default.disable_ipv6 = 1',
        'net.ipv6.conf.lo.disable_ipv6 = 1',
    ]
    append('/etc/sysctl.conf', sysconf_no_ipv6, use_sudo=True)
    sudo('sysctl -p')


def reboot():
    '''
    Restart a server.
    '''
    restart()


def _get_ubuntu_info():
    # returns {release, codename, is_64bit}
    if 'sysinfo' not in G:
        G['sysinfo'] = {
            'release': run("lsb_release -sr", shell=False).strip(),
            'codename': run("lsb_release -sc", shell=False).strip(),
            'x64': run('test -d /lib64', warn_only=True).succeeded,
            'dist': run(
                "lsb_release -is | tr [:upper:] [:lower:]", shell=False
            ).strip(),
        }
    return G['sysinfo']


def _setup_aptget():
    sudo('apt-get update -yq')
    sudo(
        'DEBIAN_FRONTEND=noninteractive '
        'apt-get -yq -o Dpkg::Options::="--force-confdef" '
        '-o Dpkg::Options::="--force-confold" upgrade'
    )


def _setup_env():
    sysinfo = _get_ubuntu_info()
    # dotfiles
    run(
        '[ ! -f ~/.tmux.conf ] && { '
        'git clone --single-branch --recursive '
        'https://github.com/ichuan/dotfiles.git '
        "&& bash dotfiles/bootstrap.sh -f; }",
        warn_only=True,
    )
    # UTC timezone
    sudo('cp /usr/share/zoneinfo/UTC /etc/localtime', warn_only=True)
    # limits.conf, max open files
    _limits()
    # rc.local after 15.04
    # https://wiki.ubuntu.com/SystemdForUpstartUsers
    if _V(sysinfo['release']) >= _V('15.04'):
        _enable_rc_local()
    # sysctl.conf
    _sysctl()
    # disable ubuntu upgrade check
    sudo(
        "sed -i 's/^Prompt.*/Prompt=never/' " "/etc/update-manager/release-upgrades",
        warn_only=True,
    )


def _limits():
    sudo(
        r'echo -e "*    soft    nofile  500000\n*    hard    nofile  500000'
        r'\nroot soft    nofile  500000\nroot hard    nofile  500000"'
        r' > /etc/security/limits.conf'
    )
    # https://underyx.me/2015/05/18/raising-the-maximum-number-of-file-descriptors
    line = 'session required pam_limits.so'
    for p in ('/etc/pam.d/common-session', '/etc/pam.d/common-session-noninteractive'):
        if exists(p) and not contains(p, line):
            sudo('echo -e "%s" >> %s' % (line, p))


def _sysctl():
    path = '/etc/sysctl.conf'
    if not contains(path, 'vm.overcommit_memory = 1'):
        sudo('echo -e "vm.overcommit_memory = 1" >> %s' % path)
    if not contains(path, 'net.core.somaxconn = 65535'):
        sudo('echo -e "net.core.somaxconn = 65535" >> %s' % path)
    if not contains(path, 'fs.file-max = 6553560'):
        sudo('echo -e "fs.file-max = 6553560" >> %s' % path)


def _setup_optional():
    _setup_mysql()
    _setup_mongodb()


def _setup_certbot():
    _setup_letsencrypt()


def _setup_letsencrypt():
    # https://certbot.eff.org/
    bin_name = '/usr/bin/certbot-auto'
    sudo(
        'wget https://dl.eff.org/certbot-auto -O %s --tries %s'
        % (bin_name, WGET_TRIES),
        warn_only=True,
    )
    sudo('chmod +x %s' % bin_name)
    path = run('echo $PATH')
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


def _setup_nodejs():
    sysinfo = _get_ubuntu_info()
    arch = 'x64' if sysinfo['x64'] else 'x86'
    filename = run(
        "curl -s https://nodejs.org/download/release/latest-carbon/"
        "SHASUMS256.txt | grep linux-%s.tar.xz | awk '{print $2}'" % arch,
        shell=False,
    )
    # already has?
    if run(
        'which node && test `node --version` = "%s"' % filename.split('-')[1],
        warn_only=True,
    ).succeeded:
        print('Already installed nodejs')
        return
    dist_url = 'https://nodejs.org/dist/latest-carbon/%s' % filename.strip()
    run('wget -O /tmp/node.tar.xz --tries %s %s' % (WGET_TRIES, dist_url))
    sudo(
        'tar -C /usr/ --exclude CHANGELOG.md --exclude LICENSE '
        '--exclude README.md --strip-components 1 -xf /tmp/node.tar.xz'
    )
    # can listening on 80 and 443
    # sudo('setcap cap_net_bind_service=+ep /usr/bin/node')


def _setup_yarn():
    if run('which yarn', warn_only=True).succeeded:
        print('Already installed yarn')
        return
    sudo('curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -')
    sudo(
        'echo "deb https://dl.yarnpkg.com/debian/ stable main" | '
        'tee /etc/apt/sources.list.d/yarn.list'
    )
    sudo('apt-get update -yq && apt-get install -yq yarn')


def _setup_mysql():
    if run('which mysqld', warn_only=True).succeeded:
        print('Already installed mysql')
        return
    # user/password => root/root
    sudo(
        "debconf-set-selections <<< 'mysql-server mysql-server/"
        "root_password password root'"
    )
    sudo(
        "debconf-set-selections <<< 'mysql-server mysql-server/"
        "root_password_again password root'"
    )
    sudo(
        'apt-get install -yq libmysqld-dev mysql-server mysql-client '
        'libmysqlclient-dev'
    )


def _setup_mongodb():
    if run('which mongod', warn_only=True).succeeded:
        print('Already installed mongod')
        return
    sysinfo = _get_ubuntu_info()
    if not sysinfo['x64']:
        print('mongodb only supports 64bit system')
        return
    sudo(
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
    sudo('echo "{}" | tee /etc/apt/sources.list.d/mongodb-org-4.0.list' ''.format(line))
    sudo('apt-get update -yq && apt-get install -yq mongodb-org')


def _enable_rc_local():
    rc_local = '/etc/rc.local'
    put('rc-local.service', '/etc/systemd/system/', use_sudo=True)
    sudo('touch %s' % rc_local)
    if run("head -1 %s | grep -q '^#!/bin/sh'" % rc_local, warn_only=True).failed:
        sudo(r"sed -i '1s/^/#!\/bin\/sh \n/' %s" % rc_local)
    _append_rc_local('echo never > /sys/kernel/mm/transparent_hugepage/enabled')
    sudo('chmod +x %s' % rc_local)
    sudo('systemctl enable rc-local')


def _setup_nginx():
    if run('which nginx', warn_only=True).succeeded:
        print('Already installed nginx')
        return
    sysinfo = _get_ubuntu_info()
    # key
    sudo('curl https://nginx.org/keys/nginx_signing.key | apt-key add -')
    # repo
    sudo(
        'echo -e "deb http://nginx.org/packages/%s/ %s nginx\\n'
        'deb-src http://nginx.org/packages/%s/ %s nginx" | tee '
        '/etc/apt/sources.list.d/nginx.list'
        % (sysinfo['dist'], sysinfo['codename'], sysinfo['dist'], sysinfo['codename'])
    )
    sudo('apt-get update -yq && apt-get install -yq nginx')
    put('nginx.conf.example', '/etc/nginx/conf.d/', use_sudo=True)


def _setup_redis():
    if run('which redis-server', warn_only=True).succeeded:
        print('Already installed redis')
        return
    sudo('apt-get install redis-server -yq')


def _setup_docker():
    # https://docs.docker.com/install/linux/docker-ce/ubuntu/
    if run('which docker', warn_only=True).succeeded:
        print('Already installed docker')
        return
    sysinfo = _get_ubuntu_info()
    if sysinfo['dist'] == 'ubuntu' and sysinfo['release'] == '14.04':
        sudo('apt-get update -yq')
        sudo(
            'apt-get install -yq linux-image-extra-virtual '
            'linux-image-extra-$(uname -r)'
        )
    sudo(
        'apt-get install -yq apt-transport-https ca-certificates '
        'software-properties-common curl gnupg2'
    )
    sudo(
        'curl -fsSL https://download.docker.com/linux/{}/gpg | '
        'apt-key add -'.format(sysinfo['dist'])
    )
    sudo(
        'add-apt-repository -y "deb [arch=amd64] '
        'https://download.docker.com/linux/{dist} {codename} stable"'
        ''.format(**sysinfo)
    )
    sudo('apt-get update -yq && apt-get install -yq docker-ce')
    # docker logging rotate
    sudo(
        r'''echo -e '{\n  "log-driver": "json-file",\n  "log-opts": '''
        r'''{\n    "max-size": "50m",\n    "max-file": "5"\n  }\n}' '''
        r'''> /etc/docker/daemon.json'''
    )
    sudo('service docker restart', warn_only=True)
    # fix permission issue
    if run('test $USER = root', warn_only=True).failed:
        sudo('usermod -a -G docker $USER', warn_only=True)
    # docker-compose
    sudo('pip install docker-compose', warn_only=True)


def _append_rc_local(cmd):
    rc_local = '/etc/rc.local'
    comment(rc_local, r'^exit 0', use_sudo=True)
    append(rc_local, [cmd, 'exit 0'], use_sudo=True)
    sed(rc_local, '^#exit 0.*', '', use_sudo=True, backup='')


def _setup_mariadb():
    '''
    can be used to migrate mysql to mariadb
    '''
    if run('test -f /etc/mysql/conf.d/mariadb.cnf ', warn_only=True).succeeded:
        print('Already installed mariadb')
        return
    # user/password => root/root
    sudo(
        "debconf-set-selections <<< 'mariadb-server mysql-server/"
        "root_password password root'"
    )
    sudo(
        "debconf-set-selections <<< 'mariadb-server mysql-server/"
        "root_password_again password root'"
    )
    # https://mariadb.com/kb/en/mariadb/installing-mariadb-deb-files/
    sysinfo = _get_ubuntu_info()
    key = '0xcbcb082a1bb943db'
    if _V(sysinfo['release']) >= _V('16.04'):
        key = '0xF1656F24C74CD1D8'
    sudo('apt-key adv --recv-keys --keyserver hkp://keyserver.ubuntu.com:80 %s' % key)
    sudo('apt-get install -yq software-properties-common')
    sudo(
        "add-apt-repository -y 'deb http://ftp.osuosl.org/pub/mariadb/repo/"
        "10.2/ubuntu %s main'" % sysinfo['codename']
    )
    sudo('apt-get update -yq')
    sudo('service mysql stop', warn_only=True)
    sudo('apt-get install -yq mariadb-server libmysqld-dev', warn_only=True)


def _setup_solc():
    # https://docs.docker.com/engine/installation/linux/ubuntu/
    if run('which solc', warn_only=True).succeeded:
        print('Already installed solc')
        return
    sudo('add-apt-repository -y ppa:ethereum/ethereum')
    sudo('apt-get update -yq')
    sudo('apt-get install -yq solc')


def _setup_mono():
    # http://www.mono-project.com/download/#download-lin
    if run('which mono', warn_only=True).succeeded:
        print('Already installed mono')
        return
    sudo(
        'apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys '
        '3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF',
        warn_only=True,
    )
    sysinfo = _get_ubuntu_info()
    sudo(
        'echo "deb http://download.mono-project.com/repo/ubuntu %s main" | tee'
        ' /etc/apt/sources.list.d/mono-official.list' % sysinfo['codename'],
        warn_only=True,
    )
    sudo('apt-get update -yq && apt-get install -y mono-devel')


def _setup_go():
    # https://golang.org/doc/install
    url = 'https://dl.google.com/go/go1.11.5.linux-amd64.tar.gz'
    if run('which go', warn_only=True).succeeded:
        print('Already installed go')
        return
    sudo(
        'wget %s -O - --tries %s | tar -C /usr/local -xzf -' % (url, WGET_TRIES),
        warn_only=True,
    )
    append('/etc/profile', 'export PATH=$PATH:/usr/local/go/bin', use_sudo=True)


def _try_install_latest(package):
    sysinfo = _get_ubuntu_info()
    url = (
        'https://raw.githubusercontent.com/ichuan/packages/master'
        '/{dist}/{release}/{package}/latest.deb'
        ''.format(package=package, **sysinfo)
    )
    if run('wget -O /tmp/til.deb {}'.format(url), warn_only=True).succeeded:
        # latest tmux
        sudo('dpkg -i /tmp/til.deb')
    else:
        # old
        sudo('apt-get install -y {}'.format(package))


def _setup_debian():
    if not run('which sudo', warn_only=True).succeeded:
        run('apt-get install sudo -y')
    _setup_aptget()
    sudo(
        'apt-get install -yq git unzip curl wget tar sudo zip '
        'sqlite3 tmux ntp build-essential gettext libcap2-bin '
        'ack-grep htop jq python dirmngr'
    )
    _try_install_latest('tmux')
    # add-apt-repository
    sudo('apt-get install -yq software-properties-common', warn_only=True)
    _setup_env()
    _setup_bbr()


def setup_swap(size='1'):
    '''
    添加 ?G 虚拟内存
    '''
    path = '/swap%sG' % size
    if run('test -f %s' % path, warn_only=True).succeeded:
        print('%s already exists' % path)
        return
    sudo('fallocate -l %sG %s' % (size, path))
    sudo('chmod 600 ' + path)
    sudo('mkswap ' + path)
    sudo('swapon ' + path)
    sudo('echo vm.swappiness=10 >> /etc/sysctl.conf')
    sudo('echo "%s none swap sw 00" >> /etc/fstab' % path)


def _setup_python3():
    url = 'https://www.python.org/ftp/python/3.7.3/Python-3.7.3.tgz'
    sudo(
        'apt install -y build-essential checkinstall libreadline-gplv2-dev '
        'libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev '
        'libc6-dev libbz2-dev libffi-dev'
    )
    with cd('/tmp'):
        run('curl %s > py.tgz' % url)
        run('tar xf py.tgz')
        with cd('Python-3.*'):
            sudo('./configure --enable-optimizations')
            sudo('make altinstall')


def _setup_bbr():
    '''
    Google bbr: https://github.com/google/bbr
    '''
    if sudo(
        'sysctl net.ipv4.tcp_available_congestion_control | grep -q bbr', warn_only=True
    ).succeeded:
        print('bbr already enabled')
        return
    kernel_version = run('uname -r', shell=False).strip()
    if _V(kernel_version) < _V('4.9'):
        print('bbr need linux 4.9+, please upgrade your kernel')
        return
    sysconf = ['net.core.default_qdisc = fq', 'net.ipv4.tcp_congestion_control = bbr']
    append('/etc/sysctl.conf', sysconf, use_sudo=True)
    sudo('sysctl -p')
