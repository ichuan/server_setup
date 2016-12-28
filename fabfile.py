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
        func = globals().get('_setup_%s' % what, None)
        if func is None:
            print 'No such task: %s' % what
            return
        return func()
    _setup_aptget()
    _setup_required()
    _setup_env()
    _setup_optional()


def reboot():
    '''
    Restart a server.
    '''
    restart()


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


def _setup_required():
    # git and utils
    sudo(
        'apt-get install -y git unzip unrar curl wget tar sudo zip python-pip '
        'python-virtualenv sqlite3 tmux ntp build-essential uwsgi gettext '
        'uwsgi-plugin-python'
    )
    # pillow reqs
    sudo(
        'apt-get install -y libtiff5-dev libjpeg8-dev zlib1g-dev liblcms2-dev '
        'libfreetype6-dev libwebp-dev tcl8.6-dev tk8.6-dev python-tk'
    )
    # letsencrypt
    _setup_letsencrypt()
    # nodejs
    _setup_nodejs()
    # yarnpkg
    _setup_yarn()


def _setup_optional():
    _setup_mysql()
    _setup_mongodb()


def _setup_letsencrypt():
    # https://certbot.eff.org/#ubuntutrusty-other
    # for ubuntu 14.04
    certbot_path = '~/certbot-auto'
    run('rm -f %s' % certbot_path, warn_only=True)
    run('wget https://dl.eff.org/certbot-auto -O %s' % certbot_path)
    run('chmod a+x %s' % certbot_path)
    print '-' * 56
    print 'Usage: %s certonly -d example.com -d www.example.com'
    print '-' * 56


def _setup_nodejs():
    dist_url = 'https://nodejs.org/dist/v7.3.0/node-v7.3.0-linux-x64.tar.xz'
    run('wget -O /tmp/node.tar.xz %s' % dist_url)
    sudo(
        'tar -C /usr/ --exclude CHANGELOG.md --exclude LICENSE '
        '--exclude README.md --strip-components 1 -xf /tmp/node.tar.xz'
    )


def _setup_yarn():
    sudo('curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add -')
    sudo(
        'echo "deb https://dl.yarnpkg.com/debian/ stable main" | '
        'tee /etc/apt/sources.list.d/yarn.list'
    )
    sudo('apt-get update && apt-get install yarn')


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


def _setup_mongodb():
    # ubuntu 14.04
    sudo(
        'apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 '
        '--recv 0C49F3730359A14518585931BC711F9BA15703C6'
    )
    sudo(
        'echo "deb [ arch=amd64 ] http://repo.mongodb.org/apt/ubuntu '
        'trusty/mongodb-org/3.4 multiverse" | tee '
        '/etc/apt/sources.list.d/mongodb-org-3.4.list'
    )
    sudo('apt-get update && apt-get install -y mongodb-org')
