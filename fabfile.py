#!/usr/bin/env python
# coding: utf-8
# yc@2016/12/28

from fabric.api import run, env, sudo, put
from fabric.api import reboot as restart
from distutils.version import LooseVersion as _V

env.use_ssh_config = True
env.colorize_errors = True
# wget max try
WGET_TRIES = 3
G = {}


def setup(what=''):
    '''
    Fresh setup. Optional argument: letsencrypt, nodejs, yarn, mysql, mongodb
    '''
    if what:
        for name in what.split(','):
            func = globals().get('_setup_%s' % name, None)
            if func is None:
                print 'No such task: %s' % name
            else:
                func()
        return
    _setup_aptget()
    _setup_required()
    _setup_env()
    # _setup_optional()


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
    sudo('apt-get update && apt-get upgrade -y')


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


def _setup_required():
    # git and utils
    sudo(
        'apt-get install -y git unzip unrar curl wget tar sudo zip python-pip '
        'python-virtualenv sqlite3 tmux ntp build-essential uwsgi gettext '
        'uwsgi-plugin-python ack-grep htop python-setuptools'
    )
    # pillow reqs
    sudo(
        'apt-get install -y libtiff5-dev libjpeg8-dev zlib1g-dev liblcms2-dev '
        'libfreetype6-dev libwebp-dev tcl8.6-dev tk8.6-dev python-tk'
    )
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
    sysinfo = _get_ubuntu_info()
    bin_name = ''
    if sysinfo['release'] == '16.04':
        run('apt-get install -y letsencrypt')
        bin_name = 'letsencrypt'
    elif sysinfo['release'] == '16.10':
        run('apt-get install -y certbot')
        bin_name = 'certbot'
    else:
        bin_name = '~/certbot-auto'
        run('rm -f %s' % bin_name, warn_only=True)
        run(
            'wget https://dl.eff.org/certbot-auto -O %s --tries %s'
            % (bin_name, WGET_TRIES)
        )
        run('chmod a+x %s' % bin_name)
    print '-' * 56
    print 'Usage: letsencrypt certonly -d example.com -d www.example.com'
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
    sudo('apt-get update && apt-get install -y yarn')


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
        'apt-get install -y libmysqld-dev mysql-server mysql-client '
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
    sudo('apt-get update && apt-get install -y mongodb-org')


def _enable_rc_local():
    put('rc-local.service', '/etc/systemd/system/', use_sudo=True)
    sudo('touch /etc/rc.local')
    if run(
        "head -1 /etc/rc.local | grep -q '^#!\/bin\/sh '", warn_only=True
    ).failed:
        run("sed -i '1s/^/#!\/bin\/sh \\n/' /etc/rc.local")
    sudo('chmod +x /etc/rc.local')
    sudo('systemctl enable rc-local')
