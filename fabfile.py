#!/usr/bin/env python
# coding: utf-8
# yc@2016/12/28

from fabric.api import run, env, sudo
from fabric.api import reboot as restart

env.use_ssh_config = True
env.colorize_errors = True


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
    version, is_64bit = _get_ubuntu_version()
    _setup_aptget()
    _setup_required(version, is_64bit)
    _setup_env()
    _setup_optional(version, is_64bit)


def reboot():
    '''
    Restart a server.
    '''
    restart()


def _get_ubuntu_version():
    # returns [version, is_64bit]
    version = run("lsb_release -r | awk '{print $2}'", shell=False).strip()
    is_64bit = run('[ -d /lib64 ]', warn_only=True).succeeded
    return [version, is_64bit]


def _setup_aptget():
    sudo('apt-get update && apt-get upgrade -y')


def _setup_env():
    # dotfiles
    run(
        '[ ! -f ~/.tmux.conf ] && { '
        'git clone --recursive https://github.com/ichuan/dotfiles.git '
        "&& echo 'y' | bash dotfiles/bootstrap.sh; }",
        warn_only=True
    )
    # UTC timezone
    sudo('cp /usr/share/zoneinfo/UTC /etc/localtime')
    # limits.conf, max open files
    sudo(
        r'echo -e "*    soft    nofile  60000\n*    hard    nofile  65535" > '
        r'/etc/security/limits.conf'
    )


def _setup_required(version=None, is_64bit=False):
    if version is None:
        version, is_64bit = _get_ubuntu_version()
    # git and utils
    sudo(
        'apt-get install -y git unzip unrar curl wget tar sudo zip python-pip '
        'python-virtualenv sqlite3 tmux ntp build-essential uwsgi gettext '
        'uwsgi-plugin-python ack-grep htop'
    )
    # pillow reqs
    sudo(
        'apt-get install -y libtiff5-dev libjpeg8-dev zlib1g-dev liblcms2-dev '
        'libfreetype6-dev libwebp-dev tcl8.6-dev tk8.6-dev python-tk'
    )
    # letsencrypt
    _setup_letsencrypt(version)
    # nodejs
    _setup_nodejs(is_64bit)
    # yarnpkg
    _setup_yarn()


def _setup_optional(version=None, is_64bit=True):
    if version is None:
        version, is_64bit = _get_ubuntu_version()
    _setup_mysql()
    _setup_mongodb(version, is_64bit)


def _setup_letsencrypt(system_version=None):
    # https://certbot.eff.org/
    if system_version is None:
        system_version = _get_ubuntu_version()
    bin_name = ''
    if system_version == '16.04':
        run('apt-get install -y letsencrypt')
        bin_name = 'letsencrypt'
    elif system_version == '16.10':
        run('apt-get install -y certbot')
        bin_name = 'certbot'
    else:
        bin_name = '~/certbot-auto'
        run('rm -f %s' % bin_name, warn_only=True)
        run('wget https://dl.eff.org/certbot-auto -O %s' % bin_name)
        run('chmod a+x %s' % bin_name)
    print '-' * 56
    print 'Usage: letsencrypt certonly -d example.com -d www.example.com'
    print '-' * 56


def _setup_nodejs(is_64bit=True):
    arch = 'x64' if is_64bit else 'x86'
    filename = run(
        "curl -s https://nodejs.org/dist/latest/SHASUMS256.txt | "
        "grep linux-%s.tar.xz | awk '{print $2}'" % arch,
        shell=False
    )
    dist_url = 'https://nodejs.org/dist/latest/%s' % filename.strip()
    run('wget -O /tmp/node.tar.xz %s' % dist_url)
    sudo(
        'tar -C /usr/ --exclude CHANGELOG.md --exclude LICENSE '
        '--exclude README.md --strip-components 1 -xf /tmp/node.tar.xz'
    )
    # can listening on 80 and 443
    sudo('setcap cap_net_bind_service=+ep /usr/bin/node')


def _setup_yarn():
    sudo('curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -')
    sudo(
        'echo "deb https://dl.yarnpkg.com/debian/ stable main" | '
        'tee /etc/apt/sources.list.d/yarn.list'
    )
    sudo('apt-get update && apt-get install -y yarn')


def _setup_mysql():
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


def _setup_mongodb(version, is_64bit):
    if not is_64bit:
        print 'mongodb only supports 64bit system'
        return
    sudo(
        'apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 '
        '--recv 0C49F3730359A14518585931BC711F9BA15703C6'
    )
    if version == '12.04':
        name = 'precise'
    elif version == '14.04':
        name = 'trusty'
    elif version == '16.04':
        name = 'xenial'
    else:
        print 'Not support: %s' % version
        return
    sudo(
        'echo "deb [ arch=amd64 ] http://repo.mongodb.org/apt/ubuntu '
        '%s/mongodb-org/3.4 multiverse" | tee '
        '/etc/apt/sources.list.d/mongodb-org-3.4.list'
        % name
    )
    sudo('apt-get update && apt-get install -y mongodb-org')
