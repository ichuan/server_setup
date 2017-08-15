#!/usr/bin/env python
# coding: utf-8
# yc@2016/12/28

from fabric.api import run, env, sudo, put
from fabric.api import reboot as restart
from fabric.contrib.files import append, contains, comment, sed
from distutils.version import LooseVersion as _V

env.use_ssh_config = True
env.colorize_errors = True
# wget max try
WGET_TRIES = 3
G = {}


def setup(*what):
    '''
    Fresh setup. Optional arguments: \
    letsencrypt, nodejs, yarn, mysql, mongodb, redis, mariadb
    '''
    if what:
        for name in what:
            func = globals().get('_setup_%s' % name, None)
            if func is None:
                print 'No such task: %s' % name
            else:
                func()
        return
    _disable_ipv6()
    _setup_aptget()
    _setup_required()
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
        }
    return G['sysinfo']


def _setup_aptget():
    sudo('apt-get update -yq && apt-get upgrade -yq')


def _setup_env():
    sysinfo = _get_ubuntu_info()
    # dotfiles
    run(
        '[ ! -f ~/.tmux.conf ] && { '
        'git clone -b minimal --single-branch --recursive '
        'https://github.com/ichuan/dotfiles.git '
        "&& echo 'y' | bash dotfiles/bootstrap.sh; }",
        warn_only=True
    )
    # UTC timezone
    sudo('cp /usr/share/zoneinfo/UTC /etc/localtime', warn_only=True)
    # limits.conf, max open files
    sudo(
        r'echo -e "*    soft    nofile  60000\n*    hard    nofile  65535" > '
        r'/etc/security/limits.conf'
    )
    # rc.local after 15.04
    # https://wiki.ubuntu.com/SystemdForUpstartUsers
    if _V(sysinfo['release']) >= _V('15.04'):
        _enable_rc_local()
    # sysctl.conf
    _sysctl()
    # disable ubuntu upgrade check
    sudo(
        "sed -i 's/^Prompt.*/Prompt=never/' "
        "/etc/update-manager/release-upgrades", warn_only=True
    )


def _sysctl():
    path = '/etc/sysctl.conf'
    if not contains(path, 'vm.overcommit_memory = 1'):
        sudo('echo -e "vm.overcommit_memory = 1" >> %s' % path)
    if not contains(path, 'net.core.somaxconn = 65535'):
        sudo('echo -e "net.core.somaxconn = 65535" >> %s' % path)


def _setup_required():
    # git and utils
    sudo(
        'apt-get install -yq git unzip curl wget tar sudo zip python-pip '
        'python-virtualenv sqlite3 tmux ntp build-essential uwsgi gettext '
        'uwsgi-plugin-python ack-grep htop python-setuptools'
    )
    # pillow reqs
    sudo(
        'apt-get install -yq libtiff5-dev libjpeg8-dev zlib1g-dev liblcms2-dev'
        ' libfreetype6-dev libwebp-dev tcl8.6-dev tk8.6-dev python-tk'
    )
    # add-apt-repository
    sudo('apt-get install -yq software-properties-common', warn_only=True)
    # letsencrypt
    # _setup_letsencrypt()
    # nodejs
    # _setup_nodejs(sysinfo['x64'])
    # yarnpkg
    # _setup_yarn()


def _setup_optional():
    _setup_mysql()
    _setup_mongodb()


def _setup_letsencrypt():
    # https://certbot.eff.org/
    bin_name = '/usr/bin/certbot-auto'
    sudo(
        'wget https://dl.eff.org/certbot-auto -O %s --tries %s'
        % (bin_name, WGET_TRIES),
        warn_only=True
    )
    sudo('chmod +x %s' % bin_name)
    path = run('echo $PATH')
    print '-' * 56
    print 'Usage:'
    print '  new: certbot-auto -d example.com -d www.example.com --nginx'
    print 'renew: certbot-auto renew --no-self-upgrade'
    print 'Crontab:'
    print (
        '0 0 * * * PATH=%s %s renew -n --nginx --no-self-upgrade '
        '>> /tmp/certbot.log 2>&1' % (path, bin_name)
    )
    print '-' * 56


def _setup_nodejs():
    sysinfo = _get_ubuntu_info()
    arch = 'x64' if sysinfo['x64'] else 'x86'
    filename = run(
        "curl -s https://nodejs.org/dist/latest/SHASUMS256.txt | "
        "grep linux-%s.tar.xz | awk '{print $2}'" % arch,
        shell=False
    )
    # already has?
    if run(
        'which node && test `node --version` = "%s"' % filename.split('-')[1],
        warn_only=True
    ).succeeded:
        print 'Already installed nodejs'
        return
    dist_url = 'https://nodejs.org/dist/latest/%s' % filename.strip()
    run('wget -O /tmp/node.tar.xz --tries %s %s' % (WGET_TRIES, dist_url))
    sudo(
        'tar -C /usr/ --exclude CHANGELOG.md --exclude LICENSE '
        '--exclude README.md --strip-components 1 -xf /tmp/node.tar.xz'
    )
    # can listening on 80 and 443
    # sudo('setcap cap_net_bind_service=+ep /usr/bin/node')


def _setup_yarn():
    if run('which yarn', warn_only=True).succeeded:
        print 'Already installed yarn'
        return
    sudo('curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -')
    sudo(
        'echo "deb https://dl.yarnpkg.com/debian/ stable main" | '
        'tee /etc/apt/sources.list.d/yarn.list'
    )
    sudo('apt-get update -yq && apt-get install -yq yarn')


def _setup_mysql():
    if run('which mysqld', warn_only=True).succeeded:
        print 'Already installed mysql'
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
        print 'Already installed mongod'
        return
    sysinfo = _get_ubuntu_info()
    if not sysinfo['x64']:
        print 'mongodb only supports 64bit system'
        return
    sudo(
        'apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 '
        '--recv 0C49F3730359A14518585931BC711F9BA15703C6'
    )
    sudo(
        'echo "deb [ arch=amd64 ] http://repo.mongodb.org/apt/ubuntu '
        '%s/mongodb-org/3.4 multiverse" | tee '
        '/etc/apt/sources.list.d/mongodb-org-3.4.list'
        % sysinfo['codename']
    )
    sudo('apt-get update -yq && apt-get install -yq mongodb-org')


def _enable_rc_local():
    rc_local = '/etc/rc.local'
    put('rc-local.service', '/etc/systemd/system/', use_sudo=True)
    sudo('touch %s' % rc_local)
    if run(
        "head -1 %s | grep -q '^#!\/bin\/sh '" % rc_local, warn_only=True
    ).failed:
        run("sed -i '1s/^/#!\/bin\/sh \\n/' %s" % rc_local)
    _append_rc_local(
        'echo never > /sys/kernel/mm/transparent_hugepage/enabled'
    )
    sudo('chmod +x %s' % rc_local)
    sudo('systemctl enable rc-local')


def _setup_nginx():
    if run('which nginx', warn_only=True).succeeded:
        print 'Already installed nginx'
        return
    sysinfo = _get_ubuntu_info()
    # key
    sudo('curl https://nginx.org/keys/nginx_signing.key | apt-key add -')
    # repo
    sudo(
        'echo -e "deb http://nginx.org/packages/ubuntu/ %s nginx\\n'
        'deb-src http://nginx.org/packages/ubuntu/ %s nginx" | tee '
        '/etc/apt/sources.list.d/nginx.list'
        % (sysinfo['codename'], sysinfo['codename'])
    )
    sudo('apt-get update -yq && apt-get install -yq nginx')
    put('nginx.conf.example', '/etc/nginx/conf.d/', use_sudo=True)


def _setup_redis():
    if run('which redis-server', warn_only=True).succeeded:
        print 'Already installed redis'
        return
    sudo('apt-get install redis-server -yq')


def _setup_docker():
    # https://docs.docker.com/engine/installation/linux/ubuntu/
    if run('which docker', warn_only=True).succeeded:
        print 'Already installed docker'
        return
    sysinfo = _get_ubuntu_info()
    if sysinfo['release'] == '14.04':
        sudo('apt-get update -yq')
        sudo('apt-get install -yq linux-image-extra-virtual '
             'linux-image-extra-$(uname -r)')
    sudo(
        'apt-get install -yq apt-transport-https ca-certificates '
        'software-properties-common'
    )
    sudo(
        'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | '
        'apt-key add -'
    )
    sudo(
        'add-apt-repository -y "deb [arch=amd64] '
        'https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"'
    )
    sudo('apt-get update -yq && apt-get install -yq docker-ce')


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
        print 'Already installed mariadb'
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
    sudo(
        'apt-key adv --recv-keys --keyserver hkp://keyserver.ubuntu.com:80 %s'
        % key
    )
    sudo('apt-get install -yq software-properties-common')
    sudo(
        "add-apt-repository -y 'deb http://ftp.osuosl.org/pub/mariadb/repo/"
        "10.2/ubuntu %s main'" % sysinfo['codename']
    )
    sudo('apt-get update -yq')
    sudo('service mysql stop', warn_only=True)
    sudo('apt-get install -yq mariadb-server libmysqld-dev', warn_only=True)
